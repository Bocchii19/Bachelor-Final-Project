"""
Face Detection — Using InsightFace's RetinaFace detector.

InsightFace uses ONNX Runtime under the hood, so our hardware
auto-detection (TensorRT/CUDA/CPU) applies automatically.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FaceDetector:
    """
    Face detection using InsightFace (RetinaFace / SCRFD).

    InsightFace's `buffalo_l` model pack includes a SCRFD detector
    which is faster and more accurate than MTCNN for our use case.
    """

    def __init__(self, model_pack: str = "buffalo_l", det_size: tuple = (640, 640)):
        self._model_pack = model_pack
        self._det_size = det_size
        self._app = None

    def _ensure_loaded(self) -> None:
        """Lazy-load the InsightFace app."""
        if self._app is not None:
            return

        from app.cv.runtime import get_optimal_providers

        import insightface
        from insightface.app import FaceAnalysis

        providers = get_optimal_providers()
        logger.info(
            "Initializing FaceDetector with model=%s, providers=%s",
            self._model_pack,
            providers,
        )

        self._app = FaceAnalysis(
            name=self._model_pack,
            providers=providers,
        )
        self._app.prepare(ctx_id=0, det_size=self._det_size)
        logger.info("FaceDetector ready (det_size=%s)", self._det_size)

    def detect(self, frame: np.ndarray, max_faces: int = 50) -> list:
        """
        Detect faces in a BGR frame.

        Returns:
            List of InsightFace Face objects. Each has:
              - face.bbox: [x1, y1, x2, y2]
              - face.det_score: detection confidence
              - face.embedding: 512-dim (if recognition model loaded)
              - face.kps: 5 keypoints (eyes, nose, mouth corners)
        """
        self._ensure_loaded()
        assert self._app is not None

        faces = self._app.get(frame)

        # Sort by detection score (highest first)
        faces = sorted(faces, key=lambda f: f.det_score, reverse=True)

        if max_faces and len(faces) > max_faces:
            faces = faces[:max_faces]

        return faces

    def detect_largest(self, frame: np.ndarray):
        """Detect and return the single largest face (by bounding box area)."""
        faces = self.detect(frame, max_faces=10)
        if not faces:
            return None

        def bbox_area(face):
            bbox = face.bbox
            return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

        return max(faces, key=bbox_area)
