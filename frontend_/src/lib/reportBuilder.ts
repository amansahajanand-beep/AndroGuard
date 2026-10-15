import type {
  AdAnalysis,
  AiReview,
  PolicyAnalysis,
  AdPositionName,
  AdScreenReport,
  AuditReport,
  ComplianceArea,
  ComplianceStatus,
  FindingCategory,
  PolicyAssessmentItem,
  RecommendationItem,
  RiskFinding,
  RiskLevel,
  SubmissionRecommendation,
} from '@/types'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = Record<string, any>

/** Minimum targetSdk for new Play submissions; below it the app is flagged. */
const REQUIRED_TARGET_SDK = 35

const SENSITIVE_PERMISSIONS: Record<string, string> = {
  READ_SMS: 'SMS',
  SEND_SMS: 'SMS',
  RECEIVE_SMS: 'SMS',
  READ_CALL_LOG: 'Call log',
  WRITE_CALL_LOG: 'Call log',
  READ_CONTACTS: 'Contacts',
  WRITE_CONTACTS: 'Contacts',
  ACCESS_FINE_LOCATION: 'Location',
  ACCESS_COARSE_LOCATION: 'Location',
  ACCESS_BACKGROUND_LOCATION: 'Background location',
  RECORD_AUDIO: 'Microphone',
  CAMERA: 'Camera',
  READ_PHONE_STATE: 'Phone identity',
  READ_PHONE_NUMBERS: 'Phone identity',
  MANAGE_EXTERNAL_STORAGE: 'All-files access',
  QUERY_ALL_PACKAGES: 'Installed apps list',
  READ_MEDIA_IMAGES: 'Photos',
  READ_MEDIA_VIDEO: 'Videos',
  READ_EXTERNAL_STORAGE: 'Storage',
  SYSTEM_ALERT_WINDOW: 'Draw over other apps',
  REQUEST_INSTALL_PACKAGES: 'Install packages',
  BIND_ACCESSIBILITY_SERVICE: 'Accessibility',
}

const AD_SDK_HINTS = ['admob', 'ads', 'applovin', 'unity', 'ironsource', 'mintegral', 'vungle', 'chartboost', 'audience', 'inmobi', 'pangle', 'adcolony']

const STATUS_SCORE: Record<ComplianceStatus, number> = {
  COMPLIANT: 100,
  REVIEW_REQUIRED: 60,
  NON_COMPLIANT: 25,
  NOT_VERIFIABLE: 40,
}

const list = (value: unknown): Json[] => (Array.isArray(value) ? value : [])

export interface ReportInput {
  auditId: string
  appName: string
  /** The full `json_analysis` document returned by the backend. */
  result: Json
  auditDate: string
}

const POSITIONS: AdPositionName[] = ['top', 'bottom', 'middle', 'fullscreen', 'unknown']

function toPosition(value: unknown): AdPositionName {
  return POSITIONS.includes(value as AdPositionName) ? (value as AdPositionName) : 'unknown'
}

function toBbox(value: unknown): [number, number, number, number] | null {
  return Array.isArray(value) && value.length === 4 && value.every((n) => typeof n === 'number')
    ? (value as [number, number, number, number])
    : null
}

