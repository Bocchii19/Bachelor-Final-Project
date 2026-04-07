/**
 * Camera View Page — VMS Multi-Camera Dashboard.
 *
 * Grid layout (1×1, 2×2, 3×3) with per-camera WebSocket streams,
 * expandable detail panel with PTZ controls, enrollment, and attendance.
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Card,
  Row,
  Col,
  Button,
  Typography,
  Tag,
  Space,
  message,
  Tooltip,
  Spin,
  Table,
  Upload,
  Badge,
  Popconfirm,
  Empty,
  Segmented,
} from "antd";
import {
  VideoCameraOutlined,
  AimOutlined,
  PauseCircleOutlined,
  UpOutlined,
  DownOutlined,
  LeftOutlined,
  RightOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  UserOutlined,
  UploadOutlined,
  ScanOutlined,
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  AppstoreOutlined,
  CloseOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";
import { Progress, Select } from "antd";
import api from "../api/client";
import AddCameraModal from "../components/AddCameraModal";

const { Title, Text } = Typography;

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface CameraInfo {
  id: string;
  name: string;
  rtsp_url: string;
  type: string;
  onvif_host?: string | null;
  onvif_port?: number | null;
  is_active: boolean;
}

interface PresetInfo {
  token: string;
  name: string;
}

interface ScanStatus {
  state: "idle" | "scanning" | "done";
  current_zone: string;
  current_sweep: number;
  total_sweeps: number;
  zones_total: number;
  zones_done: number;
  frames_processed: number;
  recognized_count: number;
  coverage_pct: number;
  recognized: Array<{
    student_code: string;
    full_name: string;
    score: number;
    time: string;
    zone: string;
  }>;
  error: string | null;
}

interface AttendanceEntry {
  student_code: string;
  full_name: string;
  score: number;
  time: string;
}

/* ------------------------------------------------------------------ */
/* Camera Tile — renders a single camera stream via WebSocket          */
/* ------------------------------------------------------------------ */

const WS_BASE = `ws://${window.location.hostname}:8000/ptz/cameras`;

const CameraTile: React.FC<{
  camera: CameraInfo;
  onExpand: () => void;
  onEdit: () => void;
  onDelete: () => void;
  isExpanded: boolean;
  gridCols: number;
}> = ({ camera, onExpand, onEdit, onDelete, isExpanded, gridCols }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    const ws = new WebSocket(`${WS_BASE}/${camera.id}/ws`);
    ws.binaryType = "blob"; // Receive binary JPEG frames
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // Handle both binary (new) and text/base64 (legacy) frames
      const blob =
        event.data instanceof Blob
          ? event.data
          : new Blob(
              [
                Uint8Array.from(atob(event.data), (c) => c.charCodeAt(0)),
              ],
              { type: "image/jpeg" }
            );

      createImageBitmap(blob).then((bmp) => {
        if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
          canvas.width = bmp.width;
          canvas.height = bmp.height;
        }
        ctx.drawImage(bmp, 0, 0);
        bmp.close();
      });
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect after 3s
      reconnectRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => setConnected(false);
  }, [camera.id]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [connect]);

  // Tile height adapts to grid size
  const tileMinHeight = gridCols === 1 ? 480 : gridCols === 2 ? 300 : 220;

  return (
    <div
      style={{
        position: "relative",
        background: "#111",
        borderRadius: 10,
        overflow: "hidden",
        border: isExpanded
          ? "2px solid #4f46e5"
          : "1px solid rgba(255,255,255,0.08)",
        cursor: "pointer",
        minHeight: tileMinHeight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "border-color 0.2s",
      }}
      onClick={onExpand}
    >
      {/* Overlay: name + status */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          padding: "8px 12px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.7) 0%, transparent 100%)",
          zIndex: 2,
        }}
      >
        <Space size={6}>
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: connected ? "#52c41a" : "#ff4d4f",
              boxShadow: connected
                ? "0 0 6px #52c41a"
                : "0 0 6px #ff4d4f",
            }}
          />
          <Text
            strong
            style={{
              color: "#fff",
              fontSize: gridCols >= 3 ? 11 : 13,
              textShadow: "0 1px 4px rgba(0,0,0,0.5)",
            }}
          >
            {camera.name}
          </Text>
          {camera.type === "ptz" && (
            <Tag
              color="blue"
              style={{
                fontSize: 10,
                lineHeight: "16px",
                padding: "0 4px",
                margin: 0,
              }}
            >
              PTZ
            </Tag>
          )}
        </Space>

        <Space size={4} onClick={(e) => e.stopPropagation()}>
          <Tooltip title="Sửa">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              style={{ color: "#ffffffcc" }}
              onClick={onEdit}
            />
          </Tooltip>
          <Popconfirm title="Xóa camera này?" onConfirm={onDelete}>
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              style={{ color: "#ff4d4fcc" }}
            />
          </Popconfirm>
        </Space>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        width={1920}
        height={1080}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          display: "block",
        }}
      />

      {/* No signal overlay */}
      {!connected && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.6)",
            zIndex: 1,
          }}
        >
          <VideoCameraOutlined
            style={{ fontSize: 36, color: "#ffffff40", marginBottom: 8 }}
          />
          <Text style={{ color: "#ffffff60", fontSize: 12 }}>
            Đang kết nối...
          </Text>
        </div>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Empty Add-Camera Slot                                               */
