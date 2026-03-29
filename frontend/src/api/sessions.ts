/**
 * API hooks — Sessions
 */

import apiClient from "./client";

export interface Session {
  id: string;
  class_id: string;
  session_date: string;
  start_time: string;
  end_time: string;
  enrolled_count: number;
  scan_plan?: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface ScanPlan {
  zones: { id: string; preset: number; pan: number; tilt: number }[];
  sweeps: number;
  dwell_seconds: number;
  move_seconds: number;
  total_seconds: number;
  coverage_threshold: number;
}

export interface CoverageResult {
  session_id: string;
  recognized_count: number;
  enrolled_count: number;
  coverage_pct: number;
  target_pct: number;
  is_sufficient: boolean;
  missing_zones: string[];
}

export async function fetchSessions(
  classId?: string,
  status?: string
): Promise<Session[]> {
  const params: Record<string, string> = {};
  if (classId) params.class_id = classId;
  if (status) params.status = status;
  const res = await apiClient.get("/sessions", { params });
  return res.data;
}

export async function createSession(data: {
  class_id: string;
  session_date: string;
  start_time: string;
  end_time: string;
  enrolled_count: number;
}): Promise<Session> {
  const res = await apiClient.post("/sessions", data);
  return res.data;
}

export async function startScan(sessionId: string): Promise<Session> {
  const res = await apiClient.post(`/sessions/${sessionId}/start-scan`);
  return res.data;
}

export async function fetchScanPlan(
  sessionId: string
): Promise<ScanPlan> {
  const res = await apiClient.get(`/sessions/${sessionId}/scan-plan`);
  return res.data;
}

export async function fetchCoverage(
  sessionId: string
): Promise<CoverageResult> {
  const res = await apiClient.get(`/sessions/${sessionId}/coverage`);
  return res.data;
}