/** Per-screen ad placements, including how they moved while the agent stayed on the screen. */
export function buildAdAnalysis(result: Json): AdAnalysis {
  const exploration: Json = result.data?.exploration ?? {}
  const states = list(exploration.states)
  const urlByState = new Map<string, string>()
  for (const shot of list(exploration.screenshots)) {
    if (shot?.state_id && shot?.url) urlByState.set(String(shot.state_id), String(shot.url))
  }
  const timelineByState = new Map<string, Json>()
  for (const item of list(exploration.ad_timeline)) timelineByState.set(String(item.state_id), item)

  const screens: AdScreenReport[] = []
  const seen = new Set<string>()

  const pageOf = (activity: unknown, fallback: unknown) =>
    String(fallback || String(activity ?? '').split(/[./]/).pop() || 'Screen')

  for (const state of states) {
    const stateId = String(state?.state_id ?? '')
    const timeline = timelineByState.get(stateId)
    let sightings: AdScreenReport['sightings'] = []
    if (timeline) {
      sightings = list(timeline.sightings).map((s) => ({
        offsetSeconds: Number(s.offset_seconds ?? 0),
        adType: String(s.ad_type ?? 'unknown'),
        position: toPosition(s.position),
        bbox: toBbox(s.relative_bbox),
        coverage: typeof s.coverage_ratio === 'number' ? s.coverage_ratio : null,
        isFullscreen: Boolean(s.is_fullscreen),
        screenshotUrl: s.frame_id ? urlByState.get(String(s.frame_id)) : undefined,
      }))
    } else {
      sightings = list(state?.ad_placements)
        .filter((p) => p?.ad_detected)
        .map((p) => ({
          offsetSeconds: 0,
          adType: String(p.ad_type ?? 'unknown'),
          position: toPosition(p.position),
          bbox: toBbox(p.relative_bbox),
          coverage: typeof p.coverage_ratio === 'number' ? p.coverage_ratio : null,
          isFullscreen: Boolean(p.is_fullscreen),
        }))
    }
    if (!sightings.length) continue
    seen.add(stateId)
    const positionsSeen = [...new Set(sightings.map((s) => s.position))]
    screens.push({
      stateId,
      page: pageOf(state?.activity, state?.label),
      screenshotUrl: urlByState.get(stateId),
      sightings,
      positionsSeen,
      positionChanged: positionsSeen.length > 1,
    })
  }

  // Timelines for screens the state list no longer holds (e.g. an ad screen reached once).
  for (const [stateId, timeline] of timelineByState) {
    if (seen.has(stateId)) continue
    const sightings = list(timeline.sightings).map((s) => ({
      offsetSeconds: Number(s.offset_seconds ?? 0),
      adType: String(s.ad_type ?? 'unknown'),
      position: toPosition(s.position),
      bbox: toBbox(s.relative_bbox),
      coverage: typeof s.coverage_ratio === 'number' ? s.coverage_ratio : null,
      isFullscreen: Boolean(s.is_fullscreen),
      screenshotUrl: s.frame_id ? urlByState.get(String(s.frame_id)) : undefined,
    }))
    if (!sightings.length) continue
    const positionsSeen = [...new Set(sightings.map((s) => s.position))]
    screens.push({
      stateId,
      page: pageOf(timeline.activity, timeline.page),
      screenshotUrl: urlByState.get(stateId),
      sightings,
      positionsSeen,
      positionChanged: positionsSeen.length > 1,
    })
  }

  const positionCounts: Record<string, number> = {}
  let total = 0
  let fullscreen = 0
  for (const screen of screens) {
    for (const s of screen.sightings) {
      total += 1
      positionCounts[s.position] = (positionCounts[s.position] ?? 0) + 1
      if (s.isFullscreen) fullscreen += 1
    }
  }
  const explored = exploration.status === 'completed' || exploration.status === 'partial' || states.length > 0
  return { explored, screens, totalPlacements: total, fullscreenCount: fullscreen, positionCounts }
}

/** AI-written review stored by the backend under data.ai_review (absent when AI reporting is off). */
export function buildAiReview(result: Json): AiReview | undefined {
  const raw: Json | undefined = result.data?.ai_review
  if (!raw || typeof raw.summary !== 'string' || !raw.summary.trim()) return undefined
  const severities = ['critical', 'high', 'medium', 'low']
  return {
    summary: raw.summary,
    findings: list(raw.findings)
      .filter((item) => typeof item?.title === 'string' && item.title.trim())
      .map((item) => ({
        title: String(item.title),
        severity: (severities.includes(item.severity) ? item.severity : 'medium') as AiReview['findings'][number]['severity'],
        explanation: String(item.explanation ?? ''),
        recommendedFix: String(item.recommended_fix ?? ''),
        evidenceIds: list(item.evidence_ids).map(String),
      })),
    adNotes: String(raw.ad_notes ?? ''),
    evidence: list(raw.evidence).map((e) => ({ id: String(e.id), text: String(e.text ?? '') })),
    unsupportedDropped: Number(raw.unsupported_dropped ?? 0),
    model: String(raw.model ?? ''),
    generatedAt: String(raw.generated_at ?? ''),
    disclaimer: String(raw.disclaimer ?? ''),
  }
}

