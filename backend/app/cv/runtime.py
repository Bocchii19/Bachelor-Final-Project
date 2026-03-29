"""
ONNX Runtime — Hardware auto-detection and provider management.

Supports:
  - NVIDIA Jetson (ARM64): TensorrtExecutionProvider
  - PC with RTX GPU (x86): CUDAExecutionProvider
  - CPU fallback: CPUExecutionProvider

Priority: TensorRT > CUDA > CPU
"""

from __future__ import annotations

import logging
import platform
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger(__name__)

# Provider priority order
PROVIDER_PRIORITY = [
    "TensorrtExecutionProvider",
    "CUDAExecutionProvider",
    "CPUExecutionProvider",
]


def _is_jetson() -> bool:
    """Detect if running on NVIDIA Jetson (ARM64 + tegra)."""
    try:
        arch = platform.machine().lower()
        if arch not in ("aarch64", "arm64"):
            return False
        # Check for Jetson-specific file
        with open("/proc/device-tree/model", "r") as f:
            model = f.read().lower()
            return "jetson" in model or "tegra" in model
    except (FileNotFoundError, PermissionError):
        return False


def _has_nvidia_gpu() -> bool:
    """Detect if NVIDIA GPU is available."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@lru_cache
def get_available_providers() -> List[str]:
    """Return list of available ONNX Runtime execution providers."""
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        logger.info("ONNX Runtime available providers: %s", available)
        return available
    except ImportError:
        logger.warning("onnxruntime not installed, falling back to CPU")
        return ["CPUExecutionProvider"]


@lru_cache
def get_optimal_providers() -> List[str]:
    """
    Determine the optimal provider chain based on hardware.

    Returns providers in priority order — ONNX Runtime will try each
    in sequence and use the first one that works.
    """
    from app.config import get_settings
    settings = get_settings()

    # If user specified providers, use those
    if settings.onnx_providers_list:
        logger.info("Using user-specified ONNX providers: %s", settings.onnx_providers_list)
        return settings.onnx_providers_list

    available = get_available_providers()

    # Auto-detect optimal providers
    selected: List[str] = []
    is_jetson = _is_jetson()

    if is_jetson:
        logger.info("Detected NVIDIA Jetson platform (ARM64)")
        if "TensorrtExecutionProvider" in available:
            selected.append("TensorrtExecutionProvider")
            logger.info("✓ Using TensorRT (optimal for Jetson)")
        elif "CUDAExecutionProvider" in available:
            selected.append("CUDAExecutionProvider")
            logger.info("✓ Using CUDA (Jetson fallback)")
    else:
        if "CUDAExecutionProvider" in available:
            selected.append("CUDAExecutionProvider")
            logger.info("✓ Using CUDA (RTX GPU detected)")
        if "TensorrtExecutionProvider" in available:
            # On desktop, TensorRT can also be beneficial
            selected.insert(0, "TensorrtExecutionProvider")
            logger.info("✓ TensorRT also available, adding as primary")

    # Always add CPU as final fallback
    selected.append("CPUExecutionProvider")

    logger.info("Selected ONNX provider chain: %s", selected)
    return selected


def get_device_info() -> dict:
    """Return a summary of detected hardware capabilities."""
    info = {
        "arch": platform.machine(),
        "platform": platform.platform(),
        "is_jetson": _is_jetson(),
        "has_nvidia_gpu": _has_nvidia_gpu(),
        "available_providers": get_available_providers(),
        "selected_providers": get_optimal_providers(),
    }

    # Try to get GPU info
    if info["has_nvidia_gpu"]:
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["gpu_info"] = result.stdout.strip()
        except Exception:
            pass

    return info
