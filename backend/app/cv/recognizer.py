"""
Face Recognition — ArcFace embedding + pgvector cosine similarity search.

Uses InsightFace's integrated ArcFace model for 512-dim embeddings.
Searches the PostgreSQL database using pgvector's cosine distance operator.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of a face recognition search."""
    student_id: uuid.UUID
    student_code: str
    full_name: str
    score: float  # cosine similarity (0.0 – 1.0)


class FaceRecognizer:
    """
    Face embedding computation and similarity search against pgvector.

    The InsightFace model pack (buffalo_l) already includes ArcFace,
    so embeddings are computed as part of face detection.
    """

    def __init__(self):
        self._initialized = False

    def get_embedding(self, face) -> Optional[np.ndarray]:
        """
        Extract 512-dim ArcFace embedding from a detected face.

        Args:
            face: InsightFace Face object (from detector.detect())

        Returns:
            Normalized 512-dim numpy array, or None if no embedding.
        """
        if face is None:
            return None

        embedding = getattr(face, "embedding", None)
        if embedding is None:
            return None

        # Normalize to unit vector for cosine similarity
        norm = np.linalg.norm(embedding)
        if norm < 1e-6:
            return None
        return (embedding / norm).astype(np.float32)

    async def search_top_k(
        self,
        embedding: np.ndarray,
        db: AsyncSession,
        class_id: Optional[uuid.UUID] = None,
        top_k: int = 5,
    ) -> List[MatchResult]:
        """
        Search for the top-K most similar face embeddings in the database.

        Uses pgvector's cosine distance operator (<=>) for efficient search.

        Args:
            embedding: 512-dim query vector
            db: Async database session
            class_id: Optional filter by class
            top_k: Number of results to return

        Returns:
            List of MatchResult sorted by similarity (highest first)
        """
        # Convert embedding to PostgreSQL vector string
        vec_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

        # Build query with pgvector cosine distance
        if class_id:
            query = text("""
                SELECT
                    fe.student_id,
                    s.student_code,
                    s.full_name,
                    1 - (fe.embedding <=> :query_vec::vector) AS score
                FROM face_embeddings fe
                JOIN students s ON s.id = fe.student_id
                WHERE s.class_id = :class_id
                ORDER BY fe.embedding <=> :query_vec::vector
                LIMIT :top_k
            """)
            result = await db.execute(
                query,
                {"query_vec": vec_str, "class_id": str(class_id), "top_k": top_k},
            )
        else:
            query = text("""
                SELECT
                    fe.student_id,
                    s.student_code,
                    s.full_name,
                    1 - (fe.embedding <=> :query_vec::vector) AS score
                FROM face_embeddings fe
                JOIN students s ON s.id = fe.student_id
                ORDER BY fe.embedding <=> :query_vec::vector
                LIMIT :top_k
            """)
            result = await db.execute(
                query, {"query_vec": vec_str, "top_k": top_k}
            )

        rows = result.all()
        return [
            MatchResult(
                student_id=uuid.UUID(str(row[0])),
                student_code=row[1],
                full_name=row[2],
                score=float(row[3]),
            )
            for row in rows
        ]

    async def find_best_match(
        self,
        embedding: np.ndarray,
        db: AsyncSession,
        class_id: Optional[uuid.UUID] = None,
    ) -> Optional[MatchResult]:
        """Find the single best match for a face embedding."""
        results = await self.search_top_k(embedding, db, class_id, top_k=1)
        return results[0] if results else None