/* ------------------------------------------------------------------ */

const AddCameraSlot: React.FC<{
  onClick: () => void;
  gridCols: number;
}> = ({ onClick, gridCols }) => {
  const tileMinHeight = gridCols === 1 ? 480 : gridCols === 2 ? 300 : 220;
  return (
    <div
      style={{
        minHeight: tileMinHeight,
        borderRadius: 10,
        border: "2px dashed rgba(255,255,255,0.15)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#1a1a1a",
        cursor: "pointer",
        transition: "border-color 0.2s, background 0.2s",
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor =
          "rgba(79,70,229,0.5)";
        (e.currentTarget as HTMLDivElement).style.background = "#1e1e2f";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor =
          "rgba(255,255,255,0.15)";
        (e.currentTarget as HTMLDivElement).style.background = "#1a1a1a";
      }}
    >
      <PlusOutlined
        style={{ fontSize: 28, color: "#ffffff40", marginBottom: 8 }}
      />
      <Text style={{ color: "#ffffff50", fontSize: 13 }}>Thêm Camera</Text>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Main Dashboard                                                      */
/* ------------------------------------------------------------------ */

const PTZ_SPEED = 0.5;
const ENROLL_FOLDER = "/media/edabk/edabk1_500gb/Bocchi/Thesis/408";

const CameraView: React.FC = () => {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [gridCols, setGridCols] = useState(2);
  const [loading, setLoading] = useState(true);

  // Expanded camera detail
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Add/Edit modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editCam, setEditCam] = useState<CameraInfo | null>(null);

  // PTZ controls (for expanded camera)
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [movingPreset, setMovingPreset] = useState<string | null>(null);

  // Enrollment
  const [enrolling, setEnrolling] = useState(false);
  const [enrollStats, setEnrollStats] =
    useState<{ total_students: number; total_embeddings: number } | null>(null);

  // Attendance
  const [attendanceActive, setAttendanceActive] = useState(false);
  const [attendanceResults, setAttendanceResults] = useState<
    AttendanceEntry[]
  >([]);
  const attendancePollRef = useRef<ReturnType<typeof setInterval> | null>(
    null
  );

  // Auto-scan
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [allPresets, setAllPresets] = useState<PresetInfo[]>([]);
  const [scanPresetTokens, setScanPresetTokens] = useState<string[]>([]);

  /* -- Data fetching -- */

  const fetchCameras = async () => {
    try {
      const res = await api.get("/ptz/cameras");
      setCameras(res.data);
    } catch {
      setCameras([]);
    }
  };

  const fetchEnrollStats = async () => {
    try {
      const res = await api.get("/ptz/enrollment-stats");
      setEnrollStats(res.data);
    } catch {
      /* ignore */
    }
  };

  const fetchPresets = async () => {
    try {
      const res = await api.get("/ptz/presets");
      setPresets(res.data);
    } catch {
      setPresets([]);
    }
  };

  const fetchAllPresets = async () => {
    try {
      const res = await api.get("/ptz/all-presets");
      setAllPresets(res.data);
    } catch {
      setAllPresets([]);
    }
  };

  // Initial load
  useEffect(() => {
    Promise.all([fetchCameras(), fetchEnrollStats(), fetchPresets(), fetchAllPresets()]).finally(
      () => setLoading(false)
    );
  }, []);

  // Restore attendance state on mount
  useEffect(() => {
    const restore = async () => {
      try {
        const res = await api.get("/ptz/attendance-results");
        if (res.data.active) {
          setAttendanceActive(true);
          setAttendanceResults(res.data.recognized || []);
          attendancePollRef.current = setInterval(async () => {
            try {
              const r = await api.get("/ptz/attendance-results");
              setAttendanceResults(r.data.recognized || []);
              if (!r.data.active) {
                setAttendanceActive(false);
                if (attendancePollRef.current)
                  clearInterval(attendancePollRef.current);
              }
            } catch {
              /* ignore */
            }
          }, 2000);
        }
      } catch {
        /* ignore */
      }
    };
    restore();
    return () => {
      if (attendancePollRef.current)
        clearInterval(attendancePollRef.current);
    };
  }, []);

  /* -- Camera CRUD -- */

  const handleDeleteCamera = async (id: string) => {
    try {
      await api.delete(`/ptz/cameras/${id}`);
      message.success("Đã xóa camera");
      if (expandedId === id) setExpandedId(null);
      fetchCameras();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Lỗi xóa camera");
    }
  };

  /* -- PTZ Controls -- */

  const handlePTZStart = async (pan: number, tilt: number, zoom: number) => {
    try {
      await api.post("/ptz/continuous-move", { pan, tilt, zoom });
    } catch {
      message.error("Lỗi điều khiển PTZ");
    }
  };

  const handlePTZStop = async () => {
    try {
      await api.post("/ptz/stop");
    } catch {
      /* ignore */
    }
  };

  const handleMovePreset = async (token: string) => {
    setMovingPreset(token);
    try {
      await api.post("/ptz/move", { preset_token: token });
      message.success(`Đã di chuyển đến preset`);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Lỗi di chuyển camera");
    } finally {
      setMovingPreset(null);
    }
  };

  /* -- Enrollment -- */

  const handleEnrollFolder = async () => {
    setEnrolling(true);
    try {
      const res = await api.post("/ptz/enroll-folder", {
        folder_path: ENROLL_FOLDER,
        class_name: "408",
      });
      fetchEnrollStats();
      message.success(
        `Đã đăng ký: ${res.data.students_created} SV mới, ${res.data.embeddings_created} embeddings`
      );
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Lỗi enrollment");
    } finally {
      setEnrolling(false);
    }
  };

  const handleUploadEnroll = async (file: File) => {
    const formData = new FormData();
    formData.append("files", file);
    formData.append("class_name", "408");
    try {
      const res = await api.post("/ptz/enroll-upload", formData);
      message.success(
        `Upload: ${res.data.students_created} SV, ${res.data.embeddings_created} embeddings`
      );
    } catch {
      message.error("Lỗi upload enrollment");
    }
    return false;
  };

  /* -- Attendance -- */

  const handleStartAttendance = async () => {
    try {
      await api.post("/ptz/start-attendance");
      setAttendanceActive(true);
      setAttendanceResults([]);
      message.success("Bắt đầu điểm danh");
      attendancePollRef.current = setInterval(async () => {
        try {
          const res = await api.get("/ptz/attendance-results");
          setAttendanceResults(res.data.recognized || []);
          if (!res.data.active) {
            setAttendanceActive(false);
            if (attendancePollRef.current)
              clearInterval(attendancePollRef.current);
          }
        } catch {
          /* ignore */
        }
      }, 2000);
    } catch {
      message.error("Lỗi bắt đầu điểm danh");
    }
  };

  const handleStopAttendance = async () => {
    try {
      await api.post("/ptz/stop-attendance");
      setAttendanceActive(false);
      if (attendancePollRef.current)
        clearInterval(attendancePollRef.current);
      message.info("Đã dừng điểm danh");
    } catch {
      /* ignore */
    }
  };

  /* -- Auto-Scan -- */

  const handleStartAutoScan = async () => {
    try {
      await api.post("/ptz/start-auto-scan", {
        sweeps: 2,
        dwell_seconds: 4.0,
        frames_per_zone: 6,
        preset_tokens: scanPresetTokens.length > 0 ? scanPresetTokens : undefined,
      });
      message.success("Bắt đầu quét tự động");
      // Poll scan status
      scanPollRef.current = setInterval(async () => {
        try {
          const res = await api.get("/ptz/auto-scan-status");
          setScanStatus(res.data);
          if (res.data.state === "done" || res.data.state === "idle") {
            if (scanPollRef.current) clearInterval(scanPollRef.current);
            if (res.data.state === "done") {
              message.success(
                `Quét xong: ${res.data.recognized_count} SV (${res.data.coverage_pct}%)`
              );
            }
          }
        } catch {
          /* ignore */
        }
      }, 2000);
    } catch {
      message.error("Lỗi bắt đầu quét tự động");
    }
  };

  const handleStopAutoScan = async () => {
    try {
      await api.post("/ptz/stop-auto-scan");
      if (scanPollRef.current) clearInterval(scanPollRef.current);
      message.info("Đã dừng quét tự động");
    } catch {
      /* ignore */
    }
  };

  // Cleanup scan poll on unmount
  useEffect(() => {
    return () => {
      if (scanPollRef.current) clearInterval(scanPollRef.current);
    };
  }, []);

  // Restore scan state on mount
  useEffect(() => {
    const restoreScan = async () => {
      try {
        const res = await api.get("/ptz/auto-scan-status");
        if (res.data.state === "scanning") {
          setScanStatus(res.data);
          scanPollRef.current = setInterval(async () => {
            try {
              const r = await api.get("/ptz/auto-scan-status");
              setScanStatus(r.data);
              if (r.data.state !== "scanning") {
                if (scanPollRef.current) clearInterval(scanPollRef.current);
              }
            } catch { /* ignore */ }
          }, 2000);
        }
      } catch { /* ignore */ }
    };
    restoreScan();
  }, []);

  /* -- Render -- */

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  const expandedCamera = cameras.find((c) => c.id === expandedId) || null;

  // D-Pad button
  const dpadBtn = (
    icon: React.ReactNode,
    pan: number,
    tilt: number,
    zoom: number
  ) => (
    <Button
      size="large"
      icon={icon}
      style={{ width: 48, height: 48, fontSize: 18 }}
      onMouseDown={() => handlePTZStart(pan, tilt, zoom)}
      onMouseUp={handlePTZStop}
      onMouseLeave={handlePTZStop}
      onTouchStart={() => handlePTZStart(pan, tilt, zoom)}
      onTouchEnd={handlePTZStop}
    />
  );

  // Build grid items: cameras + empty slots
  const totalSlots = gridCols * gridCols;
  const gridItems: (CameraInfo | "add")[] = [
    ...cameras,
    ...(cameras.length < totalSlots ? ["add" as const] : []),
  ];

  return (
    <div>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <Title level={3} style={{ margin: 0 }}>
          <AppstoreOutlined style={{ marginRight: 8 }} />
          Camera Dashboard
        </Title>

        <Space size={12}>
          {attendanceActive && (
            <Tag icon={<ScanOutlined />} color="processing">
              Đang điểm danh ({attendanceResults.length} SV)
            </Tag>
          )}
          <Segmented
            value={`${gridCols}×${gridCols}`}
            options={["1×1", "2×2", "3×3"]}
            onChange={(val) => setGridCols(parseInt(val as string))}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditCam(null);
              setModalOpen(true);
            }}
          >
            Thêm Camera
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        {/* Grid */}
        <Col xs={24} lg={expandedCamera ? 16 : 24}>
          {cameras.length === 0 && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Chưa có camera nào"
              style={{
                padding: 80,
                background: "#fafafa",
                borderRadius: 12,
              }}
            >
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  setEditCam(null);
                  setModalOpen(true);
                }}
              >
                Thêm Camera đầu tiên
              </Button>
            </Empty>
          )}

          {cameras.length > 0 && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
                gap: 12,
              }}
            >
              {gridItems.slice(0, totalSlots).map((item) =>
                item === "add" ? (
                  <AddCameraSlot
                    key="add-slot"
                    gridCols={gridCols}
                    onClick={() => {
                      setEditCam(null);
                      setModalOpen(true);
                    }}
                  />
                ) : (
                  <CameraTile
                    key={item.id}
                    camera={item}
                    gridCols={gridCols}
                    isExpanded={expandedId === item.id}
                    onExpand={() =>
                      setExpandedId(
                        expandedId === item.id ? null : item.id
                      )
                    }
                    onEdit={() => {
                      setEditCam(item);
                      setModalOpen(true);
                    }}
                    onDelete={() => handleDeleteCamera(item.id)}
                  />
                )
              )}
            </div>
          )}
        </Col>

        {/* Detail Panel — appears when a tile is expanded */}
        {expandedCamera && (
          <Col xs={24} lg={8}>
            <Card
              title={
                <Space>
                  <VideoCameraOutlined />
                  {expandedCamera.name}
                  <Tag color={expandedCamera.type === "ptz" ? "blue" : "default"}>
                    {expandedCamera.type.toUpperCase()}
                  </Tag>
                </Space>
              }
              extra={
                <Button
                  type="text"
                  icon={<CloseOutlined />}
                  onClick={() => setExpandedId(null)}
                />
              }
              style={{ borderRadius: 12, marginBottom: 16 }}
              size="small"
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                RTSP: {expandedCamera.rtsp_url}
              </Text>
            </Card>

            {/* PTZ Controls (only for PTZ cameras) */}
            {expandedCamera.type === "ptz" && (
              <Card
                title="Điều khiển PTZ"
                style={{ borderRadius: 12, marginBottom: 16 }}
                size="small"
              >
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 4,
                    marginBottom: 16,
                  }}
                >
                  <div>
                    {dpadBtn(<UpOutlined />, 0, PTZ_SPEED, 0)}
                  </div>
                  <div style={{ display: "flex", gap: 4 }}>
                    {dpadBtn(<LeftOutlined />, -PTZ_SPEED, 0, 0)}
                    <Button
                      size="large"
                      style={{
                        width: 48,
                        height: 48,
                        fontSize: 14,
                        fontWeight: "bold",
                      }}
                      onClick={handlePTZStop}
                    >
                      ■
                    </Button>
                    {dpadBtn(<RightOutlined />, PTZ_SPEED, 0, 0)}
                  </div>
                  <div>
                    {dpadBtn(<DownOutlined />, 0, -PTZ_SPEED, 0)}
                  </div>
                </div>

                {/* Zoom */}
                <div style={{ display: "flex", gap: 8 }}>
                  <Button
                    icon={<ZoomInOutlined />}
                    block
                    onMouseDown={() =>
                      handlePTZStart(0, 0, PTZ_SPEED)
                    }
                    onMouseUp={handlePTZStop}
                    onMouseLeave={handlePTZStop}
                  >
                    Zoom +
                  </Button>
                  <Button
                    icon={<ZoomOutOutlined />}
                    block
                    onMouseDown={() =>
                      handlePTZStart(0, 0, -PTZ_SPEED)
                    }
                    onMouseUp={handlePTZStop}
                    onMouseLeave={handlePTZStop}
                  >
                    Zoom −
                  </Button>
                </div>

                {/* Focus */}
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <Button
                    block
                    onMouseDown={() => {
                      api.post("/ptz/focus-in").catch(() => {});
                    }}
                    onMouseUp={() => {
                      api.post("/ptz/focus-stop").catch(() => {});
                    }}
                    onMouseLeave={() => {
                      api.post("/ptz/focus-stop").catch(() => {});
                    }}
                  >
                    🔍 Focus +
                  </Button>
                  <Button
                    block
                    onMouseDown={() => {
                      api.post("/ptz/focus-out").catch(() => {});
                    }}
                    onMouseUp={() => {
                      api.post("/ptz/focus-stop").catch(() => {});
                    }}
                    onMouseLeave={() => {
                      api.post("/ptz/focus-stop").catch(() => {});
                    }}
                  >
                    🔍 Focus −
                  </Button>
                  <Button
                    block
                    onClick={() => {
                      api
                        .post("/ptz/focus-auto")
                        .then(() => message.success("Auto Focus"))
                        .catch(() => message.error("Focus error"));
                    }}
                    style={{ flex: "0 0 auto", minWidth: 70 }}
                  >
                    AF
                  </Button>
                </div>

                {/* Presets */}
                {presets.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <Text
                      type="secondary"
                      style={{ fontSize: 12, marginBottom: 6, display: "block" }}
                    >
                      Presets
                    </Text>
                    <Space wrap>
                      {presets.map((p) => (
                        <Button
                          key={p.token}
                          icon={<AimOutlined />}
                          size="small"
                          loading={movingPreset === p.token}
                          onClick={() => handleMovePreset(p.token)}
                        >
                          {p.name}
                        </Button>
                      ))}
                    </Space>
                  </div>
                )}
              </Card>
            )}

            {/* Enrollment */}
            <Card
              title="Đăng ký khuôn mặt"
              style={{ borderRadius: 12, marginBottom: 16 }}
              size="small"
            >
              <Space direction="vertical" style={{ width: "100%" }}>
                <Button
                  type="primary"
                  icon={<UserOutlined />}
                  block
                  loading={enrolling}
                  onClick={handleEnrollFolder}
                >
                  Đăng ký từ thư mục 408
                </Button>
                <Upload
                  accept=".jpg,.jpeg,.png,.bmp,.webp,.zip"
                  multiple
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUploadEnroll(file);
                    return false;
                  }}
                >
                  <Button icon={<UploadOutlined />} block>
                    Upload ảnh / ZIP
                  </Button>
                </Upload>
                {enrollStats && (
                  <div style={{ fontSize: 12, color: "#888" }}>
                    📊 {enrollStats.total_students} sinh viên,{" "}
                    {enrollStats.total_embeddings} embeddings trong DB
                  </div>
                )}
              </Space>
            </Card>

            {/* Attendance */}
            <Card
              title={
                <Space>
                  <ScanOutlined />
                  Điểm danh
                  {attendanceActive && (
                    <Badge status="processing" text="Đang chạy" />
                  )}
                </Space>
              }
              style={{ borderRadius: 12, marginBottom: 16 }}
              size="small"
            >
              <Space direction="vertical" style={{ width: "100%" }}>
                {!attendanceActive ? (
                  <Button
                    type="primary"
                    danger
                    icon={<ScanOutlined />}
                    block
                    onClick={handleStartAttendance}
                    disabled={scanStatus?.state === "scanning"}
                  >
                    Bắt đầu điểm danh
                  </Button>
                ) : (
                  <Button
                    danger
                    icon={<PauseCircleOutlined />}
                    block
                    onClick={handleStopAttendance}
                  >
                    Dừng điểm danh
                  </Button>
                )}
                {attendanceResults.length > 0 && (
                  <Table
                    dataSource={attendanceResults}
                    columns={[
                      {
                        title: "Tên",
                        dataIndex: "full_name",
                        key: "name",
                      },
                      {
                        title: "Mã SV",
                        dataIndex: "student_code",
                        key: "code",
                        width: 100,
                      },
                      {
                        title: "Score",
                        dataIndex: "score",
                        key: "score",
                        width: 70,
                      },
                      {
                        title: "Giờ",
                        dataIndex: "time",
                        key: "time",
                        width: 80,
                      },
                    ]}
                    rowKey="student_code"
                    size="small"
                    pagination={false}
                    scroll={{ y: 200 }}
                  />
                )}
              </Space>
            </Card>

            {/* Auto-Scan */}
            {expandedCamera?.type === "ptz" && (
              <Card
                title={
                  <Space>
                    <RadarChartOutlined />
                    Quét tự động
                    {scanStatus?.state === "scanning" && (
                      <Badge status="processing" text="Đang quét" />
                    )}
                    {scanStatus?.state === "done" && (
                      <Badge status="success" text="Hoàn thành" />
                    )}
                  </Space>
                }
                style={{ borderRadius: 12, marginBottom: 16 }}
                size="small"
              >
                <Space direction="vertical" style={{ width: "100%" }} size={12}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Camera tự di chuyển qua các preset, chụp và nhận diện khuôn
                    mặt tại mỗi vị trí.
                  </Text>

                  {/* Preset selector */}
                  {allPresets.length > 0 && scanStatus?.state !== "scanning" && (
                    <div>
                      <Text
                        type="secondary"
                        style={{ fontSize: 11, marginBottom: 4, display: "block" }}
                      >
                        Chọn preset để quét (bỏ trống = quét tất cả):
                      </Text>
                      <Select
                        mode="multiple"
                        placeholder="Tất cả preset"
                        style={{ width: "100%" }}
                        value={scanPresetTokens}
                        onChange={(vals: string[]) => setScanPresetTokens(vals)}
                        options={allPresets.map((p) => ({
                          value: p.token,
                          label: p.name,
                        }))}
                        maxTagCount={3}
                        allowClear
                        size="small"
                      />
                    </div>
                  )}

                  {scanStatus?.state !== "scanning" ? (
                    <Button
                      type="primary"
                      icon={<RadarChartOutlined />}
                      block
                      onClick={handleStartAutoScan}
                      disabled={attendanceActive}
                      style={{
                        background:
                          "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                        border: "none",
                      }}
                    >
                      🔄 Bắt đầu quét tự động
                    </Button>
                  ) : (
                    <Button
                      danger
                      icon={<PauseCircleOutlined />}
                      block
                      onClick={handleStopAutoScan}
                    >
                      Dừng quét
                    </Button>
                  )}

                  {/* Scan Progress */}
                  {scanStatus && scanStatus.state !== "idle" && (
                    <div
                      style={{
                        background: "rgba(79, 70, 229, 0.05)",
                        borderRadius: 8,
                        padding: 12,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          marginBottom: 8,
                        }}
                      >
                        <Text style={{ fontSize: 12 }}>
                          📍 {scanStatus.current_zone || "—"}
                        </Text>
                        <Text style={{ fontSize: 12 }}>
                          Sweep {scanStatus.current_sweep}/{scanStatus.total_sweeps}
                        </Text>
                      </div>

                      <Progress
                        percent={
                          scanStatus.zones_total > 0
                            ? Math.round(
                                ((scanStatus.current_sweep - 1) *
                                  scanStatus.zones_total +
                                  scanStatus.zones_done) *
                                  100 /
                                  (scanStatus.total_sweeps *
                                    scanStatus.zones_total)
                              )
                            : 0
                        }
                        size="small"
                        strokeColor={{
                          "0%": "#667eea",
                          "100%": "#764ba2",
                        }}
                      />

                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          marginTop: 8,
                          fontSize: 12,
                        }}
                      >
                        <Text type="secondary">
                          🎯 {scanStatus.recognized_count} SV nhận diện
                        </Text>
                        <Text
                          style={{
                            color:
                              scanStatus.coverage_pct >= 90
                                ? "#52c41a"
                                : scanStatus.coverage_pct >= 50
                                ? "#faad14"
                                : "#ff4d4f",
                            fontWeight: 600,
                          }}
                        >
                          {scanStatus.coverage_pct}% coverage
                        </Text>
                      </div>

                      <Text
                        type="secondary"
                        style={{ fontSize: 11, marginTop: 4, display: "block" }}
                      >
                        {scanStatus.frames_processed} frames đã xử lý
                      </Text>
                    </div>
                  )}

                  {/* Scan Results Table */}
                  {scanStatus &&
                    scanStatus.recognized &&
                    scanStatus.recognized.length > 0 && (
                      <Table
                        dataSource={scanStatus.recognized}
                        columns={[
                          {
                            title: "Tên",
                            dataIndex: "full_name",
                            key: "name",
                            ellipsis: true,
                          },
                          {
                            title: "Mã SV",
                            dataIndex: "student_code",
                            key: "code",
                            width: 90,
                          },
                          {
                            title: "Vị trí",
                            dataIndex: "zone",
                            key: "zone",
                            width: 80,
                            ellipsis: true,
                          },
                          {
                            title: "Giờ",
                            dataIndex: "time",
                            key: "time",
                            width: 70,
                          },
                        ]}
                        rowKey="student_code"
                        size="small"
                        pagination={false}
                        scroll={{ y: 200 }}
                      />
                    )}

                  {scanStatus?.error && (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      ❌ {scanStatus.error}
                    </Text>
                  )}
                </Space>
              </Card>
            )}
          </Col>
        )}
      </Row>

      {/* Add/Edit Camera Modal */}
      <AddCameraModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditCam(null);
        }}
        onSuccess={fetchCameras}
        editCamera={editCam}
      />
    </div>
  );
};

export default CameraView;
