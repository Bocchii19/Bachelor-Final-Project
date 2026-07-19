"""
Thread-safe YOLO wrapper — shared ONNX/CUDA session.

Ultralytics YOLO creates a new ONNX Runtime CUDA session per thread.
On devices with limited GPU memory (e.g. Jetson Orin ~8GB), this causes
CUBLAS_STATUS_ALLOC_FAILED when multiple monitors run inference concurrently.

This wrapper:
  1. Holds a single YOLO model instance
  2. Uses a threading Lock to serialize inference calls
  3. Warms up the model on first call (creates the CUDA session once)

Usage:
    from src.backend.core.ai.yolo_shared import SharedYOLO

    shared = SharedYOLO(model_path)
    # Pass shared to all monitors / tracker — they all call shared(frame, ...)
    results = shared(frame, conf=0.5, device="0", imgsz=640)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class SharedYOLO:
    """
    Thread-safe wrapper around Ultralytics YOLO.

    Serializes all inference calls through a lock so only ONE
    ONNX Runtime CUDA session is ever created and used.
    """

    def __init__(self, model_path: str | Path) -> None:
        from ultralytics import YOLO

        self._model = YOLO(str(model_path))
        self._lock = threading.Lock()
        self._warmed_up = False

    def _warmup(self, device: str | None = "0", imgsz: int = 640) -> None:
        """Run one dummy inference to initialize ONNX session on the main thread."""
        if self._warmed_up:
            return
        logger.info("SharedYOLO: warming up (device=%s, imgsz=%d)...", device, imgsz)
        dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
        try:
            self._model(dummy, conf=0.5, device=device, imgsz=imgsz, verbose=False)
        except Exception as e:
            logger.warning("SharedYOLO warmup exception (may be OK): %s", e)
        self._warmed_up = True
        logger.info("SharedYOLO: warmup done — single CUDA session active.")

    def warmup(self, device: str | None = "0", imgsz: int = 640) -> None:
        """Public warmup — call once before starting monitor threads."""
        with self._lock:
            self._warmup(device=device, imgsz=imgsz)

    def __call__(
        self,
        source,
        *,
        conf: float = 0.5,
        device: str | None = "0",
        imgsz: int = 640,
        verbose: bool = False,
        **kwargs,
    ):
        """
        Thread-safe inference.

        Acquires lock → runs model → releases lock.
        All threads share the same ONNX CUDA session.
        """
        with self._lock:
            if not self._warmed_up:
                self._warmup(device=device, imgsz=imgsz)
            return self._model(
                source,
                conf=conf,
                device=device,
                imgsz=imgsz,
                verbose=verbose,
                **kwargs,
            )

    # ── Proxy common attributes ──

    @property
    def names(self):
        return self._model.names

    @property
    def model(self):
        return self._model.model

    def __getattr__(self, name):
        """Proxy any attribute access to the underlying YOLO model."""
        return getattr(self._model, name)
