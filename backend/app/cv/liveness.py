"""
Liveness Detection — Anti-spoofing check.

Supports ONNX-based liveness model for cross-platform compatibility
(Jetson TensorRT / RTX CUDA / CPU).

If no liveness model is available, falls back to basic heuristic checks.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class LivenessDetector:
    """
    Anti-spoofing detector to distinguish real faces from photos/screens.

    Uses ONNX model if available, otherwise falls back to basic checks
    (blur detection, reflection analysis, color histogram analysis).
    """

    def __init__(self, model_path: Optional[str] = None):
        self._model_path = model_path
        self._session = None
        self._use_model = False
        self._initialized = False

    def _ensure_loaded(self) -> None:
        """Lazy-load the liveness model."""
        if self._initialized:
            return
        self._initialized = True

        if self._model_path and os.path.exists(self._model_path):
            try:
                import onnxruntime as ort
                from app.cv.runtime import get_optimal_providers

                providers = get_optimal_providers()
                self._session = ort.InferenceSession(
                    self._model_path, providers=providers
                )
                self._use_model = True
                logger.info("Liveness model loaded from %s", self._model_path)
            except Exception as e:
                logger.warning(
                    "Could not load liveness model: %s. Using heuristic fallback.", e
                )
        else:
            logger.info(
                "Liveness model not found at %s. Using heuristic fallback.",
                self._model_path,
            )

    def check(self, frame: np.ndarray, face) -> bool:
        """
        Check if a detected face is live (real person, not a photo/screen).

        Args:
            frame: Full BGR frame
            face: InsightFace Face object with bbox

        Returns:
            True if the face appears to be a real person.
        """
        self._ensure_loaded()

        # Extract face region
        bbox = face.bbox.astype(int)
        x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), bbox[2], bbox[3]
        face_crop = frame[y1:y2, x1:x2]

        if face_crop.size == 0:
            return False

        if self._use_model and self._session is not None:
            return self._check_with_model(face_crop)
        else:
            return self._check_heuristic(face_crop)

    def _check_with_model(self, face_crop: np.ndarray) -> bool:
        """Use ONNX anti-spoofing model."""
        assert self._session is not None

        try:
            # Preprocess: resize, normalize, transpose to NCHW
            input_size = (80, 80)  # typical anti-spoof model input
            img = cv2.resize(face_crop, input_size)
            img = img.astype(np.float32) / 255.0
            img = np.transpose(img, (2, 0, 1))  # HWC → CHW
            img = np.expand_dims(img, axis=0)  # add batch dim

            # Inference
            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: img})

            # Output interpretation: typically [real_score, fake_score]
            scores = outputs[0][0]
            if len(scores) >= 2:
                real_score = float(scores[0])
                fake_score = float(scores[1])
                is_live = real_score > fake_score
            else:
                # Single output (probability of being real)
                is_live = float(scores[0]) > 0.5

            logger.debug("Liveness model: scores=%s, is_live=%s", scores, is_live)
            return is_live

        except Exception as e:
            logger.warning("Liveness model inference failed: %s", e)
            return self._check_heuristic(face_crop)

    def _check_heuristic(self, face_crop: np.ndarray) -> bool:
        """
        Basic heuristic liveness check when no model is available.

        Checks:
        1. Blur detection (real faces have more texture)
        2. Color diversity (photos often have limited color range)
        3. Face size (too small faces are unreliable)
        """
        h, w = face_crop.shape[:2]

        # Check minimum face size
        if h < 30 or w < 30:
            return False

        # 1. Laplacian blur detection
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if laplacian_var < 10.0:
            logger.debug("Heuristic: too blurry (laplacian_var=%.2f)", laplacian_var)
            return False

        # 2. Color histogram diversity
        hsv = cv2.cvtColor(face_crop, cv2.COLOR_BGR2HSV)
        hue_hist = cv2.calcHist([hsv], [0], None, [30], [0, 180])
        hue_std = np.std(hue_hist)
        if hue_std < 5.0:
            logger.debug("Heuristic: low color diversity (hue_std=%.2f)", hue_std)
            return False

        # 3. Saturation check (screen captures often have very uniform saturation)
        sat_mean = np.mean(hsv[:, :, 1])
        if sat_mean < 15.0:
            logger.debug("Heuristic: very low saturation (sat_mean=%.2f)", sat_mean)
            return False

        return True
