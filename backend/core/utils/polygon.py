"""
Generic polygon / YAML / ROI utilities.

Chỉ chứa hàm dùng chung cho mọi module.
Fence-specific functions nằm trong src.backend.modules.fence.geometry.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.backend.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    """Safely load a YAML file. Returns empty dict on error."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_ip_from_rtsp(url: str) -> str | None:
    """Extract IP address from an RTSP URL string."""
    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", url or "")
    return m.group(1) if m else None


def parse_pt_list(seq: object) -> list[list[float]]:
    """Parse a list of [x, y] point pairs from YAML data."""
    out: list[list[float]] = []
    if not isinstance(seq, list):
        return out
    for p in seq:
        if isinstance(p, list) and len(p) == 2:
            try:
                out.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Polygon scaling
# ---------------------------------------------------------------------------

def scale_polygon_xy(
    poly: np.ndarray,
    src_w: int, src_h: int,
    dst_w: int, dst_h: int,
) -> np.ndarray:
    """Scale polygon coordinates from (src_w, src_h) to (dst_w, dst_h)."""
    if poly is None or poly.shape[0] < 3:
        return poly
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return poly
    sx = float(dst_w) / float(src_w)
    sy = float(dst_h) / float(src_h)
    out = np.empty_like(poly, dtype=np.float32)
    out[:, 0] = poly[:, 0].astype(np.float32) * sx
    out[:, 1] = poly[:, 1].astype(np.float32) * sy
    return out


# ---------------------------------------------------------------------------
# Mask / overlay helpers
# ---------------------------------------------------------------------------

def apply_region1_zero_inside(frame: np.ndarray, poly_xy: np.ndarray | None) -> np.ndarray:
    """Zero-out BGR pixels INSIDE the region1 polygon. Keep pixels outside."""
    if poly_xy is None or poly_xy.shape[0] < 3:
        return frame
    h, w = int(frame.shape[0]), int(frame.shape[1])
    if h <= 0 or w <= 0:
        return frame
    mask = np.zeros((h, w), dtype=np.uint8)
    cnt = poly_xy.astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(mask, [cnt], 255)
    out = frame.copy()
    out[mask > 0] = 0
    return out


# ---------------------------------------------------------------------------
# Region-based helpers (generic, for any module)
# ---------------------------------------------------------------------------

def load_polygons_by_camera(yaml_path: Path) -> dict[str, np.ndarray]:
    """Load legacy single-polygon per camera from polygon.yaml."""
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, np.ndarray] = {}
    for cam_id, node in cams.items():
        if not isinstance(node, dict):
            continue
        pts = node.get("polygon", [])
        if not isinstance(pts, list):
            continue
        parsed = parse_pt_list(pts)
        if len(parsed) >= 3:
            out[str(cam_id)] = np.asarray(parsed, dtype=np.float32)
    return out


def load_regions_by_camera(yaml_path: Path) -> dict[str, dict[str, np.ndarray]]:
    """Load cameras.*.regions.region1/2/3 from polygon.yaml."""
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, dict[str, np.ndarray]] = {}
    for cam_id, node in cams.items():
        if not isinstance(node, dict):
            continue
        regions_raw = node.get("regions")
        if not isinstance(regions_raw, dict):
            continue
        cmap: dict[str, np.ndarray] = {}
        for rname in ("region1", "region2", "region3"):
            raw = regions_raw.get(rname)
            if isinstance(raw, list):
                parsed = parse_pt_list(raw)
                if len(parsed) >= 3:
                    cmap[rname] = np.asarray(parsed, dtype=np.float32)
        if cmap:
            out[str(cam_id)] = cmap
    return out


def load_ref_resolution_by_camera(yaml_path: Path) -> dict[str, tuple[int, int]]:
    """Load resolution.width/height per camera from polygon.yaml."""
    data = load_yaml(yaml_path)
    cams = data.get("cameras", {})
    if not isinstance(cams, dict):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for cam_id, node in cams.items():
        if not isinstance(node, dict):
            continue
        res_block = node.get("resolution") or {}
        if isinstance(res_block, dict):
            try:
                w = int(res_block.get("width", 0) or 0)
                h = int(res_block.get("height", 0) or 0)
                if w > 0 and h > 0:
                    out[str(cam_id)] = (w, h)
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# PTZ preset lines
# ---------------------------------------------------------------------------

def load_ptz_preset_lines(yaml_path: Path) -> dict[int, dict]:
    """
    Load PTZ preset fence lines from polygon.yaml → ptz_presets section.

    Returns dict keyed by preset_id with:
        {
            "line": [[x, y], ...],
            "resolution": (width, height),
            "preset_name": str,
        }
    """
    data = load_yaml(yaml_path)
    ptz = data.get("ptz_presets", {})
    if not isinstance(ptz, dict):
        return {}
    out: dict[int, dict] = {}
    for key, node in ptz.items():
        if not isinstance(node, dict):
            continue
        try:
            preset_id = int(node.get("preset_id", key))
        except (TypeError, ValueError):
            continue
        ln = node.get("line")
        if not isinstance(ln, list):
            continue
        pts = parse_pt_list(ln)
        if len(pts) < 2:
            continue
        res = node.get("resolution", {})
        rw = int(res.get("width", 1920)) if isinstance(res, dict) else 1920
        rh = int(res.get("height", 1080)) if isinstance(res, dict) else 1080
        out[preset_id] = {
            "line": pts,
            "resolution": (rw, rh),
            "preset_name": str(node.get("preset_name", f"preset{preset_id}")),
        }
    return out
