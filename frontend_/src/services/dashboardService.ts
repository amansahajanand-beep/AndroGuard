import { buildReport } from '@/lib/reportBuilder'
import { fetchPersistedResult, loadAllAudits } from '@/services/analysisApi'
import { authService } from '@/services/authService'
import type {
  Audit,
  AuditReport,
  ComplianceArea,
  ComplianceInsight,
  ComplianceStatus,
  DashboardData,
  KpiMetric,
  NotificationItem,
  SubmissionRecommendation,
} from '@/types'

const STATUS_LABEL: Record<ComplianceStatus, string> = {
  COMPLIANT: 'Compliant',
  REVIEW_REQUIRED: 'Review Required',
  NON_COMPLIANT: 'Non-Compliant',
  NOT_VERIFIABLE: 'Not Verifiable',
}

const flat = { label: 'overall', direction: 'flat' as const }

async function loadReports(audits: Audit[]) {
  const done = audits.filter((item) => item.status === 'COMPLETED')
  const reports = await Promise.all(
    done.map(async (audit) => {
      const result = await fetchPersistedResult(audit.id).catch(() => null)
      return result
        ? buildReport({ auditId: audit.id, appName: audit.appName, result, auditDate: audit.completedAt ?? audit.createdAt })
        : null
    }),
  )
  return reports.filter((item): item is AuditReport => item !== null)
}

function aggregateAreas(reports: AuditReport[]): ComplianceArea[] {
  const byId = new Map<string, ComplianceArea[]>()
  for (const report of reports) {
    for (const area of report.complianceByArea) byId.set(area.id, [...(byId.get(area.id) ?? []), area])
  }
  return [...byId.values()].map((items) => {
    const score = Math.round(items.reduce((sum, item) => sum + item.score, 0) / items.length)
    const status: ComplianceStatus = score >= 85 ? 'COMPLIANT' : score >= 50 ? 'REVIEW_REQUIRED' : 'NON_COMPLIANT'
    return { id: items[0].id, name: items[0].name, status, score, summary: `Average across ${items.length} audit(s).` }
  })
}

function aggregateInsights(reports: AuditReport[]): ComplianceInsight[] {
  const counts: Record<ComplianceStatus, number> = { COMPLIANT: 0, REVIEW_REQUIRED: 0, NON_COMPLIANT: 0, NOT_VERIFIABLE: 0 }
  for (const report of reports) for (const area of report.complianceByArea) counts[area.status] += 1
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0)
  return (Object.keys(counts) as ComplianceStatus[]).map((status) => ({
    status,
    label: STATUS_LABEL[status],
    percent: total ? Math.round((counts[status] / total) * 100) : 0,
  }))
}

export const dashboardService = {
  async getOverview(): Promise<DashboardData> {
    const audits = await loadAllAudits()
    const reports = await loadReports(audits)
    const completed = audits.filter((item) => item.status === 'COMPLETED')
    const now = new Date()
    const thisMonth = audits.filter((item) => {
      const date = new Date(item.createdAt)
      return date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear()
    })
    const average = completed.length
      ? Math.round(completed.reduce((sum, item) => sum + item.readinessScore, 0) / completed.length)
      : 0
    const notReady = completed.filter((item) => item.recommendation === 'NOT_READY_FOR_LIVE').length
    const ready = completed.filter((item) => item.recommendation === 'READY_FOR_LIVE').length
    const running = audits.filter((item) => item.status === 'PROCESSING').length

    const kpis: KpiMetric[] = [
      { id: 'apks', label: 'Total APKs Audited', value: String(audits.length), trend: { ...flat, value: String(completed.length), label: 'completed' }, icon: 'apk' },
      { id: 'running', label: 'Audits In Progress', value: String(running), trend: { ...flat, value: '', label: 'running now' }, icon: 'clock' },
      { id: 'ready', label: 'Apps Ready For Live', value: String(ready), trend: { ...flat, value: '', label: 'overall' }, icon: 'shield' },
      { id: 'month', label: 'Audits This Month', value: String(thisMonth.length), trend: { ...flat, value: '', label: 'this month' }, icon: 'calendar' },
      { id: 'readiness', label: 'Average Readiness Score', value: `${average}%`, trend: { ...flat, value: '', label: 'overall' }, icon: 'score' },
      { id: 'not-ready', label: 'Apps Not Ready', value: String(notReady), trend: { ...flat, value: '', label: 'overall' }, icon: 'alert' },
    ]
    const posture: SubmissionRecommendation =
      average >= 85 ? 'READY_FOR_LIVE' : average >= 60 ? 'READY_WITH_CHANGES' : 'NOT_READY_FOR_LIVE'

    return {
      userName: authService.getCurrentSession()?.user.fullName.split(' ')[0] ?? 'there',
      kpis,
      averageReadiness: average,
      insights: aggregateInsights(reports),
      complianceByArea: aggregateAreas(reports),
      recentAudits: audits.slice(0, 5),
      postureRecommendation: posture,
    }
  },

  async getNotifications(): Promise<NotificationItem[]> {
    const audits = await loadAllAudits().catch(() => [] as Audit[])
    return audits.slice(0, 5).map((audit) => ({
      id: audit.id,
      title: audit.status === 'COMPLETED' ? 'Audit completed' : audit.status === 'FAILED' ? 'Audit failed' : 'Audit in progress',
      body: `${audit.appName} (${audit.displayId})`,
      time: new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(audit.createdAt)),
      unread: audit.status === 'PROCESSING',
    }))
  },
}
