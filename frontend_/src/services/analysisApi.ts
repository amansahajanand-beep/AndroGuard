import { apiJson, ApiError } from '@/lib/api'
import { readSession } from '@/mock/store'
import { appNameFromResult, buildReport } from '@/lib/reportBuilder'
import type { Audit, AuditReport, AuditStage, AuditStatus, Intervention } from '@/types'

/* eslint-disable @typescript-eslint/no-explicit-any */
type Json = Record<string, any>

const LEGACY_JOBS_KEY = 'androguard.jobs'

/** Submission details are kept per user: a shared key made one user's audit ids visible to the next login. */
function jobsKey(): string | null {
  const userId = readSession()?.user.id
  return userId ? `androguard.jobs.${userId}` : null
}

export interface JobMeta {
  appName: string
  appDescription: string
  playStoreLink?: string
  privacyPolicyName: string
  apkName: string
  apkSize: number
  createdAt: string
}

export interface HistoryRow {
  id: string
  package_name: string | null
  file_name: string | null
  file_size: number | null
  app_name: string | null
  status: string
  created_at: string | null
}

/** Ordered pipeline stages exposed by the backend (`stage` on the job payload). */
const STAGES: Array<{ key: string; label: string }> = [
  { key: 'queued', label: 'Queued' },
  { key: 'static_analysis', label: 'Analyzing APK' },
  { key: 'emulator_boot', label: 'Booting Emulator' },
  { key: 'apk_install', label: 'Installing APK' },
  { key: 'app_launch', label: 'Launching App' },
  { key: 'exploring', label: 'Exploring App' },
  { key: 'ad_analysis', label: 'Analyzing Advertising' },
  { key: 'uploading', label: 'Uploading Artifacts' },
  { key: 'persisting', label: 'Generating Audit Report' },
  { key: 'done', label: 'Audit Completed' },
]

export function displayId(jobId: string) {
  return `AUD-${jobId.replace(/-/g, '').slice(0, 6).toUpperCase()}`
}

/* ---------- local job metadata (submission details the backend does not echo until completion) ---------- */

export function readJobs(): Record<string, JobMeta> {
  const key = jobsKey()
  if (!key) return {}
  try {
    // The old shared key mixed users; it cannot be attributed to anyone, so drop it.
    window.localStorage.removeItem(LEGACY_JOBS_KEY)
    return JSON.parse(window.localStorage.getItem(key) ?? '{}') as Record<string, JobMeta>
  } catch {
    return {}
  }
}

export function saveJobMeta(id: string, meta: JobMeta) {
  try {
    const key = jobsKey()
    if (key) window.localStorage.setItem(key, JSON.stringify({ ...readJobs(), [id]: meta }))
  } catch {
    // storage unavailable; the backend history still lists the job once persisted
  }
}

/* ---------- fetching ---------- */

const resultCache = new Map<string, Json>()

/** Forget cached results (called on logout so the next user in this tab never sees them). */
export function clearResultCache() {
  resultCache.clear()
}

export function rememberResult(id: string, result: Json) {
  resultCache.set(id, result)
}

/** Live job payload; falls back to the persisted analysis for jobs the worker no longer tracks. */
export async function fetchJob(id: string): Promise<Json> {
  try {
    const payload = await apiJson<Json>(`/api/v1/analyze-apk/${id}`, {}, 'Unable to load audit')
    if (payload.json_analysis) resultCache.set(id, payload.json_analysis)
    return payload
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) throw err
    const result = await fetchPersistedResult(id)
    return { job_id: id, status: result.status ?? 'completed', stage: 'done', progress: 100, json_analysis: result }
  }
}

export async function fetchPersistedResult(id: string): Promise<Json> {
  const cached = resultCache.get(id)
  if (cached) return cached
  const result = await apiJson<Json>(`/api/v1/analysis/${id}`, {}, 'Audit not found')
  resultCache.set(id, result)
  return result
}

export async function fetchHistory(limit = 100): Promise<HistoryRow[]> {
  const body = await apiJson<{ items: HistoryRow[] }>(`/api/v1/analyses?limit=${limit}`, {}, 'Unable to load audits')
  return body.items
}

/* ---------- mapping ---------- */

function mapStatus(raw: string): AuditStatus {
  switch (raw) {
    case 'completed':
    case 'partial':
      return 'COMPLETED'
    case 'failed':
    case 'cancelled':
    case 'timeout':
      return 'FAILED'
    default:
      return 'PROCESSING'
  }
}

