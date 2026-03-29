/**
 * API hooks — Students
 */

import apiClient from "./client";

export interface Student {
  id: string;
  student_code: string;
  full_name: string;
  email?: string;
  class_id?: string;
  enrolled_at: string;
}

export interface ImportResult {
  inserted: number;
  updated: number;
  errors: string[];
  total_rows: number;
}

export async function fetchStudents(classId?: string): Promise<Student[]> {
  const params: Record<string, string> = {};
  if (classId) params.class_id = classId;
  const res = await apiClient.get("/students", { params });
  return res.data;
}

export async function importStudentsExcel(
  classId: string,
  file: File
): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiClient.post(
    `/students/import?class_id=${classId}`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data;
}

export async function enrollFace(
  studentId: string,
  images: File[]
): Promise<{ embeddings_created: number; errors: string[] }> {
  const formData = new FormData();
  images.forEach((img) => formData.append("images", img));
  const res = await apiClient.post(
    `/students/${studentId}/enroll-face`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data;
}

export async function deleteEmbedding(studentId: string): Promise<void> {
  await apiClient.delete(`/students/${studentId}/embedding`);
}
