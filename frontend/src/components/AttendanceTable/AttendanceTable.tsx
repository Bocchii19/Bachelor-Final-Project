/**
 * AttendanceTable — Pivot table component for attendance sheet.
 * Rows = students, Columns = session dates, Cells = status icons.
 */

import React from "react";
import { Table, Tag, Progress, Tooltip, Badge } from "antd";
import {
  CheckCircleFilled,
  QuestionCircleFilled,
  MinusCircleOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type {
  AttendanceSheetData,
  StudentRow,
  SessionColumn,
  AttendanceCell,
} from "../../api/attendance";

interface Props {
  data: AttendanceSheetData;
  loading?: boolean;
  onUnknownClick?: (sessionId: string) => void;
}

const statusConfig: Record<
  string,
  { icon: React.ReactNode; color: string; label: string }
> = {
  present: {
    icon: <CheckCircleFilled style={{ color: "#52c41a", fontSize: 18 }} />,
    color: "#f6ffed",
    label: "Có mặt",
  },
  absent: {
    icon: <MinusCircleOutlined style={{ color: "#d9d9d9", fontSize: 18 }} />,
    color: "#fff",
    label: "Vắng",
  },
  unknown: {
    icon: <QuestionCircleFilled style={{ color: "#faad14", fontSize: 18 }} />,
    color: "#fffbe6",
    label: "Chưa xác minh",
  },
};

const AttendanceTable: React.FC<Props> = ({ data, loading, onUnknownClick }) => {
  // Build columns dynamically from sessions
  const sessionColumns: ColumnsType<StudentRow> = data.columns.map(
    (col: SessionColumn) => {
      const dateStr = new Date(col.session_date).toLocaleDateString("vi-VN", {
        day: "2-digit",
        month: "2-digit",
      });

      return {
        title: (
          <Tooltip
            title={`${col.session_date} — ${col.present_count}/${col.total_students} có mặt`}
          >
            <div style={{ textAlign: "center", lineHeight: 1.2 }}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{dateStr}</div>
              {col.unknown_count > 0 && (
                <Badge count={col.unknown_count} size="small" color="orange" />
              )}
            </div>
          </Tooltip>
        ),
        dataIndex: ["attendance", col.session_date],
        key: col.session_id,
        width: 70,
        align: "center" as const,
        render: (_: unknown, record: StudentRow) => {
          const cell: AttendanceCell | undefined =
            record.attendance[col.session_date];
          const status = cell?.status || "absent";
          const config = statusConfig[status] || statusConfig.absent;

          return (
            <Tooltip
              title={`${config.label}${
                cell?.confidence ? ` (${(cell.confidence * 100).toFixed(0)}%)` : ""
              }`}
            >
              <div
                style={{
                  cursor: status === "unknown" ? "pointer" : "default",
                  padding: 4,
                  borderRadius: 4,
                  backgroundColor: config.color,
                  transition: "all 0.2s",
                }}
                onClick={() => {
                  if (status === "unknown" && onUnknownClick) {
                    onUnknownClick(col.session_id);
                  }
                }}
              >
                {config.icon}
              </div>
            </Tooltip>
          );
        },
      };
    }
  );

  const columns: ColumnsType<StudentRow> = [
    {
      title: "MSSV",
      dataIndex: "student_code",
      key: "student_code",
      width: 100,
      fixed: "left",
      sorter: (a, b) => a.student_code.localeCompare(b.student_code),
    },
    {
      title: "Họ và tên",
      dataIndex: "full_name",
      key: "full_name",
      width: 180,
      fixed: "left",
      sorter: (a, b) => a.full_name.localeCompare(b.full_name),
    },
    ...sessionColumns,
    {
      title: "Có mặt",
      dataIndex: "present_count",
      key: "present_count",
      width: 80,
      align: "center" as const,
      sorter: (a, b) => a.present_count - b.present_count,
      render: (count: number, record: StudentRow) => (
        <Tag color={count === record.total_sessions ? "green" : "default"}>
          {count}/{record.total_sessions}
        </Tag>
      ),
    },
    {
      title: "Tỉ lệ",
      dataIndex: "attendance_rate",
      key: "attendance_rate",
      width: 120,
      align: "center" as const,
      sorter: (a, b) => a.attendance_rate - b.attendance_rate,
      render: (rate: number) => (
        <Progress
          percent={rate}
          size="small"
          status={rate >= 80 ? "success" : rate >= 50 ? "normal" : "exception"}
          format={(p) => `${p?.toFixed(0)}%`}
        />
      ),
    },
  ];

  // Summary row
  const summaryRow = () => (
    <Table.Summary fixed>
      <Table.Summary.Row>
        <Table.Summary.Cell index={0} colSpan={2}>
          <strong>Tổng có mặt</strong>
        </Table.Summary.Cell>
        {data.columns.map((col, idx) => (
          <Table.Summary.Cell key={col.session_id} index={idx + 2} align="center">
            <strong>
              {col.present_count}/{col.total_students}
            </strong>
          </Table.Summary.Cell>
        ))}
        <Table.Summary.Cell index={data.columns.length + 2} colSpan={2} />
      </Table.Summary.Row>
    </Table.Summary>
  );

  return (
    <Table<StudentRow>
      columns={columns}
      dataSource={data.rows}
      rowKey="student_id"
      loading={loading}
      pagination={false}
      scroll={{ x: "max-content" }}
      bordered
      size="small"
      summary={summaryRow}
      style={{ fontSize: 13 }}
    />
  );
};

export default AttendanceTable;
