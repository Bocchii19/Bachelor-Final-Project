"""
Face Capture — InsightFace detect + crop + save.

Adapted from ptz_patrol/src/face_recognizer.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Lazy import InsightFace
_INSIGHTFACE_AVAILABLE: bool | None = None
_insightface_module = None


def _check_insightface() -> bool:
    global _INSIGHTFACE_AVAILABLE, _insightface_module
    if _INSIGHTFACE_AVAILABLE is None:
        try:
            import insightface
            _insightface_module = insightface
            _INSIGHTFACE_AVAILABLE = True
            logger.info("InsightFace available.")
        except ImportError:
            _INSIGHTFACE_AVAILABLE = False
            logger.warning(
                "insightface not installed. "
                "Run: pip install insightface onnxruntime-gpu"
            )
    return _INSIGHTFACE_AVAILABLE


class FaceCapture:
    """
    InsightFace-based face detection + crop + save.

    Usage:
        fc = FaceCapture(save_dir="results/captures")
        faces = fc.detect_faces(frame)
        for face in faces:
            fc.save_capture(face, full_frame, preset_info)
    """

    def __init__(
        self,
        save_dir: str = "results/captures",
        min_face_size: int = 50,
        det_size: tuple[int, int] = (640, 640),
    ) -> None:
        self._save_dir = Path(save_dir)
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._min_face_size = min_face_size
        self._det_size = det_size
        self._app = None
        self._initialized = False

    def initialize(self) -> bool:
        """Load InsightFace model."""
        if self._initialized:
            return True
        if not _check_insightface():
            return False
        try:
            self._app = _insightface_module.app.FaceAnalysis(
                name="buffalo_l",
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=0, det_size=self._det_size)
            self._initialized = True
            logger.info("InsightFace initialized: det_size=%s", self._det_size)
            return True
        except Exception as e:
            logger.error("InsightFace init failed: %s", e)
            return False

    def detect_faces(self, frame: np.ndarray) -> list[dict]:
        """
        Detect faces in frame.

        Returns list of dicts:
            {bbox, confidence, face_crop, embedding, landmarks}
        """
        if not self._initialized and not self.initialize():
            return []

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            faces_raw = self._app.get(rgb)

            faces = []
            h, w = frame.shape[:2]
            for face in faces_raw:
                bbox = face.bbox.astype(int)
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

                face_w = x2 - x1
                face_h = y2 - y1
                if face_w < self._min_face_size or face_h < self._min_face_size:
                    continue

                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w, x2)
                y2 = min(h, y2)

                faces.append({
                    "bbox": (x1, y1, x2, y2),
                    "confidence": float(face.det_score),
                    "face_crop": frame[y1:y2, x1:x2].copy(),
                    "embedding": (
                        face.embedding
                        if hasattr(face, "embedding") and face.embedding is not None
                        else None
                    ),
                })

            logger.info(
                "[FACE] %d face(s) detected (from %d raw)",
                len(faces), len(faces_raw),
            )
            return faces

        except Exception as e:
            logger.error("[FACE] Detection error: %s", e)
            return []

    def save_capture(
        self,
        face_info: dict,
        full_frame: np.ndarray,
        preset_info: dict,
        person_index: int = 0,
        overview_frame: Optional[np.ndarray] = None,
    ) -> dict:
        """
        Save face crop + full frame + metadata JSON.

        Returns dict with file paths.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        preset_id = preset_info.get("id", 0)
        preset_name = preset_info.get("name", "unknown")
        base = f"{ts}_preset{preset_id}"
        paths: dict[str, str] = {}

        try:
            # Face crop
            face_path = self._save_dir / f"{base}_person{person_index}_face.jpg"
            cv2.imwrite(str(face_path), face_info["face_crop"])
            paths["face_path"] = str(face_path)

            # Full frame (zoomed)
            full_path = self._save_dir / f"{base}_person{person_index}_full.jpg"
            cv2.imwrite(str(full_path), full_frame)
            paths["full_path"] = str(full_path)

            # Overview (wide-angle)
            if overview_frame is not None:
                ov_path = self._save_dir / f"{base}_overview.jpg"
                if not ov_path.exists():
                    cv2.imwrite(str(ov_path), overview_frame)
                    paths["overview_path"] = str(ov_path)

            # Metadata
            meta = {
                "timestamp": ts,
                "preset_id": preset_id,
                "preset_name": preset_name,
                "person_index": person_index,
                "face_bbox": list(face_info["bbox"]),
                "face_confidence": face_info["confidence"],
            }
            meta_path = self._save_dir / f"{base}_person{person_index}.json"
            meta_path.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            paths["meta_path"] = str(meta_path)

        except Exception as e:
            logger.error("[SAVE] Error: %s", e)

        return paths

    @staticmethod
    def draw_persons(
        frame: np.ndarray,
        persons: list[tuple[int, int, int, int, float]],
    ) -> np.ndarray:
        """Draw person bboxes on frame (for overview)."""
        vis = frame.copy()
        for i, (x1, y1, x2, y2, conf) in enumerate(persons):
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(
                vis, f"P{i} {conf:.2f}", (x1, y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2,
            )
        return vis
