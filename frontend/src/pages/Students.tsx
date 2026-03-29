/**
 * Students Page — Manage students, import Excel, face enrollment.
 */

import React, { useEffect, useState } from "react";
import {
  Typography,
  Table,
  Button,
  Space,
  Upload,
  message,
  Select,
  Modal,
  Tag,
  Popconfirm,
  Descriptions,
  Result,
} from "antd";
import {
  UploadOutlined,
  UserOutlined,
  DeleteOutlined,
  CameraOutlined,
  FileExcelOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile } from "antd";
import {
  fetchStudents,
  importStudentsExcel,
  enrollFace,
  deleteEmbedding,
  type Student,
  type ImportResult,
} from "../api/students";
import apiClient from "../api/client";

const { Title, Text } = Typography;

const Students: React.FC = () => {
  const [students, setStudents] = useState<Student[]>([]);
  const [classes, setClasses] = useState<{ id: string; name: string; subject: string }[]>([]);
  const [selectedClass, setSelectedClass] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [enrollModal, setEnrollModal] = useState<string | null>(null);
  const [enrollFiles, setEnrollFiles] = useState<UploadFile[]>([]);

  useEffect(() => {
    apiClient.get("/classes").then((r) => setClasses(r.data)).catch(console.error);
  }, []);

  useEffect(() => {
    if (selectedClass) loadStudents();
  }, [selectedClass]);

  const loadStudents = async () => {
    setLoading(true);
    try {
      const data = await fetchStudents(selectedClass || undefined);
      setStudents(data);
    } catch {
      message.error("Lỗi tải danh sách sinh viên");
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async (file: File) => {
    if (!selectedClass) {
      message.warning("Vui lòng chọn lớp trước");
      return;
    }
    try {
      const result = await importStudentsExcel(selectedClass, file);
      setImportResult(result);
      message.success(
        `Import thành công: ${result.inserted} mới, ${result.updated} cập nhật`
      );
      loadStudents();
    } catch {
      message.error("Lỗi import file Excel");
    }
  };

  const handleEnrollFace = async () => {
    if (!enrollModal || enrollFiles.length === 0) return;
    try {
      const files = enrollFiles
        .map((f) => f.originFileObj)
        .filter((f): f is File => !!f);
      const result = await enrollFace(enrollModal, files);
      if (result.embeddings_created > 0) {
        message.success(
          `Đăng ký thành công ${result.embeddings_created} khuôn mặt!`
        );
      }
      if (result.errors.length > 0) {
        message.warning(`Có ${result.errors.length} lỗi: ${result.errors[0]}`);
      }
      setEnrollModal(null);
      setEnrollFiles([]);
    } catch {
      message.error("Lỗi đăng ký khuôn mặt");
    }
  };

  const handleDeleteEmbedding = async (studentId: string) => {
    try {
      await deleteEmbedding(studentId);
      message.success("Đã xóa embedding");
    } catch {
      message.error("Lỗi xóa embedding");
    }
  };

  const columns: ColumnsType<Student> = [
    {
      title: "MSSV",
      dataIndex: "student_code",
      key: "student_code",
      sorter: (a, b) => a.student_code.localeCompare(b.student_code),
    },
    {
      title: "Họ và tên",
      dataIndex: "full_name",
      key: "full_name",
      sorter: (a, b) => a.full_name.localeCompare(b.full_name),
    },
    {
      title: "Email",
      dataIndex: "email",
      key: "email",
      render: (email: string) => email || <Text type="secondary">—</Text>,
    },
    {
      title: "Ngày đăng ký",
      dataIndex: "enrolled_at",
      key: "enrolled_at",
      render: (d: string) =>
        new Date(d).toLocaleDateString("vi-VN"),
    },
    {
      title: "Hành động",
      key: "actions",
      render: (_, record) => (
        <Space>
          <Button
            icon={<CameraOutlined />}
            size="small"
            onClick={() => setEnrollModal(record.id)}
          >
            Đăng ký mặt
          </Button>
          <Popconfirm
            title="Xóa tất cả embedding?"
            onConfirm={() => handleDeleteEmbedding(record.id)}
          >
            <Button icon={<DeleteOutlined />} size="small" danger />
          </Popconfirm>
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
          👨‍🎓 Quản lý sinh viên
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadStudents}>
            Tải lại
          </Button>
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="Chọn lớp học"
          style={{ width: 280 }}
          value={selectedClass || undefined}
          onChange={setSelectedClass}
          showSearch
          optionFilterProp="children"
          options={classes.map((c) => ({
            value: c.id,
            label: `${c.name} — ${c.subject}`,
          }))}
        />

        <Upload
          accept=".xlsx,.xls"
          showUploadList={false}
          beforeUpload={(file) => {
            handleImport(file);
            return false; // prevent auto upload
          }}
        >
          <Button icon={<FileExcelOutlined />} disabled={!selectedClass}>
            Import từ Excel
          </Button>
        </Upload>

        <Tag color="blue">{students.length} sinh viên</Tag>
      </Space>

      {/* Import Result */}
      {importResult && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            background: "#f6ffed",
            borderRadius: 8,
            border: "1px solid #b7eb8f",
          }}
        >
          <Descriptions size="small" column={4}>
            <Descriptions.Item label="Tổng hàng">
              {importResult.total_rows}
            </Descriptions.Item>
            <Descriptions.Item label="Thêm mới">
              <Tag color="green">{importResult.inserted}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Cập nhật">
              <Tag color="blue">{importResult.updated}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Lỗi">
              <Tag color={importResult.errors.length > 0 ? "red" : "default"}>
                {importResult.errors.length}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
          {importResult.errors.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
              {importResult.errors.slice(0, 5).map((err, i) => (
                <li key={i}>
                  <Text type="danger">{err}</Text>
                </li>
              ))}
            </ul>
          )}
          <Button size="small" type="link" onClick={() => setImportResult(null)}>
            Đóng
          </Button>
        </div>
      )}

      <Table<Student>
        columns={columns}
        dataSource={students}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 50 }}
        style={{ borderRadius: 8 }}
        locale={{ emptyText: "Chọn lớp học để xem danh sách sinh viên" }}
      />

      {/* Face Enrollment Modal */}
      <Modal
        title="Đăng ký khuôn mặt"
        open={!!enrollModal}
        onOk={handleEnrollFace}
        onCancel={() => {
          setEnrollModal(null);
          setEnrollFiles([]);
        }}
        okText="Đăng ký"
        cancelText="Hủy"
        okButtonProps={{ disabled: enrollFiles.length === 0 }}
      >
        <Text>Upload 3–5 ảnh chụp từ các góc khác nhau:</Text>
        <Upload.Dragger
          multiple
          accept="image/*"
          fileList={enrollFiles}
          onChange={({ fileList }) => setEnrollFiles(fileList)}
          beforeUpload={() => false}
          style={{ marginTop: 12 }}
        >
          <p className="ant-upload-drag-icon">
            <CameraOutlined style={{ fontSize: 48, color: "#1677ff" }} />
          </p>
          <p>Kéo thả hoặc click để chọn ảnh</p>
          <p className="ant-upload-hint">
            Hỗ trợ: JPG, PNG. Tốt nhất: 3-5 ảnh với khuôn mặt rõ ràng.
          </p>
        </Upload.Dragger>
      </Modal>
    </div>
  );
};

export default Students;
