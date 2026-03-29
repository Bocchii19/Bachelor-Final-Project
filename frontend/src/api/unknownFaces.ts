/**
 * API hooks — Unknown Faces
 */

import apiClient from "./client";

export interface UnknownFace {
  id: string;
  session_id: string;
  image_path: string;
  best_match_id?: string;
  best_match_name?: string;
  best_match_code?: string;
  best_score?: number;
  zone_id?: string;
  captured_at: string;
  status: string;
  cluster_id?: string;
  cluster_size: number;
  created_at: string;
}

export async function fetchUnknownFaces(
  sessionId?: string,
  status?: string
): Promise<UnknownFace[]> {
  const params: Record<string, string> = {};
  if (sessionId) params.session_id = sessionId;
  if (status) params.status = status;
  const res = await apiClient.get("/unknown-faces", { params });
  return res.data;
}

export async function matchFace(
  faceId: string,
  studentId: string
): Promise<UnknownFace> {
  const res = await apiClient.patch(`/unknown-faces/${faceId}/match`, {
    student_id: studentId,
  });
  return res.data;
}

export async function markStranger(faceId: string): Promise<void> {
  await apiClient.patch(`/unknown-faces/${faceId}/stranger`);
}

export async function markFalsePositive(faceId: string): Promise<void> {
  await apiClient.patch(`/unknown-faces/${faceId}/false-positive`);
}

export async function bulkResolve(data: {
  cluster_id: string;
  action: string;
  student_id?: string;
}): Promise<{ resolved_count: number }> {
  const res = await apiClient.post("/unknown-faces/bulk-resolve", data);
  return res.data;
}
