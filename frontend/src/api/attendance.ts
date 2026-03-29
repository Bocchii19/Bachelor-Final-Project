/**
 * API hooks — Attendance
 */

import apiClient from "./client";

export interface AttendanceCell {
  status: string;
  confidence?: number;
}

export interface StudentRow {
  student_id: string;
  student_code: string;
  full_name: string;
  attendance: Record<string, AttendanceCell>;
  present_count: number;
  total_sessions: number;
  attendance_rate: number;
}

export interface SessionColumn {
  session_id: string;
  session_date: string;
  status: string;
  present_count: number;
  unknown_count: number;
  total_students: number;
}

export interface AttendanceSheetData {
  class_id: string;
  class_name: string;
  subject: string;
  columns: SessionColumn[];
  rows: StudentRow[];
}

export async function fetchAttendanceSheet(
  classId: string,
  dateFrom?: string,
  dateTo?: string
): Promise<AttendanceSheetData> {
  const params: Record<string, string> = { class_id: classId };
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  const res = await apiClient.get("/attendance/sheet", { params });
  return res.data;
}

export async function exportAttendanceExcel(
  classId: string,
  dateFrom?: string,
  dateTo?: string
): Promise<Blob> {
  const params: Record<string, string> = { class_id: classId };
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  const res = await apiClient.get("/attendance/export", {
    params,
    responseType: "blob",
  });
  return res.data;
}
