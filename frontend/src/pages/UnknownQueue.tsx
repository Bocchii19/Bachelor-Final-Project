/**
 * UnknownQueue Page — Admin verification queue for unrecognized faces.
 */

import React, { useEffect, useState } from "react";
import {
  Typography,
  Select,
  Row,
  Col,
  Spin,
  message,
  Empty,
  Segmented,
  Modal,
  Space,
  Tag,
  Button,
  Statistic,
} from "antd";
import {
  ClusterOutlined,
  FilterOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";
import FaceCard from "../components/FaceCard/FaceCard";
import {
  fetchUnknownFaces,
  matchFace,
  markStranger,
  markFalsePositive,
  bulkResolve,
  type UnknownFace,
} from "../api/unknownFaces";
import { fetchSessions, type Session } from "../api/sessions";
import { fetchStudents, type Student } from "../api/students";

const { Title, Text } = Typography;

const UnknownQueue: React.FC = () => {
  const [faces, setFaces] = useState<UnknownFace[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [loading, setLoading] = useState(false);
  const [matchModal, setMatchModal] = useState<string | null>(null);
  const [selectedStudent, setSelectedStudent] = useState<string>("");

  useEffect(() => {
    fetchSessions().then(setSessions).catch(console.error);
    fetchStudents().then(setStudents).catch(console.error);
  }, []);

  useEffect(() => {
    loadFaces();
  }, [selectedSession, statusFilter]);

  const loadFaces = async () => {
    setLoading(true);
    try {
      const data = await fetchUnknownFaces(
        selectedSession || undefined,
        statusFilter || undefined
      );
      setFaces(data);
    } catch {
      message.error("Lỗi tải danh sách");
    } finally {
      setLoading(false);
    }
  };

  const handleMatch = async () => {
    if (!matchModal || !selectedStudent) return;
    try {
      await matchFace(matchModal, selectedStudent);
      message.success("Đã xác nhận sinh viên!");
      setMatchModal(null);
      setSelectedStudent("");
      loadFaces();
    } catch {
      message.error("Lỗi xác nhận");
    }
  };

  const handleStranger = async (faceId: string) => {
    try {
      await markStranger(faceId);
      message.success("Đã đánh dấu người lạ");
      loadFaces();
    } catch {
      message.error("Lỗi");
    }
  };

  const handleFalsePositive = async (faceId: string) => {
    try {
      await markFalsePositive(faceId);
      message.success("Đã đánh dấu nhận diện nhầm");
      loadFaces();
    } catch {
      message.error("Lỗi");
    }
  };

  const pendingCount = faces.filter((f) => f.status === "pending").length;

  // Group by clusters
  const clusters = new Map<string, UnknownFace[]>();
  faces.forEach((f) => {
    const key = f.cluster_id || f.id;
    if (!clusters.has(key)) clusters.set(key, []);
    clusters.get(key)!.push(f);
  });

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        🔍 Chưa nhận diện
        {pendingCount > 0 && (
          <Tag color="orange" style={{ marginLeft: 8, fontSize: 14 }}>
            {pendingCount} chờ xử lý
          </Tag>
        )}
      </Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="Tất cả buổi học"
          allowClear
          style={{ width: 240 }}
          onChange={(v) => setSelectedSession(v || "")}
          options={sessions.map((s) => ({
            value: s.id,
            label: `${new Date(s.session_date).toLocaleDateString("vi-VN")} (${s.enrolled_count} SV)`,
          }))}
        />

        <Segmented
          options={[
            { label: "Chờ xử lý", value: "pending" },
            { label: "Đã xử lý", value: "matched" },
            { label: "Người lạ", value: "stranger" },
            { label: "Tất cả", value: "" },
          ]}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as string)}
        />
      </Space>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : faces.length === 0 ? (
        <Empty description="Không có khuôn mặt nào" />
      ) : (
        <Row gutter={[16, 16]}>
          {faces.map((face) => (
            <Col key={face.id} xs={24} sm={12} md={8} lg={6}>
              <FaceCard
                face={face}
                onMatch={(id) => {
                  setMatchModal(id);
                  // Pre-select best match if available
                  const f = faces.find((x) => x.id === id);
                  if (f?.best_match_id) setSelectedStudent(f.best_match_id);
                }}
                onStranger={handleStranger}
                onFalsePositive={handleFalsePositive}
              />
            </Col>
          ))}
        </Row>
      )}

      {/* Match Modal */}
      <Modal
        title="Xác nhận sinh viên"
        open={!!matchModal}
        onOk={handleMatch}
        onCancel={() => setMatchModal(null)}
        okText="Xác nhận"
        cancelText="Hủy"
      >
        <Select
          placeholder="Chọn sinh viên"
          showSearch
          optionFilterProp="children"
          style={{ width: "100%" }}
          value={selectedStudent || undefined}
          onChange={setSelectedStudent}
          options={students.map((s) => ({
            value: s.id,
            label: `${s.student_code} — ${s.full_name}`,
          }))}
        />
      </Modal>
    </div>
  );
};

export default UnknownQueue;