/** Privacy policy compared with the app's behaviour (data.ai_policy_analysis). */
export function buildPolicyAnalysis(result: Json): PolicyAnalysis | undefined {
  const raw: Json | undefined = result.data?.ai_policy_analysis
  if (!raw || typeof raw.status !== 'string') return undefined
  const severities = ['high', 'medium', 'low']
  return {
    status: raw.status as PolicyAnalysis['status'],
    reason: raw.reason ? String(raw.reason) : undefined,
    summary: String(raw.summary ?? ''),
    claims: list(raw.claims).map((c) => ({
      id: String(c.id),
      topic: String(c.topic ?? 'other'),
      statement: String(c.statement ?? ''),
      quote: String(c.quote ?? ''),
    })),
    issues: list(raw.issues).map((i) => ({
      type: i.type,
      severity: (severities.includes(i.severity) ? i.severity : 'medium') as 'high' | 'medium' | 'low',
      title: String(i.title ?? ''),
      explanation: String(i.explanation ?? ''),
      evidenceIds: list(i.evidence_ids).map(String),
      claimIds: list(i.claim_ids).map(String),
      recommendedFix: String(i.recommended_fix ?? ''),
    })),
    source: raw.source,
    evidence: list(raw.evidence).map((e) => ({ id: String(e.id), text: String(e.text ?? '') })),
    charsRead: Number(raw.chars_read ?? 0),
    truncated: Boolean(raw.truncated),
    unsupportedDropped: Number(raw.unsupported_dropped ?? 0),
  }
}

export function appNameFromResult(result: Json | null | undefined, fallback: string): string {
  const data = result?.data ?? {}
  return data.submission?.app_name || data.manifest?.app_label || fallback
}

function adEvidence(result: Json) {
  const data = result.data ?? {}
  const states = list(data.exploration?.states)
  let placements = 0
  for (const state of states) {
    if (list(state?.ad_placements).some((p) => p?.ad_detected)) placements += 1
    else if (state?.screenshot?.ad_detected) placements += 1
  }
  const sdks = list(data.code_analysis?.third_party_sdk_usage)
    .map((sdk) => String(sdk?.name ?? ''))
    .filter((name) => AD_SDK_HINTS.some((hint) => name.toLowerCase().includes(hint)))
  const explored = data.exploration?.status === 'completed' || states.length > 0
  return { placements, sdks, explored }
}

function sensitivePermissions(result: Json) {
  const found = new Map<string, string>()
  for (const perm of list(result.data?.permissions)) {
    const short = String(perm?.name ?? '').split('.').pop() ?? ''
    if (SENSITIVE_PERMISSIONS[short]) found.set(short, SENSITIVE_PERMISSIONS[short])
  }
  return found
}

