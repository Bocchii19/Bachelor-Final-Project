/**
 * Dashboard Page — Overview of attendance system.
 */

import React, { useEffect, useState } from "react";
import {
  Row,
  Col,
  Card,
  Statistic,
  Typography,
  Spin,
  Tag,
  List,
  Space,
} from "antd";
import {
  TeamOutlined,
  CalendarOutlined,
  CheckCircleOutlined,
  QuestionCircleOutlined,
  VideoCameraOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { fetchSessions, type Session } from "../api/sessions";

const { Title, Text } = Typography;

const Dashboard: React.FC = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchSessions()
      .then(setSessions)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const totalSessions = sessions.length;
  const activeSessions = sessions.filter((s) => s.status === "scanning").length;
  const completedSessions = sessions.filter((s) => s.status === "done").length;
  const scheduledSessions = sessions.filter(
    (s) => s.status === "scheduled"
  ).length;

  const recentSessions = sessions.slice(0, 5);

  const statusColors: Record<string, string> = {
    scheduled: "blue",
    scanning: "orange",
    done: "green",
  };

  const statusLabels: Record<string, string> = {
    scheduled: "Đã lên lịch",
    scanning: "Đang quét",
    done: "Hoàn thành",
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        📊 Dashboard
      </Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{ borderRadius: 12, borderLeft: "4px solid #1677ff" }}
          >
            <Statistic
              title="Tổng buổi học"
              value={totalSessions}
              prefix={<CalendarOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{ borderRadius: 12, borderLeft: "4px solid #52c41a" }}
          >
            <Statistic
              title="Hoàn thành"
              value={completedSessions}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: "#52c41a" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{ borderRadius: 12, borderLeft: "4px solid #faad14" }}
          >
            <Statistic
              title="Đang quét"
              value={activeSessions}
              prefix={<VideoCameraOutlined />}
              valueStyle={{ color: "#faad14" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{ borderRadius: 12, borderLeft: "4px solid #722ed1" }}
          >
            <Statistic
              title="Đã lên lịch"
              value={scheduledSessions}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: "#722ed1" }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col xs={24} lg={16}>
          <Card
            title="Buổi học gần đây"
            style={{ borderRadius: 12 }}
            extra={
              <a onClick={() => navigate("/sessions")}>Xem tất cả</a>
            }
          >
            <List
              dataSource={recentSessions}
              renderItem={(session) => (
                <List.Item
                  actions={[
                    <Tag color={statusColors[session.status]} key="status">
                      {statusLabels[session.status] || session.status}
                    </Tag>,
                  ]}
                >
                  <List.Item.Meta
                    title={`Buổi ${new Date(
                      session.session_date
                    ).toLocaleDateString("vi-VN")}`}
                    description={
                      <Space>
                        <Text type="secondary">
                          <TeamOutlined /> {session.enrolled_count} SV
                        </Text>
                        <Text type="secondary">
                          {session.start_time} – {session.end_time}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
              locale={{ emptyText: "Chưa có buổi học nào" }}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="Hệ thống" style={{ borderRadius: 12 }}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "8px 0",
                }}
              >
                <Text>Backend</Text>
                <Tag color="green">Online</Tag>
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "8px 0",
                }}
              >
                <Text>Camera PTZ</Text>
                <Tag color="default">Chưa kết nối</Tag>
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "8px 0",
                }}
              >
                <Text>Celery Worker</Text>
                <Tag color="default">—</Tag>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;
