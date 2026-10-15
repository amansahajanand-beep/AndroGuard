export type AuditStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type ComplianceStatus =
  | 'COMPLIANT'
  | 'REVIEW_REQUIRED'
  | 'NON_COMPLIANT'
  | 'NOT_VERIFIABLE'
export type SubmissionRecommendation =
  | 'READY_FOR_LIVE'
  | 'READY_WITH_CHANGES'
  | 'NOT_READY_FOR_LIVE'
export type FindingCategory =
  | 'Permissions'
  | 'API'
  | 'SDK'
  | 'Privacy'
  | 'Play Store'
  | 'Advertising'
  | 'User Data'
  | 'Data Safety'
  | 'Other'
export type AuditStageStatus = 'COMPLETED' | 'CURRENT' | 'PENDING' | 'FAILED'

export interface User {
  id: string
  fullName: string
  companyName: string
  email: string
  avatarInitials: string
}

export interface AuthSession {
  user: User
  token: string
}

export interface Trend {
  label: string
  value: string
  direction: 'up' | 'down' | 'flat'
}

export interface KpiMetric {
  id: string
  label: string
  value: string
  trend: Trend
  icon: 'apk' | 'clock' | 'shield' | 'calendar' | 'score' | 'alert'
}

export interface ComplianceInsight {
  status: ComplianceStatus
  label: string
  percent: number
}

export interface ComplianceArea {
  id: string
  name: string
  status: ComplianceStatus
  score: number
  summary: string
}

export interface AuditStage {
  id: string
  label: string
  status: AuditStageStatus
}

export interface Audit {
  id: string
  displayId: string
  appName: string
  apkName: string
  apkSize: number
  privacyPolicyName: string
  packageName: string
  version: string
  targetSdk: number
  playStoreLink?: string
  appDescription: string
  readinessScore: number
  overallRisk: RiskLevel
  recommendation: SubmissionRecommendation
  status: AuditStatus
  progress: number
  currentStageId: string
  stages: AuditStage[]
  createdAt: string
  completedAt?: string
  errorMessage?: string
  intervention?: Intervention
}

export interface Intervention {
  id: string
  typeLabel: string
  title: string
  message: string
  suggestedAction: string
  steps: string[]
  screenshotUrl: string
}

export interface PolicyAssessmentItem {
  id: string
  policyName: string
  requirement: string
  evidence: string
  assessment: ComplianceStatus
}

export interface RiskFinding {
  id: string
  finding: string
  evidence: string
  riskLevel: RiskLevel
  status: ComplianceStatus
  policyRequirement: string
  recommendedAction: string
  category: FindingCategory
}

export interface RecommendationItem {
  id: string
  priority: number
  issue: string
  recommendedAction: string
  status: 'OPEN' | 'IN_PROGRESS' | 'RESOLVED'
}

export interface RiskCounts {
  critical: number
  high: number
  medium: number
  low: number
}

export type AdPositionName = 'top' | 'bottom' | 'middle' | 'fullscreen' | 'unknown'

export interface AdSightingItem {
  /** Seconds after reaching the screen when this layout was first seen. */
  offsetSeconds: number
  adType: string
  position: AdPositionName
  /** [left, top, width, height] as fractions of the screen (0..1). */
  bbox: [number, number, number, number] | null
  coverage: number | null
  isFullscreen: boolean
  screenshotUrl?: string
}

export interface AdScreenReport {
  stateId: string
  page: string
  screenshotUrl?: string
  sightings: AdSightingItem[]
  positionsSeen: AdPositionName[]
  positionChanged: boolean
}

export interface AdAnalysis {
  explored: boolean
  screens: AdScreenReport[]
  totalPlacements: number
  fullscreenCount: number
  positionCounts: Record<string, number>
}

export interface AiReviewFinding {
  title: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  explanation: string
  recommendedFix: string
  /** Ids of the audit facts this finding relies on (see AiReview.evidence). */
  evidenceIds: string[]
}

export interface AiEvidence {
  id: string
  text: string
}

export interface PolicyClaim {
  id: string
  topic: string
  statement: string
  /** Exact text copied from the policy. */
  quote: string
}

export interface PolicyIssue {
  type: 'undisclosed_data_use' | 'contradiction' | 'vague_or_missing'
  severity: 'high' | 'medium' | 'low'
  title: string
  explanation: string
  evidenceIds: string[]
  claimIds: string[]
  recommendedFix: string
}

export interface PolicyAnalysis {
  status: 'analyzed' | 'unavailable' | 'no_policy'
  reason?: string
  summary: string
  claims: PolicyClaim[]
  issues: PolicyIssue[]
  source?: 'url' | 'upload'
  evidence: AiEvidence[]
  charsRead: number
  truncated: boolean
  unsupportedDropped: number
}

export interface AiReview {
  summary: string
  findings: AiReviewFinding[]
  adNotes: string
  evidence: AiEvidence[]
  unsupportedDropped: number
  model: string
  generatedAt: string
  disclaimer: string
}

export interface AuditReport {
  auditId: string
  appName: string
  packageName: string
  version: string
  auditDate: string
  targetSdk: number
  readinessScore: number
  overallRisk: RiskLevel
  recommendation: SubmissionRecommendation
  executiveSummary: string
  submissionReadiness: {
    percent: number
    status: SubmissionRecommendation
    summary: string
  }
  riskCounts: RiskCounts
  policyAssessments: PolicyAssessmentItem[]
  complianceByArea: ComplianceArea[]
  topFindings: RiskFinding[]
  detailedFindings: RiskFinding[]
  missingInformation: string[]
  recommendedActions: RecommendationItem[]
  adAnalysis?: AdAnalysis
  aiReview?: AiReview
  policyAnalysis?: PolicyAnalysis
  limitations: string[]
}

export interface DashboardData {
  userName: string
  kpis: KpiMetric[]
  averageReadiness: number
  insights: ComplianceInsight[]
  complianceByArea: ComplianceArea[]
  recentAudits: Audit[]
  postureRecommendation: SubmissionRecommendation
}

export interface Product {
  id: string
  name: string
  description: string
  href: string
  tone: 'blue' | 'sky' | 'green'
}

export interface NotificationItem {
  id: string
  title: string
  body: string
  time: string
  unread: boolean
}

export interface StartAuditInput {
  appName: string
  appDescription: string
  playStoreLink?: string
  apk: File
  privacyPolicy?: File
  privacyPolicyUrl?: string
  /** true: queue an emulator run (ads, screenshots); false: static analysis only. */
  explore: boolean
}

export interface AuditFilters {
  dateFrom?: string
  dateTo?: string
  appName?: string
  risk?: RiskLevel | ''
  readiness?: string
  status?: AuditStatus | ''
}

export interface PaginatedAudits {
  items: Audit[]
  page: number
  pageSize: number
  total: number
  totalPages: number
}

export interface UpdateProfileInput {
  fullName: string
  companyName: string
}

export interface ChangePasswordInput {
  currentPassword: string
  newPassword: string
}
