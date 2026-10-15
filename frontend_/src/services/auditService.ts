import { apiJson } from '@/lib/api'
import type { Audit, AuditFilters, PaginatedAudits, StartAuditInput } from '@/types'
import { fetchJob, loadAllAudits, readJobs, rememberResult, saveJobMeta, toAudit } from '@/services/analysisApi'

export const auditService = {
  async list(filters: AuditFilters, page = 1, pageSize = 8): Promise<PaginatedAudits> {
    let items = await loadAllAudits()
    if (filters.appName) {
      const q = filters.appName.toLowerCase()
      items = items.filter(
        (item) =>
          item.appName.toLowerCase().includes(q) ||
          item.apkName.toLowerCase().includes(q) ||
          item.displayId.toLowerCase().includes(q),
      )
    }
    if (filters.risk) items = items.filter((item) => item.overallRisk === filters.risk)
    if (filters.status) items = items.filter((item) => item.status === filters.status)
    if (filters.readiness) {
      if (filters.readiness === '90+') items = items.filter((item) => item.readinessScore >= 90)
      if (filters.readiness === '70-89') {
        items = items.filter((item) => item.readinessScore >= 70 && item.readinessScore < 90)
      }
      if (filters.readiness === 'below-70') items = items.filter((item) => item.readinessScore < 70)
    }
    if (filters.dateFrom) items = items.filter((item) => item.createdAt.slice(0, 10) >= filters.dateFrom!)
    if (filters.dateTo) items = items.filter((item) => item.createdAt.slice(0, 10) <= filters.dateTo!)

    const total = items.length
    const totalPages = Math.max(1, Math.ceil(total / pageSize))
    const safePage = Math.min(page, totalPages)
    const start = (safePage - 1) * pageSize
    return { items: items.slice(start, start + pageSize), page: safePage, pageSize, total, totalPages }
  },

  async getById(id: string): Promise<Audit> {
    const payload = await fetchJob(id)
    return toAudit(id, payload, readJobs()[id])
  },

  async start(input: StartAuditInput): Promise<Audit> {
    const form = new FormData()
    form.append('file', input.apk, input.apk.name)
    form.append('app_name', input.appName)
    form.append('app_description', input.appDescription)
    if (input.playStoreLink) form.append('play_store_url', input.playStoreLink)
    // The backend accepts a URL or a path reference for the policy, not file content.
    const policy = input.privacyPolicyUrl ?? input.privacyPolicy?.name
    if (policy) form.append('privacy_policy', policy)
    // The file itself, so the backend can read it and compare it with what the app does.
    if (input.privacyPolicy) form.append('privacy_policy_file', input.privacyPolicy, input.privacyPolicy.name)

    let jobId: string
    if (input.explore) {
      // Queued job: the emulator explores the app; progress is polled on the processing page.
      form.append('explore', 'true')
      const created = await apiJson<{ job_id: string }>(
        '/api/v1/analyze-apk',
        { method: 'POST', body: form },
        'Unable to start audit',
      )
      jobId = created.job_id
    } else {
      // Synchronous static analysis: the response is the finished result.
      const result = await apiJson<{ data?: { analysis?: { id?: string } } }>(
        '/api/v1/analyze',
        { method: 'POST', body: form },
        'Unable to start audit',
      )
      const id = result.data?.analysis?.id
      if (!id) throw new Error('The server did not return an audit id')
      rememberResult(id, result as Record<string, unknown>)
      jobId = id
    }
    const created = { job_id: jobId }
    const createdAt = new Date().toISOString()
    saveJobMeta(created.job_id, {
      appName: input.appName,
      appDescription: input.appDescription,
      playStoreLink: input.playStoreLink,
      privacyPolicyName: input.privacyPolicy?.name ?? input.privacyPolicyUrl ?? 'Not provided',
      apkName: input.apk.name,
      apkSize: input.apk.size,
      createdAt,
    })
    return this.getById(created.job_id)
  },

  async cancel(id: string) {
    await apiJson(`/api/v1/analyze-apk/${id}/cancel`, { method: 'POST' }, 'Unable to cancel audit')
  },

  async search(query: string) {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const all = await loadAllAudits()
    return all
      .filter(
        (item) =>
          item.appName.toLowerCase().includes(q) ||
          item.apkName.toLowerCase().includes(q) ||
          item.displayId.toLowerCase().includes(q),
      )
      .slice(0, 6)
  },
}
