import { buildReport } from '@/lib/reportBuilder'
import { fetchPersistedResult, loadAllAudits, loadReport } from '@/services/analysisApi'
import type { AuditReport } from '@/types'

export const reportService = {
  getByAuditId(auditId: string): Promise<AuditReport> {
    return loadReport(auditId)
  },

  async listCompleted(): Promise<AuditReport[]> {
    const audits = (await loadAllAudits()).filter((item) => item.status === 'COMPLETED')
    const reports = await Promise.all(
      audits.map(async (audit) => {
        const result = await fetchPersistedResult(audit.id).catch(() => null)
        return result
          ? buildReport({ auditId: audit.id, appName: audit.appName, result, auditDate: audit.completedAt ?? audit.createdAt })
          : null
      }),
    )
    return reports.filter((item): item is AuditReport => item !== null)
  },
}
