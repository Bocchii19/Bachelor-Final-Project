/**
 * AttendanceSheet Page — Excel-like pivot attendance table.
 */

import React, { useEffect, useState } from "react";
import {
  Typography,
  Select,
  DatePicker,
  Button,
  Space,
  Spin,
  message,
  Empty,
} from "antd";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import AttendanceTable from "../components/AttendanceTable/AttendanceTable";
import {
  fetchAttendanceSheet,
  exportAttendanceExcel,
  type AttendanceSheetData,
} from "../api/attendance";
import apiClient from "../api/client";

const { Title } = Typography;
const { RangePicker } = DatePicker;

interface ClassOption {
  id: string;
  name: string;
  subject: string;
}

const AttendanceSheet: React.FC = () => {
  const [classes, setClasses] = useState<ClassOption[]>([]);
  const [selectedClass, setSelectedClass] = useState<string>("");
  const [dateRange, setDateRange] = useState<
    [dayjs.Dayjs | null, dayjs.Dayjs | null] | null
  >(null);
  const [sheetData, setSheetData] = useState<AttendanceSheetData | null>(null);
  const [loading, setLoading] = useState(false);

  // Fetch classes on mount
  useEffect(() => {
    apiClient
      .get("/classes")
      .then((res) => setClasses(res.data))
      .catch(console.error);
  }, []);

  const loadSheet = async () => {
    if (!selectedClass) {
      message.warning("Vui lòng chọn lớp học");
      return;
    }
    setLoading(true);
    try {
      const data = await fetchAttendanceSheet(
        selectedClass,
        dateRange?.[0]?.format("YYYY-MM-DD"),
        dateRange?.[1]?.format("YYYY-MM-DD")
      );
      setSheetData(data);
    } catch {
      message.error("Không thể tải dữ liệu điểm danh");
    } finally {
      setLoading(false);
    }
  };

  // Auto-load when class selected
  useEffect(() => {
    if (selectedClass) loadSheet();
  }, [selectedClass]);

  const handleExport = async () => {
    if (!selectedClass) return;
    try {
      const blob = await exportAttendanceExcel(
        selectedClass,
        dateRange?.[0]?.format("YYYY-MM-DD"),
        dateRange?.[1]?.format("YYYY-MM-DD")
      );
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `attendance_${sheetData?.class_name || "export"}.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
      message.success("Xuất file Excel thành công!");
    } catch {
      message.error("Xuất file thất bại");
    }
  };

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        📋 Bảng điểm danh
      </Title>

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

        <RangePicker
          onChange={(dates) =>
            setDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null])
          }
          placeholder={["Từ ngày", "Đến ngày"]}
        />

        <Button icon={<ReloadOutlined />} onClick={loadSheet} loading={loading}>
          Tải lại
        </Button>

        <Button
          type="primary"
          icon={<DownloadOutlined />}
          onClick={handleExport}
          disabled={!sheetData}
        >
          Xuất Excel
        </Button>
      </Space>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : sheetData ? (
        <AttendanceTable data={sheetData} />
      ) : (
        <Empty description="Chọn lớp học để xem bảng điểm danh" />
      )}
    </div>
  );
};

export default AttendanceSheet;
