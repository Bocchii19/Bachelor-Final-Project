/**
 * ScanPlanBadge — Displays PTZ scan plan summary.
 */

import React from "react";
import { Card, Descriptions, Tag, Space, Progress, Typography } from "antd";
import {
  VideoCameraOutlined,
  ClockCircleOutlined,
  AimOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import type { ScanPlan } from "../../api/sessions";

const { Text } = Typography;

interface Props {
  plan?: ScanPlan;
  coverage?: {
    coverage_pct: number;
    target_pct: number;
    is_sufficient: boolean;
    recognized_count: number;
    enrolled_count: number;
  };
}

const ScanPlanBadge: React.FC<Props> = ({ plan, coverage }) => {
  if (!plan) {
    return (
      <Card size="small" style={{ borderRadius: 8 }}>
        <Text type="secondary">Chưa có scan plan</Text>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={
        <Space>
          <VideoCameraOutlined />
          <span>Scan Plan</span>
        </Space>
      }
      style={{ borderRadius: 8 }}
    >
      <Descriptions column={2} size="small">
        <Descriptions.Item
          label={
            <Space>
              <AimOutlined /> Zones
            </Space>
          }
        >
          {plan.zones.map((z) => (
            <Tag key={z.id} color="blue">
              {z.id}
            </Tag>
          ))}
        </Descriptions.Item>

        <Descriptions.Item
          label={
            <Space>
              <SyncOutlined /> Sweeps
            </Space>
          }
        >
          <Tag>{plan.sweeps}×</Tag>
        </Descriptions.Item>

        <Descriptions.Item
          label={
            <Space>
              <ClockCircleOutlined /> Dwell
            </Space>
          }
        >
          {plan.dwell_seconds}s
        </Descriptions.Item>

        <Descriptions.Item label="Tổng thời gian">
          <Tag color="purple">{Math.round(plan.total_seconds)}s</Tag>
        </Descriptions.Item>
      </Descriptions>

      {coverage && (
        <div style={{ marginTop: 12 }}>
          <Text strong>
            Coverage: {coverage.recognized_count}/{coverage.enrolled_count}
          </Text>
          <Progress
            percent={coverage.coverage_pct}
            success={{
              percent: coverage.target_pct,
              strokeColor: "transparent",
            }}
            status={coverage.is_sufficient ? "success" : "active"}
            format={(p) => `${p?.toFixed(1)}%`}
            style={{ marginTop: 4 }}
          />
        </div>
      )}
    </Card>
  );
};

export default ScanPlanBadge;
