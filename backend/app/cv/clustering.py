"""
Unknown Face Clustering — DBSCAN on face embeddings.

Groups unknown faces from the same session that likely belong to the same person,
so admin only needs to verify once per cluster.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cv.recognizer import FaceRecognizer
from app.models.unknown_face import UnknownFace

logger = logging.getLogger(__name__)


async def cluster_unknown_faces(
    session_id: uuid.UUID,
    db: AsyncSession,
    eps: float = 0.35,
    min_samples: int = 1,
) -> int:
    """
    Cluster unknown faces from a session using DBSCAN.

    1. Fetch all unknown_faces for this session without a cluster_id
    2. Load each face image and compute embedding
    3. Run DBSCAN with cosine metric
    4. Assign cluster_id to each unknown face

    Args:
        session_id: Session to cluster
        db: Async database session
        eps: DBSCAN epsilon (cosine distance threshold)
        min_samples: Minimum samples per cluster

    Returns:
        Number of clusters found
    """
    # Fetch unclustered unknown faces
    result = await db.execute(
        select(UnknownFace).where(
            UnknownFace.session_id == session_id,
            UnknownFace.cluster_id.is_(None),
            UnknownFace.status == "pending",
        )
    )
    faces = result.scalars().all()

    if len(faces) < 2:
        # Assign individual cluster IDs
        for face in faces:
            face.cluster_id = uuid.uuid4()
        await db.flush()
        return len(faces)

    logger.info(
        "Clustering %d unknown faces for session %s", len(faces), session_id
    )

    # Compute embeddings for each face
    import cv2
    from app.cv.detector import FaceDetector

    detector = FaceDetector()
    recognizer = FaceRecognizer()

    embeddings: List[np.ndarray] = []
    valid_faces: List[UnknownFace] = []

    for face_record in faces:
        try:
            img = cv2.imread(face_record.image_path)
            if img is None:
                logger.warning("Could not read image: %s", face_record.image_path)
                face_record.cluster_id = uuid.uuid4()  # standalone cluster
                continue

            detected = detector.detect(img, max_faces=1)
            if not detected:
                logger.warning("No face found in: %s", face_record.image_path)
                face_record.cluster_id = uuid.uuid4()
                continue

            embedding = recognizer.get_embedding(detected[0])
            if embedding is None:
                face_record.cluster_id = uuid.uuid4()
                continue

            embeddings.append(embedding)
            valid_faces.append(face_record)

        except Exception as e:
            logger.warning("Error processing face %s: %s", face_record.id, e)
            face_record.cluster_id = uuid.uuid4()

    if len(embeddings) < 2:
        for vf in valid_faces:
            vf.cluster_id = uuid.uuid4()
        await db.flush()
        return len(faces)

    # Normalize embeddings
    X = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    X = X / np.maximum(norms, 1e-6)

    # DBSCAN clustering with cosine distance
    clustering = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="cosine",
    ).fit(X)

    labels = clustering.labels_
    n_clusters = len(set(labels) - {-1})

    logger.info(
        "DBSCAN result: %d clusters, %d noise points",
        n_clusters,
        (labels == -1).sum(),
    )

    # Map label → UUID cluster_id
    label_to_uuid: dict[int, uuid.UUID] = {}
    for label in set(labels):
        label_to_uuid[label] = uuid.uuid4()

    # Assign cluster_id
    for face_record, label in zip(valid_faces, labels):
        face_record.cluster_id = label_to_uuid[int(label)]

    await db.flush()
    return n_clusters
