"""
Fence-specific geometry and polygon utilities.

Chứa các hàm liên quan đến fence line, ROI cho bài toán trèo rào.
Các hàm generic nằm trong src.backend.core.utils.polygon.

Functions moved from core/polygon.py:
- foot_below_fence_polyline
- line_two_points_to_stripe_polygon
- load_polygon_yaml_region1_by_ip
- load_polygon_yaml_fence_line_by_ip
- load_configs_yaml_treo_polygon_by_ip
- CameraRoiRefs
- build_cam_roi_refs
- draw_roi_overlay_bgr
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from src.backend.core.utils.polygon import (
    load_yaml,
    extract_ip_from_rtsp,
    parse_pt_list,
)
from src.backend.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Fence line geometry
# ---------------------------------------------------------------------------

def line_two_points_to_stripe_polygon(
    ax: float, ay: float,
    bx: float, by: float,
    half_width: float = 48.0,
) -> np.ndarray | None:
    """Expand a line segment into a quadrilateral strip for mask filling."""
    p0 = np.array([ax, ay], dtype=np.float64)
    p1 = np.array([bx, by], dtype=np.float64)
    d = p1 - p0
    L = float(np.linalg.norm(d))
    if L < 1e-6:
        return None
    u = d / L
    n = np.array([-float(u[1]), float(u[0])], dtype=np.float64) * float(half_width)
    corners = np.stack([p0 + n, p0 - n, p1 - n, p1 + n])
    return corners.astype(np.float32)


def foot_below_fence_polyline(
    px: float, py: float,
    pts_scaled: list[list[float]],
    fw: int, fh: int,
) -> bool:
    """
    Check if point (px,py) is below the fence polyline in image coordinates.
    Interpolates y at the x-position and returns py >= interp_y.
    """
    if fw <= 0 or fh <= 0 or len(pts_scaled) < 2:
        return False
    n = len(pts_scaled)
    for i in range(n - 1):
        x1, y1 = pts_scaled[i][0], pts_scaled[i][1]
        x2, y2 = pts_scaled[i + 1][0], pts_scaled[i + 1][1]
        xmin, xmax = (x1, x2) if x1 <= x2 else (x2, x1)
        if xmin <= px <= xmax:
            dx = x2 - x1
            if abs(dx) < 1e-6:
                interp_y = (y1 + y2) / 2.0
            else:
                interp_y = y1 + (px - x1) * (y2 - y1) / dx
            return py >= interp_y
    # px outside all segments: use nearest endpoint segment
    if px < pts_scaled[0][0]:
        x1, y1 = pts_scaled[0][0], pts_scaled[0][1]
        x2, y2 = pts_scaled[1][0], pts_scaled[1][1]
    else:
        x1, y1 = pts_scaled[-2][0], pts_scaled[-2][1]
        x2, y2 = pts_scaled[-1][0], pts_scaled[-1][1]
    dx = x2 - x1
    if abs(dx) < 1e-6:
        interp_y = (y1 + y2) / 2.0
    else:
        interp_y = y1 + (px - x1) * (y2 - y1) / dx
    return py >= interp_y


# ---------------------------------------------------------------------------
# polygon.yaml loaders (map by IP) — fence-specific
# ---------------------------------------------------------------------------

def load_polygon_yaml_region1_by_ip(yaml_path: Path) -> dict[str, tuple[np.ndarray, tuple[int, int]]]:
    """Load regions.region1 polygons from polygon.yaml, mapped by camera IP."""
    yaml_path = yaml_path.expanduser().resolve()
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, tuple[np.ndarray, tuple[int, int]]] = {}
    for _cid, node in cams.items():
        if not isinstance(node, dict):
            continue
        ip = extract_ip_from_rtsp(str(node.get("rtsp_url", "") or ""))
        if not ip:
            continue
        poly_arr: np.ndarray | None = None
        regions = node.get("regions", {})
        if isinstance(regions, dict):
            r1 = regions.get("region1")
            if isinstance(r1, list):
                pl = parse_pt_list(r1)
                if len(pl) >= 3:
                    poly_arr = np.asarray(pl, dtype=np.float32)
        if poly_arr is None or poly_arr.shape[0] < 3:
            continue
        res = node.get("resolution", {}) if isinstance(node.get("resolution"), dict) else {}
        rw = int(res.get("width", 1920))
        rh = int(res.get("height", 1080))
        if rw <= 0 or rh <= 0:
            rw, rh = 1920, 1080
        out[ip] = (poly_arr, (rw, rh))
    return out


def load_polygon_yaml_region2_by_ip(yaml_path: Path) -> dict[str, tuple[np.ndarray, tuple[int, int]]]:
    """Load regions.region2 polygons from polygon.yaml, mapped by camera IP."""
    yaml_path = yaml_path.expanduser().resolve()
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, tuple[np.ndarray, tuple[int, int]]] = {}
    for _cid, node in cams.items():
        if not isinstance(node, dict):
            continue
        ip = extract_ip_from_rtsp(str(node.get("rtsp_url", "") or ""))
        if not ip:
            continue
        poly_arr: np.ndarray | None = None
        regions = node.get("regions", {})
        if isinstance(regions, dict):
            r2 = regions.get("region2")
            if isinstance(r2, list):
                pl = parse_pt_list(r2)
                if len(pl) >= 3:
                    poly_arr = np.asarray(pl, dtype=np.float32)
        if poly_arr is None or poly_arr.shape[0] < 3:
            continue
        res = node.get("resolution", {}) if isinstance(node.get("resolution"), dict) else {}
        rw = int(res.get("width", 1920))
        rh = int(res.get("height", 1080))
        if rw <= 0 or rh <= 0:
            rw, rh = 1920, 1080
        out[ip] = (poly_arr, (rw, rh))
    return out


def load_polygon_yaml_fence_line_by_ip(
    yaml_path: Path,
) -> dict[str, tuple[list[list[float]], tuple[int, int]]]:
    """Load cameras.*.line (polyline >= 2 points) from polygon.yaml, mapped by IP."""
    yaml_path = yaml_path.expanduser().resolve()
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, tuple[list[list[float]], tuple[int, int]]] = {}
    for _cid, node in cams.items():
        if not isinstance(node, dict):
            continue
        ip = extract_ip_from_rtsp(str(node.get("rtsp_url", "") or ""))
        if not ip:
            continue
        ln = node.get("line")
        if not isinstance(ln, list):
            continue
        pl = parse_pt_list(ln)
        if len(pl) < 2:
            continue
        res = node.get("resolution", {}) if isinstance(node.get("resolution"), dict) else {}
        rw = int(res.get("width", 1920))
        rh = int(res.get("height", 1080))
        if rw <= 0 or rh <= 0:
            rw, rh = 1920, 1080
        out[ip] = ([[float(p[0]), float(p[1])] for p in pl], (rw, rh))
    return out


def load_configs_yaml_treo_polygon_by_ip(
    config_path: Path,
) -> dict[str, tuple[np.ndarray, tuple[int, int]]]:
    """Load Treo_rao polygons from src/backend/api/configs.yaml, mapped by IP."""
    config_path = config_path.expanduser().resolve()
    data = load_yaml(config_path)
    treo = data.get("Treo_rao") or data.get("treo_rao") or data.get("Treo_Rao")
    if not isinstance(treo, dict):
        return {}
    cams = treo.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, tuple[np.ndarray, tuple[int, int]]] = {}
    for _name, node in cams.items():
        if not isinstance(node, dict):
            continue
        ip = extract_ip_from_rtsp(str(node.get("rtsp_url", "") or ""))
        if not ip:
            continue
        ims = node.get("image_size", {})
        iw, ih = 1920, 1080
        if isinstance(ims, dict):
            iw = int(ims.get("width", 1920))
            ih = int(ims.get("height", 1080))
        pts_raw = parse_pt_list(node.get("polygon", []) or [])
        if len(pts_raw) < 3:
            continue
        if iw <= 0 or ih <= 0:
            iw, ih = 1920, 1080
        out[ip] = (np.asarray(pts_raw, dtype=np.float32), (iw, ih))
    return out


# ---------------------------------------------------------------------------
# Camera ROI dataclass — fence-specific
# ---------------------------------------------------------------------------

@dataclass
class CameraRoiRefs:
    """Per-camera polygon/ROI references in config coordinate space (not pixel)."""
    region1: np.ndarray | None
    region1_ref: tuple[int, int]
    config_poly: np.ndarray | None
    config_ref: tuple[int, int]
    fence_line: list[list[float]] | None = None
    fence_line_ref: tuple[int, int] = (1920, 1080)
    region2: np.ndarray | None = None
    region2_ref: tuple[int, int] = (1920, 1080)


def build_cam_roi_refs(
    rtsp_pairs: list[tuple[str, str]],
    polygon_yaml: Path,
    configs_yaml: Path,
) -> dict[str, CameraRoiRefs]:
    """Build per-camera ROI references from polygon.yaml and configs.yaml."""
    r1_ip = load_polygon_yaml_region1_by_ip(polygon_yaml.resolve())
    r2_ip = load_polygon_yaml_region2_by_ip(polygon_yaml.resolve())
    fence_ip = load_polygon_yaml_fence_line_by_ip(polygon_yaml.resolve())
    cfg_ip = load_configs_yaml_treo_polygon_by_ip(configs_yaml.resolve())
    out: dict[str, CameraRoiRefs] = {}

    logger.info("=== ROI MAPPING DIAGNOSTIC ===")
    logger.info("  polygon.yaml  : %s", polygon_yaml)
    logger.info("  configs.yaml  : %s", configs_yaml)

    for cam_id, url in rtsp_pairs:
        ip = extract_ip_from_rtsp(url)
        r1_pts, r1_ref = None, (1920, 1080)
        r2_pts, r2_ref = None, (1920, 1080)
        c_pts, c_ref = None, (1920, 1080)
        f_line: list[list[float]] | None = None
        f_ref = (1920, 1080)

        if ip and ip in r1_ip:
            r1_pts, r1_ref = r1_ip[ip]
        elif ip:
            logger.warning("%s: polygon.yaml khong co region1 cho IP=%s", cam_id, ip)

        if ip and ip in r2_ip:
            r2_pts, r2_ref = r2_ip[ip]

        if ip and ip in fence_ip:
            f_line, f_ref = fence_ip[ip]

        if ip and ip in cfg_ip:
            c_pts, c_ref = cfg_ip[ip]
        elif ip:
            logger.warning("%s: configs.yaml khong co Treo_rao polygon cho IP=%s", cam_id, ip)

        out[cam_id] = CameraRoiRefs(
            region1=r1_pts,
            region1_ref=r1_ref,
            config_poly=c_pts,
            config_ref=c_ref,
            fence_line=f_line,
            fence_line_ref=f_ref,
            region2=r2_pts,
            region2_ref=r2_ref,
        )

    logger.info("=== END ROI MAPPING ===")
    return out


# ---------------------------------------------------------------------------
# Fence overlay drawing
# ---------------------------------------------------------------------------

def draw_roi_overlay_bgr(
    frame_bgr: np.ndarray,
    mask_poly_xy: np.ndarray | None,
    cfg_poly_xy: np.ndarray | None,
    fence_line_scaled: list[list[float]] | None,
    cam_label: str,
) -> np.ndarray:
    """Draw ROI polygons and fence line overlay onto a copy of the frame."""
    out = frame_bgr.copy()

    def _fill_poly_alpha(img: np.ndarray, pts: np.ndarray, color_bgr: tuple, alpha: float = 0.20) -> None:
        overlay = img.copy()
        cnt = pts.astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(overlay, [cnt], color_bgr)
        cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
        cv2.polylines(img, [cnt], isClosed=True, color=color_bgr, thickness=2, lineType=cv2.LINE_AA)

    if mask_poly_xy is not None and len(mask_poly_xy) >= 3:
        _fill_poly_alpha(out, mask_poly_xy, (255, 255, 0))  # cyan

    if cfg_poly_xy is not None and len(cfg_poly_xy) >= 3:
        _fill_poly_alpha(out, cfg_poly_xy, (0, 255, 255))  # yellow

    if fence_line_scaled is not None and len(fence_line_scaled) >= 2:
        pts_line = np.array([[int(p[0]), int(p[1])] for p in fence_line_scaled], dtype=np.int32)
        cv2.polylines(out, [pts_line], isClosed=False, color=(0, 0, 255), thickness=2, lineType=cv2.LINE_AA)
        for p in fence_line_scaled:
            cv2.circle(out, (int(p[0]), int(p[1])), 4, (0, 0, 255), -1)

    # Legend
    cv2.rectangle(out, (4, 4), (320, 74), (30, 30, 30), -1)
    cv2.putText(out, cam_label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, "CYAN: mask(region1/stripe)", (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(out, "YEL : config polygon(Treo_rao)", (8, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, "RED : fence line", (8, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1, cv2.LINE_AA)

    return out