export function buildReport(input: ReportInput): AuditReport {
  const { auditId, appName, result, auditDate } = input
  const data: Json = result.data ?? {}
  const manifest: Json = data.manifest ?? {}
  const targetSdk: number = data.sdk?.target_sdk ?? 0
  const code: Json = data.code_analysis ?? {}
  const policy: string | null = data.submission?.privacy_policy ?? null
  const sensitive = sensitivePermissions(result)
  const ads = adEvidence(result)
  const dataAccess = list(code.data_access_indicators).length + list(code.telephony_calls).length
  const network = list(code.network_calls).length
  const sdkCount = list(code.third_party_sdk_usage).length
  const dynamicLoading = list(code.dynamic_code_loading).length

  const findings: RiskFinding[] = []
  const policyAssessments: PolicyAssessmentItem[] = []
  const areas: ComplianceArea[] = []
  const actions: RecommendationItem[] = []
  const missing: string[] = []

  function addArea(
    id: string,
    name: string,
    policyName: string,
    requirement: string,
    status: ComplianceStatus,
    summary: string,
    evidence: string,
    finding?: { title: string; risk: RiskLevel; category: FindingCategory; action: string },
  ) {
    areas.push({ id, name, status, score: STATUS_SCORE[status], summary })
    policyAssessments.push({ id: `p-${id}`, policyName, requirement, evidence, assessment: status })
    if (finding && status !== 'COMPLIANT') {
      findings.push({
        id: `${auditId}-${id}`,
        finding: finding.title,
        evidence,
        riskLevel: finding.risk,
        status,
        policyRequirement: requirement,
        recommendedAction: finding.action,
        category: finding.category,
      })
      actions.push({
        id: `${auditId}-a-${id}`,
        priority: 0,
        issue: finding.title,
        recommendedAction: finding.action,
        status: 'OPEN',
      })
    }
  }

  // Target API
  const apiStatus: ComplianceStatus = !targetSdk
    ? 'NOT_VERIFIABLE'
    : targetSdk >= REQUIRED_TARGET_SDK
      ? 'COMPLIANT'
      : targetSdk >= REQUIRED_TARGET_SDK - 1
        ? 'REVIEW_REQUIRED'
        : 'NON_COMPLIANT'
  addArea(
    'target-api', 'Target API', 'TARGET_API_CURRENT',
    `Application must target API ${REQUIRED_TARGET_SDK} or higher.`,
    apiStatus,
    apiStatus === 'COMPLIANT' ? 'Meets current target API guidance.' : 'Target API is below current Play guidance.',
    targetSdk ? `targetSdkVersion = ${targetSdk}` : 'targetSdkVersion could not be read from the manifest.',
    { title: 'Outdated target API level', risk: apiStatus === 'NON_COMPLIANT' ? 'HIGH' : 'MEDIUM', category: 'API', action: `Raise targetSdkVersion to ${REQUIRED_TARGET_SDK} or higher.` },
  )

  // Permissions
  const permGroups = [...new Set(sensitive.values())]
  const permStatus: ComplianceStatus =
    sensitive.size === 0
      ? 'COMPLIANT'
      : sensitive.size > 4 || permGroups.includes('SMS') || permGroups.includes('Call log')
        ? 'NON_COMPLIANT'
        : 'REVIEW_REQUIRED'
  addArea(
    'permissions', 'Permissions', 'SENSITIVE_PERMISSIONS',
    'Sensitive permissions must be justified and disclosed.',
    permStatus,
    sensitive.size ? `${sensitive.size} sensitive permission(s) declared.` : 'No sensitive permissions declared.',
    sensitive.size ? `Declared: ${[...sensitive.keys()].join(', ')}` : 'No sensitive permissions found in the manifest.',
    { title: 'Sensitive permissions declared', risk: permStatus === 'NON_COMPLIANT' ? 'HIGH' : 'MEDIUM', category: 'Permissions', action: 'Remove unused permissions and add prominent in-app disclosures for the rest.' },
  )

  // User data
  const dataStatus: ComplianceStatus =
    dataAccess === 0 && sensitive.size === 0 ? 'COMPLIANT' : policy ? 'REVIEW_REQUIRED' : 'NON_COMPLIANT'
  addArea(
    'user-data', 'User Data', 'USER_DATA_DISCLOSURE',
    'User data collection must be disclosed.',
    dataStatus,
    dataStatus === 'COMPLIANT' ? 'No user data access detected.' : 'Data access detected; disclosure must be confirmed.',
    `${dataAccess} data-access / telephony API call(s) found in app code.`,
    { title: 'User data disclosure', risk: dataStatus === 'NON_COMPLIANT' ? 'HIGH' : 'MEDIUM', category: 'User Data', action: 'Disclose collected data types, purpose, sharing and retention.' },
  )

  // Privacy policy
  const policyStatus: ComplianceStatus = !policy
    ? 'NON_COMPLIANT'
    : policy.startsWith('http')
      ? 'REVIEW_REQUIRED'
      : 'NOT_VERIFIABLE'
  addArea(
    'privacy-policy', 'Privacy Policy', 'PRIVACY_POLICY',
    'A privacy policy must accurately describe data practices.',
    policyStatus,
    policy ? 'Policy supplied; content is not machine-verified.' : 'No privacy policy was supplied.',
    policy ? `Privacy policy reference: ${policy}` : 'No privacy policy URL or file was provided with the submission.',
    { title: 'Privacy policy review', risk: policy ? 'MEDIUM' : 'HIGH', category: 'Privacy', action: 'Provide a public privacy policy URL that matches the observed app behavior.' },
  )

  // Data safety
  const safetyStatus: ComplianceStatus = network + sdkCount === 0 ? 'COMPLIANT' : 'NOT_VERIFIABLE'
  addArea(
    'data-safety', 'Data Safety', 'DATA_SAFETY',
    'Data Safety must match actual app behavior.',
    safetyStatus,
    safetyStatus === 'COMPLIANT' ? 'No network or SDK data flows detected.' : 'Data Safety form is not available to compare.',
    `${network} network call(s) and ${sdkCount} third-party SDK(s) detected.`,
    { title: 'Data Safety cannot be verified', risk: 'MEDIUM', category: 'Data Safety', action: 'Make sure the Data Safety form declares data collected by the app and its SDKs.' },
  )
  if (safetyStatus !== 'COMPLIANT') missing.push('Data Safety form was not supplied for comparison.')

  // Advertising
  const adStatus: ComplianceStatus =
    ads.placements > 0 || ads.sdks.length > 0 ? 'REVIEW_REQUIRED' : ads.explored ? 'COMPLIANT' : 'NOT_VERIFIABLE'
  addArea(
    'advertising', 'Advertising', 'ADS',
    'Advertising use must be declared when applicable.',
    adStatus,
    adStatus === 'REVIEW_REQUIRED'
      ? 'Advertising detected; confirm the Play Console ads declaration.'
      : adStatus === 'COMPLIANT'
        ? 'No advertising detected during exploration.'
        : 'Advertising could not be verified.',
    `${ads.placements} screen(s) with ads observed; ad SDKs: ${ads.sdks.join(', ') || 'none'}.`,
    { title: 'Advertising declaration', risk: 'MEDIUM', category: 'Advertising', action: 'Declare "Contains ads" in Play Console and review ad placement policy.' },
  )
  if (!ads.explored) missing.push('Dynamic exploration did not run, so advertising could not be verified.')

  // Deceptive behaviour / integrity
  const integrity: string[] = []
  if (manifest.debuggable) integrity.push('app is debuggable')
  if (manifest.uses_cleartext_traffic) integrity.push('cleartext traffic allowed')
  if (dynamicLoading) integrity.push(`${dynamicLoading} dynamic code loading call(s)`)
  const integrityStatus: ComplianceStatus = integrity.length ? 'REVIEW_REQUIRED' : 'COMPLIANT'
  addArea(
    'deceptive', 'Deceptive Behaviour', 'DECEPTIVE_BEHAVIOR',
    'Apps must not mislead users or load unreviewed code.',
    integrityStatus,
    integrity.length ? 'Integrity indicators need review.' : 'No deceptive behavior indicators found.',
    integrity.length ? `Indicators: ${integrity.join('; ')}.` : 'No debuggable flag, cleartext traffic or dynamic code loading found.',
    { title: 'App integrity indicators', risk: manifest.debuggable ? 'HIGH' : 'MEDIUM', category: 'Other', action: 'Disable debuggable builds, enforce HTTPS and avoid loading code outside the APK.' },
  )

  const rank: Record<RiskLevel, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
  findings.sort((a, b) => rank[a.riskLevel] - rank[b.riskLevel])
  actions.forEach((item, index) => {
    item.priority = index + 1
  })

  const readiness = Math.round(areas.reduce((sum, area) => sum + area.score, 0) / areas.length)
  const riskCounts = {
    critical: findings.filter((f) => f.riskLevel === 'CRITICAL').length,
    high: findings.filter((f) => f.riskLevel === 'HIGH').length,
    medium: findings.filter((f) => f.riskLevel === 'MEDIUM').length,
    low: findings.filter((f) => f.riskLevel === 'LOW').length,
  }
  const overallRisk: RiskLevel = riskCounts.critical ? 'CRITICAL' : riskCounts.high ? 'HIGH' : riskCounts.medium ? 'MEDIUM' : 'LOW'
  const blockers = areas.filter((a) => a.status === 'NON_COMPLIANT')
  const recommendation: SubmissionRecommendation =
    blockers.length || readiness < 60 ? 'NOT_READY_FOR_LIVE' : readiness >= 85 ? 'READY_FOR_LIVE' : 'READY_WITH_CHANGES'
  const summaryText =
    recommendation === 'READY_FOR_LIVE'
      ? 'No blocking issues were found in the static and dynamic analysis.'
      : `${findings.length} item(s) need attention before submission${blockers.length ? `, including ${blockers.map((a) => a.name).join(', ')}` : ''}.`

  return {
    auditId,
    appName,
    packageName: data.apk?.package_name ?? manifest.package ?? '',
    version: data.apk?.version_name ?? manifest.version_name ?? '',
    auditDate,
    targetSdk,
    readinessScore: readiness,
    overallRisk,
    recommendation,
    executiveSummary: `${appName} was analysed statically${ads.explored ? ' and explored on an emulator' : ''}. ${summaryText}`,
    submissionReadiness: { percent: readiness, status: recommendation, summary: summaryText },
    riskCounts,
    policyAssessments,
    complianceByArea: areas,
    topFindings: findings.slice(0, 3),
    detailedFindings: findings,
    missingInformation: missing,
    recommendedActions: actions,
    adAnalysis: buildAdAnalysis(result),
    aiReview: buildAiReview(result),
    policyAnalysis: buildPolicyAnalysis(result),
    limitations: [
      'Findings are derived from static APK analysis and automated emulator exploration.',
      'Privacy policy and Data Safety content are not machine-verified.',
      'This audit does not replace official Google Play Console review.',
    ],
  }
}