function buildStages(stage: string, status: AuditStatus): AuditStage[] {
  const key = stage === 'waiting_for_human' ? 'exploring' : stage
  const current = Math.max(0, STAGES.findIndex((item) => item.key === key))
  return STAGES.map((item, index) => ({
    id: item.key,
    label: item.label,
    status:
      status === 'COMPLETED' || index < current
        ? 'COMPLETED'
        : index === current
          ? status === 'FAILED'
            ? 'FAILED'
            : 'CURRENT'
          : 'PENDING',
  }))
}

function mapIntervention(raw: Json | undefined): Intervention | undefined {
  if (!raw) return undefined
  return {
    id: raw.id,
    typeLabel: raw.type_label ?? 'Action required',
    title: raw.title ?? 'Human action required',
    message: raw.message ?? '',
    suggestedAction: raw.suggested_action ?? '',
    steps: Array.isArray(raw.steps) ? raw.steps : [],
    screenshotUrl: raw.screenshot ?? '',
  }
}

export function toAudit(id: string, payload: Json, meta?: JobMeta, row?: HistoryRow): Audit {
  const result: Json | undefined = payload.json_analysis
  const data: Json = result?.data ?? {}
  const status = mapStatus(String(payload.status ?? row?.status ?? 'queued'))
  const apkName = meta?.apkName ?? data.apk?.file_name ?? payload.file_name ?? row?.file_name ?? 'app.apk'
  const appName = meta?.appName || row?.app_name || appNameFromResult(result, apkName.replace(/\.apk$/i, ''))
  const createdAt = meta?.createdAt ?? row?.created_at ?? data.analysis?.analyzed_at ?? new Date().toISOString()

  const audit: Audit = {
    id,
    displayId: displayId(id),
    appName,
    apkName,
    apkSize: meta?.apkSize ?? data.apk?.file_size ?? row?.file_size ?? 0,
    privacyPolicyName: meta?.privacyPolicyName ?? data.submission?.privacy_policy ?? 'Not provided',
    packageName: data.apk?.package_name ?? payload.package_name ?? row?.package_name ?? '',
    version: data.apk?.version_name ?? '',
    targetSdk: data.sdk?.target_sdk ?? 0,
    playStoreLink: meta?.playStoreLink ?? data.submission?.play_store_url ?? undefined,
    appDescription: meta?.appDescription ?? data.submission?.app_description ?? '',
    readinessScore: 0,
    overallRisk: 'LOW',
    recommendation: 'NOT_READY_FOR_LIVE',
    status,
    progress: status === 'COMPLETED' ? 100 : Number(payload.progress ?? 0),
    currentStageId: String(payload.stage ?? 'queued'),
    stages: buildStages(String(payload.stage ?? 'queued'), status),
    createdAt,
    completedAt: status === 'COMPLETED' ? (data.analysis?.analyzed_at ?? createdAt) : undefined,
    errorMessage: payload.error?.message,
    intervention: mapIntervention(payload.intervention),
  }

  if (status === 'COMPLETED' && result) {
    const report = buildReport({ auditId: id, appName, result, auditDate: audit.completedAt ?? createdAt })
    audit.readinessScore = report.readinessScore
    audit.overallRisk = report.overallRisk
    audit.recommendation = report.recommendation
  }
  return audit
}

export async function loadReport(id: string): Promise<AuditReport> {
  const payload = await fetchJob(id)
  const audit = toAudit(id, payload, readJobs()[id])
  if (audit.status === 'FAILED') throw new Error(audit.errorMessage ?? 'The audit did not complete')
  if (audit.status !== 'COMPLETED' || !payload.json_analysis) {
    throw new Error('Report unavailable until the audit is completed')
  }
  return buildReport({
    auditId: id,
    appName: audit.appName,
    result: payload.json_analysis,
    auditDate: audit.completedAt ?? audit.createdAt,
  })
}

/** All audits: backend history merged with locally tracked in-flight jobs, newest first. */
export async function loadAllAudits(): Promise<Audit[]> {
  const [rows, jobs] = await Promise.all([fetchHistory().catch(() => [] as HistoryRow[]), Promise.resolve(readJobs())])
  const known = new Set(rows.map((row) => row.id))

  const fromHistory = await Promise.all(
    rows.map(async (row) => {
      const result = await fetchPersistedResult(row.id).catch(() => undefined)
      return toAudit(row.id, { status: row.status || 'completed', stage: 'done', progress: 100, json_analysis: result }, jobs[row.id], row)
    }),
  )
  const inFlight = await Promise.all(
    Object.keys(jobs)
      .filter((id) => !known.has(id))
      .map((id) => fetchJob(id).then((payload) => toAudit(id, payload, jobs[id])).catch(() => null)),
  )
  return [...fromHistory, ...inFlight.filter((item): item is Audit => item !== null)].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  )
}
