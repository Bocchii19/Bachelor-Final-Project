"""
Detection utilities: person class IDs, point-in-polygon, bbox helpers,
YOLO label output, bounding box drawing.

Consolidated from duplicated code across 5+ scripts.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def has_any_detection(result) -> bool:
    """Check if a YOLO result has any bounding boxes."""
    if result is None or result.boxes is None:
        return False
    return len(result.boxes) > 0


def person_class_ids(res) -> set[int]:
    """
    Get class IDs that represent a person.
    Defaults to {0} if no matching name found.
    """
    names = getattr(res, "names", None) or {}
    if not isinstance(names, dict):
        return {0}
    out: set[int] = set()
    for k, v in names.items():
        s = str(v).lower().strip()
        if s in ("person", "nguoi", "người", "pedestrian") or "person" in s:
            out.add(int(k))
    return out if out else {0}


def point_in_polygon(x: float, y: float, polygon: np.ndarray | None) -> bool:
    """Check if point (x,y) is inside polygon. Returns True if polygon is None/empty."""
    if polygon is None or polygon.shape[0] < 3:
        return True
    return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0


def box_xyxy_to_yolo_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    iw: int,
    ih: int,
    cls_id: int,
) -> str | None:
    """Convert xyxy bbox to YOLO format line: `class xc yc w h` (normalized 0-1)."""
    if iw <= 0 or ih <= 0:
        return None
    x1 = max(0.0, x1)
    y1 = max(0.0, y1)
    x2 = min(float(iw), x2)
    y2 = min(float(ih), y2)
    bw = x2 - x1
    bh = y2 - y1
    if bw <= 0 or bh <= 0:
        return None
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return (
        f"{cls_id} {cx / iw:.6f} {cy / ih:.6f} {bw / iw:.6f} {bh / ih:.6f}"
    )


def save_person_image_and_yolo(
    frame: np.ndarray,
    res,
    out_person_cam_dir: Path,
    ts: str,
    polygon: np.ndarray | None,
) -> int:
    """
    Save frame as jpg + YOLO label txt for person bboxes inside polygon.
    Returns number of person boxes written.
    """
    if res is None or res.boxes is None or len(res.boxes) == 0:
        return 0
    pids = person_class_ids(res)
    ih, iw = int(frame.shape[0]), int(frame.shape[1])
    lines: list[str] = []
    for box in res.boxes:
        try:
            cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
        except (TypeError, ValueError, IndexError):
            continue
        if cls_id not in pids:
            continue
        try:
            xy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else box.xyxy[0].numpy()
            x1, y1, x2, y2 = float(xy[0]), float(xy[1]), float(xy[2]), float(xy[3])
        except Exception:
            continue
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        if not point_in_polygon(cx, cy, polygon):
            continue
        line = box_xyxy_to_yolo_line(x1, y1, x2, y2, iw, ih, cls_id)
        if line is not None:
            lines.append(line)
    if not lines:
        return 0
    jpg = out_person_cam_dir / f"{ts}.jpg"
    txt = out_person_cam_dir / f"{ts}.txt"
    if not cv2.imwrite(str(jpg), frame):
        return 0
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def draw_model_boxes_bgr(frame_bgr: np.ndarray, res) -> np.ndarray:
    """Draw all bounding boxes from YOLO result onto a copy of the BGR frame."""
    out = frame_bgr.copy()
    if res is None or res.boxes is None or len(res.boxes) == 0:
        return out
    names = getattr(res, "names", None) or {}
    ih, iw = int(out.shape[0]), int(out.shape[1])
    for box in res.boxes:
        try:
            cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
        except (TypeError, ValueError, IndexError):
            cls_id = -1
        try:
            cf = float(box.conf[0].item() if hasattr(box.conf[0], "item") else float(box.conf[0]))
        except (TypeError, ValueError, IndexError):
            cf = 0.0
        try:
            xy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else box.xyxy[0].numpy()
            x1, y1, x2, y2 = int(xy[0]), int(xy[1]), int(xy[2]), int(xy[3])
        except Exception:
            continue
        x1 = max(0, min(x1, iw - 1))
        x2 = max(0, min(x2, iw - 1))
        y1 = max(0, min(y1, ih - 1))
        y2 = max(0, min(y2, ih - 1))
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
        cap = f"{label} {cf:.2f}"
        cv2.putText(
            out, cap, (x1, max(y1 - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
        )
    return out


def largest_person_box_xyxy(res) -> tuple[float, float, float, float] | None:
    """Find the largest person bounding box by area. Returns (x1,y1,x2,y2) or None."""
    if res is None or res.boxes is None or len(res.boxes) == 0:
        return None
    pids = person_class_ids(res)
    best_area = -1.0
    best: tuple[float, float, float, float] | None = None
    for box in res.boxes:
        try:
            cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
        except (TypeError, ValueError, IndexError):
            continue
        if cls_id not in pids:
            continue
        xy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else box.xyxy[0].numpy()
        x1, y1, x2, y2 = float(xy[0]), float(xy[1]), float(xy[2]), float(xy[3])
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if area > best_area:
            best_area = area
            best = (x1, y1, x2, y2)
    return best
