/**
 * FaceCard — Unknown face card for admin verification.
 */

import React from "react";
import {
  Card,
  Button,
  Tag,
  Typography,
  Space,
  Tooltip,
  Avatar,
  Popconfirm,
} from "antd";
import {
  UserOutlined,
  CheckOutlined,
  StopOutlined,
  WarningOutlined,
  ClusterOutlined,
} from "@ant-design/icons";
import type { UnknownFace } from "../../api/unknownFaces";

const { Text, Paragraph } = Typography;

interface Props {
  face: UnknownFace;
  onMatch: (faceId: string) => void;
  onStranger: (faceId: string) => void;
  onFalsePositive: (faceId: string) => void;
}

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const statusColors: Record<string, string> = {
  pending: "orange",
  matched: "green",
  stranger: "red",
  false_positive: "default",
};

const FaceCard: React.FC<Props> = ({
  face,
  onMatch,
  onStranger,
  onFalsePositive,
}) => {
  const isPending = face.status === "pending";
  const imageUrl = face.image_path.startsWith("http")
    ? face.image_path
    : `${API_URL}/media/${face.image_path.replace("./media/", "")}`;

  return (
    <Card
      hoverable={isPending}
      style={{
        width: 280,
        borderRadius: 12,
        overflow: "hidden",
        border: isPending ? "2px solid #faad14" : undefined,
        opacity: isPending ? 1 : 0.7,
      }}
      cover={
        <div
          style={{
            height: 200,
            background: "#f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          <img
            alt="Unknown face"
            src={imageUrl}
            style={{
              maxHeight: "100%",
              maxWidth: "100%",
              objectFit: "contain",
            }}
            onError={(e) => {
              (e.target as HTMLImageElement).src = "";
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      }
      actions={
        isPending
          ? [
              <Tooltip title="Xác nhận sinh viên" key="match">
                <Button
                  type="text"
                  icon={<CheckOutlined />}
                  style={{ color: "#52c41a" }}
                  onClick={() => onMatch(face.id)}
                />
              </Tooltip>,
              <Popconfirm
                title="Đánh dấu người lạ?"
                onConfirm={() => onStranger(face.id)}
                key="stranger"
              >
                <Button
                  type="text"
                  icon={<StopOutlined />}
                  style={{ color: "#ff4d4f" }}
                />
              </Popconfirm>,
              <Popconfirm
                title="Đánh dấu nhận diện nhầm?"
                onConfirm={() => onFalsePositive(face.id)}
                key="fp"
              >
                <Button
                  type="text"
                  icon={<WarningOutlined />}
                  style={{ color: "#8c8c8c" }}
                />
              </Popconfirm>,
            ]
          : undefined
      }
    >
      <Card.Meta
        avatar={<Avatar icon={<UserOutlined />} />}
        title={
          <Space>
            <Tag color={statusColors[face.status]}>{face.status}</Tag>
            {face.cluster_id && (
              <Tooltip title={`Cluster: ${face.cluster_size} ảnh`}>
                <Tag icon={<ClusterOutlined />} color="blue">
                  ×{face.cluster_size}
                </Tag>
              </Tooltip>
            )}
          </Space>
        }
        description={
          <Space direction="vertical" size={2}>
            {face.best_match_name && (
              <Text>
                Gợi ý: <strong>{face.best_match_name}</strong> ({face.best_match_code})
              </Text>
            )}
            {face.best_score != null && (
              <Text type="secondary">
                Điểm: {(face.best_score * 100).toFixed(1)}%
              </Text>
            )}
            <Text type="secondary" style={{ fontSize: 11 }}>
              Zone: {face.zone_id || "—"} ·{" "}
              {new Date(face.captured_at).toLocaleTimeString("vi-VN")}
            </Text>
          </Space>
        }
      />
    </Card>
  );
};

export default FaceCard;
