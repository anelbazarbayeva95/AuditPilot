/** Shared type guards for the two agents whose raw_data is a {strengths, weaknesses, recommendations, score} shape. */
import type { CopyRawData, VisualRawData } from "@/types/audit"

export function isCopyRawData(data: unknown): data is CopyRawData {
  if (!data || typeof data !== "object") return false
  const candidate = data as Partial<CopyRawData>
  return (
    Array.isArray(candidate.strengths) &&
    Array.isArray(candidate.weaknesses) &&
    Array.isArray(candidate.recommendations)
  )
}

export function isVisualRawData(data: unknown): data is VisualRawData {
  if (!data || typeof data !== "object") return false
  const candidate = data as Partial<VisualRawData>
  return (
    Array.isArray(candidate.strengths) &&
    Array.isArray(candidate.weaknesses) &&
    Array.isArray(candidate.recommendations)
  )
}
