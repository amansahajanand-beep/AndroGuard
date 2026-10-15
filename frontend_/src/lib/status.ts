import type { AuditStatus, ComplianceStatus, RiskLevel, SubmissionRecommendation } from '@/types'

export function complianceLabel(status: ComplianceStatus) {
  switch (status) {
    case 'COMPLIANT':
      return 'Compliant'
    case 'REVIEW_REQUIRED':
      return 'Review Required'
    case 'NON_COMPLIANT':
      return 'Non-Compliant'
    case 'NOT_VERIFIABLE':
      return 'Not Verifiable'
  }
}

export function auditStatusLabel(status: AuditStatus) {
  switch (status) {
    case 'PENDING':
      return 'Pending'
    case 'PROCESSING':
      return 'Processing'
    case 'COMPLETED':
      return 'Completed'
    case 'FAILED':
      return 'Failed'
  }
}

export function riskLabel(risk: RiskLevel) {
  switch (risk) {
    case 'CRITICAL':
      return 'Critical'
    case 'HIGH':
      return 'High'
    case 'MEDIUM':
      return 'Medium'
    case 'LOW':
      return 'Low'
  }
}

export function recommendationLabel(value: SubmissionRecommendation) {
  switch (value) {
    case 'READY_FOR_LIVE':
      return 'READY FOR LIVE'
    case 'READY_WITH_CHANGES':
      return 'READY WITH CHANGES'
    case 'NOT_READY_FOR_LIVE':
      return 'NOT READY FOR LIVE'
  }
}

export function recommendationTone(value: SubmissionRecommendation): 'success' | 'warning' | 'danger' {
  if (value === 'READY_FOR_LIVE') return 'success'
  if (value === 'READY_WITH_CHANGES') return 'warning'
  return 'danger'
}
