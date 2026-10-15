import { apiJson } from '@/lib/api'

export type InterventionDecision = 'continue' | 'skip' | 'stop'

export const interventionService = {
  /** Resolve a human-in-the-loop pause raised by the emulator exploration. */
  async resolve(jobId: string, interventionId: string, decision: InterventionDecision) {
    const result = await apiJson<{ success: boolean; message?: string }>(
      `/api/v1/analyze-apk/${jobId}/intervention/${interventionId}/${decision}`,
      { method: 'POST' },
      'Unable to send your response',
    )
    if (!result.success) throw new Error(result.message ?? 'The action could not be applied')
    return result
  },
}
