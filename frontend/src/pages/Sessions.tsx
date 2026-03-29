/**
 * Sessions Page — Manage class sessions and trigger scans.
 */

import React, { useEffect, useState } from "react";
import {
  Typography,
  Table,
  Tag,
  Button,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  DatePicker,
  TimePicker,
  Select,
  message,
  Spin,
  Drawer,
} from "antd";
import {
  PlusOutlined,
  PlayCircleOutlined,
  EyeOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  fetchSessions,
  createSession,
  startScan,
  fetchCoverage,
  type Session,
  type CoverageResult,
} from "../api/sessions";
import ScanPlanBadge from "../components/ScanPlanBadge/ScanPlanBadge";
import apiClient from "../api/client";

const { Title } = Typography;

const statusConfig: Record<string, { color: string; label: string }> = {
  scheduled: { color: "blue", label: "Đã lên lịch" },
  scanning: { color: "processing", label: "Đang quét ..." },
  done: { color: "green", label: "Hoàn thành" },
};

const Sessions: React.FC = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [classes, setClasses] = useState<{ id: string; name: string; subject: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailDrawer, setDetailDrawer] = useState<Session | null>(null);
  const [coverage, setCoverage] = useState<CoverageResult | null>(null);
  const [form] = Form.useForm();

  const loadAll = async () => {
    setLoading(true);
    try {
      const [sessionsData, classesData] = await Promise.all([
        fetchSessions(),
        apiClient.get("/classes").then((r) => r.data),
      ]);
      setSessions(sessionsData);
      setClasses(classesData);
    } catch {
      message.error("Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      await createSession({
        class_id: values.class_id as string,
        session_date: (values.session_date as dayjs.Dayjs).format("YYYY-MM-DD"),
        start_time: (values.start_time as dayjs.Dayjs).format("HH:mm:ss"),
        end_time: (values.end_time as dayjs.Dayjs).format("HH:mm:ss"),
        enrolled_count: values.enrolled_count as number,
      });
      message.success("Tạo buổi học thành công!");
      setCreateOpen(false);
      form.resetFields();
      loadAll();
    } catch {
      message.error("Lỗi tạo buổi học");
    }
  };

  const handleStartScan = async (sessionId: string) => {
    try {
      await startScan(sessionId);
      message.success("Đã kích hoạt quét!");
      loadAll();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      message.error(error.response?.data?.detail || "Lỗi kích hoạt quét");
    }
  };

  const showDetail = async (session: Session) => {
    setDetailDrawer(session);
    if (session.status !== "scheduled") {
      try {
        const cov = await fetchCoverage(session.id);
        setCoverage(cov);
      } catch {
        setCoverage(null);
      }
    }
  };

  const columns: ColumnsType<Session> = [
    {
      title: "Ngày",
      dataIndex: "session_date",
      key: "date",
      render: (d: string) =>
        new Date(d).toLocaleDateString("vi-VN", {
          weekday: "short",
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        }),
      sorter: (a, b) => a.session_date.localeCompare(b.session_date),
      defaultSortOrder: "descend",
    },
    {
      title: "Thời gian",
      key: "time",
      render: (_, r) => `${r.start_time} – ${r.end_time}`,
    },
    {
      title: "Sĩ số",
      dataIndex: "enrolled_count",
      key: "enrolled",
      align: "center",
    },
    {
      title: "Trạng thái",
      dataIndex: "status",
      key: "status",
      render: (s: string) => {
        const cfg = statusConfig[s] || { color: "default", label: s };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: "Hành động",
      key: "actions",
      render: (_, record) => (
        <Space>
          {record.status === "scheduled" && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              size="small"
              onClick={() => handleStartScan(record.id)}
            >
              Bắt đầu quét
            </Button>
          )}
          <Button
            icon={<EyeOutlined />}
            size="small"
            onClick={() => showDetail(record)}
          >
            Chi tiết
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <Title level={3} style={{ margin: 0 }}>
          📅 Quản lý buổi học
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadAll}>
            Tải lại
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            Tạo buổi học
          </Button>
        </Space>
      </div>

      <Table<Session>
        columns={columns}
        dataSource={sessions}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
        style={{ borderRadius: 8 }}
      />

      {/* Create Modal */}
      <Modal
        title="Tạo buổi học mới"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="Tạo"
        cancelText="Hủy"
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="class_id" label="Lớp học" rules={[{ required: true }]}>
            <Select
              placeholder="Chọn lớp"
              options={classes.map((c) => ({
                value: c.id,
                label: `${c.name} — ${c.subject}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="session_date"
            label="Ngày"
            rules={[{ required: true }]}
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Space>
            <Form.Item
              name="start_time"
              label="Giờ bắt đầu"
              rules={[{ required: true }]}
            >
              <TimePicker format="HH:mm" />
            </Form.Item>
            <Form.Item
              name="end_time"
              label="Giờ kết thúc"
              rules={[{ required: true }]}
            >
              <TimePicker format="HH:mm" />
            </Form.Item>
          </Space>
          <Form.Item
            name="enrolled_count"
            label="Sĩ số"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={500} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Drawer */}
      <Drawer
        title="Chi tiết buổi học"
        open={!!detailDrawer}
        onClose={() => {
          setDetailDrawer(null);
          setCoverage(null);
        }}
        width={480}
      >
        {detailDrawer && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <ScanPlanBadge
              plan={detailDrawer.scan_plan as never}
              coverage={
                coverage
                  ? {
                      coverage_pct: coverage.coverage_pct,
                      target_pct: coverage.target_pct,
                      is_sufficient: coverage.is_sufficient,
                      recognized_count: coverage.recognized_count,
                      enrolled_count: coverage.enrolled_count,
                    }
                  : undefined
              }
            />
          </Space>
        )}
      </Drawer>
    </div>
  );
};

export default Sessions;
