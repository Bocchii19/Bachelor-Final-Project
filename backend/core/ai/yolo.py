"""
YOLO model resolution, TensorRT helpers, CUDA cache management.

Consolidated from duplicated code across 7+ scripts.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from src.backend.core.config import MODEL_STEM, MODELS_DIR, SRC_MODELS_DIR, PROJECT_ROOT
from src.backend.core.logger import get_logger

logger = get_logger(__name__)


def resolve_model_path(user: Path | None) -> Path:
    """
    Find inference model file.
    Priority: user path → .engine → .trt → .onnx → .pt
    Searches: models/, src/models/, src/models/v*/
    """
    if user is not None:
        p = user.expanduser().resolve()
        if p.is_file():
            return p

    # Build search directories: flat dirs + version subdirs under src/models/
    search_dirs = [MODELS_DIR, SRC_MODELS_DIR, PROJECT_ROOT]
    if SRC_MODELS_DIR.exists():
        search_dirs += sorted(SRC_MODELS_DIR.iterdir())  # v4/, v5/, etc.

    for base in search_dirs:
        if not base.is_dir():
            continue
        for ext in (".onnx", ".engine", ".trt", ".pt"):
            c = (base / f"{MODEL_STEM}{ext}").resolve()
            if c.is_file():
                logger.info("Found model: %s", c)
                return c
    raise FileNotFoundError(
        f"Khong tim thay {MODEL_STEM}.engine, .trt hoac .pt trong {MODELS_DIR} hoac {SRC_MODELS_DIR}. "
        f"Chay export_tensorrt.py, hoac --model /duong/den/model"
    )


def path_for_ultralytics_load(p: Path) -> Path:
    """
    Ultralytics only accepts `*.engine` for TensorRT.
    If only `*.trt` exists (same content), create a temp symlink with .engine suffix.
    """
    p = p.resolve()
    s = p.suffix.lower()
    if s == ".engine":
        return p
    if s == ".trt":
        eng = p.with_suffix(".engine")
        if eng.is_file():
            return eng
        tdir = Path(tempfile.gettempdir()) / "ultralytics_trt_engine"
        tdir.mkdir(parents=True, exist_ok=True)
        h = hashlib.md5(str(p).encode()).hexdigest()[:12]
        link = tdir / f"{p.stem}_{h}.engine"
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
        except OSError:
            pass
        link.symlink_to(p)
        return link
    return p


def is_tensorrt_path(p: Path) -> bool:
    """Check if path points to a TensorRT engine file."""
    return p.suffix.lower() in (".trt", ".engine")


def maybe_empty_cuda_cache() -> None:
    """Free unused CUDA memory. Safe to call even without torch/CUDA."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def extract_trt_imgsz_from_assertion(err: BaseException) -> int | None:
    """
    Parse TensorRT size mismatch error to extract expected image size.
    Example: "input size torch.Size([1, 3, 640, 640]) not equal to max model size (1, 3, 512, 512)"
    """
    msg = str(err)
    if "max model size" not in msg:
        return None
    m = re.search(r"max model size\s*\(\s*\d+\s*,\s*\d+\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", msg)
    if not m:
        return None
    try:
        h = int(m.group(1))
        w = int(m.group(2))
        if h > 0 and w > 0 and h == w:
            return h
        if h > 0 and w > 0:
            return min(h, w)
    except ValueError:
        return None
    return None
