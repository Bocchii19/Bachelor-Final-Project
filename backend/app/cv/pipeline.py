"""
CV Pipeline — Orchestrates face detection → liveness → recognition → classification.

Central module that processes camera frames and produces attendance events.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.cv.detector import FaceDetector
from app.cv.liveness import LivenessDetector
from app.cv.recognizer import FaceRecognizer, MatchResult
from app.models.attendance import AttendanceRecord
from app.models.unknown_face import UnknownFace

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class FaceResult:
    """Result for a single detected face in a frame."""
    bbox: list  # [x1, y1, x2, y2]
    det_score: float
    is_live: bool
    match: Optional[MatchResult] = None
    action: str = "unknown"  # 'present' | 'suggest' | 'unknown' | 'spoof'


@dataclass
class ProcessResult:
    """Result of processing one frame."""
    total_faces: int = 0
    recognized: List[FaceResult] = field(default_factory=list)
    unrecognized: List[FaceResult] = field(default_factory=list)
    spoofs: List[FaceResult] = field(default_factory=list)
    frame_hash: Optional[str] = None


class CVPipeline:
    """
    Main CV pipeline that processes frames end-to-end.

    Usage:
        pipeline = CVPipeline.get_instance()
        result = await pipeline.process_frame(frame, session_id, db)
    """

    _instance: Optional["CVPipeline"] = None

    def __init__(self):
        self._detector = FaceDetector(model_pack=settings.INSIGHTFACE_MODEL_PACK)
        self._recognizer = FaceRecognizer()
        self._liveness = LivenessDetector(model_path=settings.LIVENESS_MODEL_PATH)
        self._prev_frame_hash: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "CVPipeline":
        """Singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def detect_faces(self, frame: np.ndarray) -> list:
        """Detect all faces in a frame."""
        return self._detector.detect(frame)

    def check_liveness(self, frame: np.ndarray, face) -> bool:
        """Check if a face is live."""
        return self._liveness.check(frame, face)

    def compute_embedding(self, frame: np.ndarray, face) -> Optional[np.ndarray]:
        """Compute 512-dim embedding for a face."""
        return self._recognizer.get_embedding(face)

    def _compute_frame_hash(self, frame: np.ndarray) -> str:
        """Compute a perceptual hash for frame deduplication."""
        small = cv2.resize(frame, (16, 16))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mean_val = gray.mean()
        bits = (gray > mean_val).flatten()
        return "".join("1" if b else "0" for b in bits)

    def _is_duplicate_frame(self, frame: np.ndarray) -> bool:
        """Check if this frame is too similar to the previous one."""
        current_hash = self._compute_frame_hash(frame)
        if self._prev_frame_hash is None:
            self._prev_frame_hash = current_hash
            return False

        # Hamming distance
        diff = sum(a != b for a, b in zip(current_hash, self._prev_frame_hash))
        self._prev_frame_hash = current_hash

        # If less than 10% of bits differ, consider it a duplicate
        return diff < len(current_hash) * 0.10

    async def process_frame(
        self,
        frame: np.ndarray,
        session_id: uuid.UUID,
        db: AsyncSession,
        zone_id: Optional[str] = None,
        class_id: Optional[uuid.UUID] = None,
        skip_dedup: bool = False,
    ) -> ProcessResult:
        """
        Full pipeline: detect → liveness → recognize → classify.

        1. Detect all faces in the frame
        2. For each face:
           a. Liveness check → skip if spoof
           b. Compute embedding (512-dim ArcFace)
           c. Cosine similarity search against class embeddings
           d. Classify by threshold:
              - score >= 0.75 → INSERT attendance_records(status='present')
              - score 0.45–0.74 → INSERT unknown_faces(best_match_id, best_score)
              - score < 0.45 → INSERT unknown_faces(best_match_id=NULL)
        3. Return recognized + unrecognized lists
        """
        result = ProcessResult()

        # Frame deduplication
        if not skip_dedup and self._is_duplicate_frame(frame):
            logger.debug("Skipping duplicate frame")
            return result

        # Step 1: Detect faces
        faces = self._detector.detect(frame)
        result.total_faces = len(faces)

        if not faces:
            return result

        now = datetime.now(timezone.utc)

        for face in faces:
            bbox = face.bbox.tolist()
            det_score = float(face.det_score)

            # Step 2a: Liveness check
            is_live = self._liveness.check(frame, face)
            if not is_live:
                face_result = FaceResult(
                    bbox=bbox, det_score=det_score, is_live=False, action="spoof"
                )
                result.spoofs.append(face_result)
                logger.debug("Face at %s detected as spoof", bbox)
                continue

            # Step 2b: Get embedding
            embedding = self._recognizer.get_embedding(face)
            if embedding is None:
                logger.warning("Could not compute embedding for face at %s", bbox)
                continue

            # Step 2c: Search for best match
            best_match = await self._recognizer.find_best_match(
                embedding, db, class_id
            )

            # Step 2d: Classify by threshold
            score = best_match.score if best_match else 0.0

            if score >= settings.CONFIDENCE_AUTO_PRESENT:
                # AUTO PRESENT
                face_result = FaceResult(
                    bbox=bbox,
                    det_score=det_score,
                    is_live=True,
                    match=best_match,
                    action="present",
                )
                result.recognized.append(face_result)

                # Insert/update attendance record
                assert best_match is not None
                existing = await db.execute(
                    AttendanceRecord.__table__.select().where(
                        AttendanceRecord.student_id == best_match.student_id,
                        AttendanceRecord.session_id == session_id,
                    )
                )
                if not existing.first():
                    db.add(
                        AttendanceRecord(
                            student_id=best_match.student_id,
                            session_id=session_id,
                            status="present",
                            confidence=score,
                            captured_at=now,
                            zone_id=zone_id,
                        )
                    )
                    logger.info(
                        "AUTO PRESENT: %s (%s) score=%.3f",
                        best_match.full_name,
                        best_match.student_code,
                        score,
                    )

            elif score >= settings.CONFIDENCE_SUGGEST:
                # SUGGEST — goes to unknown queue with suggested match
                face_result = FaceResult(
                    bbox=bbox,
                    det_score=det_score,
                    is_live=True,
                    match=best_match,
                    action="suggest",
                )
                result.unrecognized.append(face_result)

                # Save cropped face + add to unknown queue
                image_path = self._save_face_crop(frame, face, session_id)
                assert best_match is not None
                db.add(
                    UnknownFace(
                        session_id=session_id,
                        image_path=image_path,
                        best_match_id=best_match.student_id,
                        best_score=score,
                        zone_id=zone_id,
                        captured_at=now,
                    )
                )
                logger.info(
                    "SUGGEST: best_match=%s score=%.3f",
                    best_match.student_code,
                    score,
                )

            else:
                # UNKNOWN — no good match
                face_result = FaceResult(
                    bbox=bbox,
                    det_score=det_score,
                    is_live=True,
                    match=best_match if best_match and best_match.score > 0 else None,
                    action="unknown",
                )
                result.unrecognized.append(face_result)

                image_path = self._save_face_crop(frame, face, session_id)
                db.add(
                    UnknownFace(
                        session_id=session_id,
                        image_path=image_path,
                        best_match_id=best_match.student_id if best_match else None,
                        best_score=score if best_match else None,
                        zone_id=zone_id,
                        captured_at=now,
                    )
                )
                logger.info("UNKNOWN: no match (best_score=%.3f)", score)

        await db.flush()
        return result

    def _save_face_crop(
        self, frame: np.ndarray, face, session_id: uuid.UUID
    ) -> str:
        """Save cropped face image to disk. Returns the file path."""
        bbox = face.bbox.astype(int)
        x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), bbox[2], bbox[3]

        # Add 20% margin around face
        h, w = frame.shape[:2]
        margin_x = int((x2 - x1) * 0.2)
        margin_y = int((y2 - y1) * 0.2)
        x1 = max(0, x1 - margin_x)
        y1 = max(0, y1 - margin_y)
        x2 = min(w, x2 + margin_x)
        y2 = min(h, y2 + margin_y)

        face_crop = frame[y1:y2, x1:x2]

        save_dir = os.path.join(
            settings.MEDIA_ROOT, "unknown_faces", str(session_id)
        )
        os.makedirs(save_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex[:12]}.jpg"
        filepath = os.path.join(save_dir, filename)
        cv2.imwrite(filepath, face_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])

        return filepath
