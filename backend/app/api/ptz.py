"""PTZ Camera API — Control endpoints + MJPEG live stream."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid as _uuid_mod
from typing import AsyncGenerator, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.auth import get_current_user, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Camera CRUD — Multi-camera management
# ---------------------------------------------------------------------------

class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    type: str = "fixed"  # "ptz" | "fixed"
    onvif_host: Optional[str] = None
    onvif_port: Optional[int] = 80
    onvif_user: Optional[str] = None
    onvif_password: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    type: Optional[str] = None
    onvif_host: Optional[str] = None
    onvif_port: Optional[int] = None
    onvif_user: Optional[str] = None
    onvif_password: Optional[str] = None
    is_active: Optional[bool] = None


class CameraOut(BaseModel):
    id: str
    name: str
    rtsp_url: str
    type: str
    onvif_host: Optional[str] = None
    onvif_port: Optional[int] = None
    is_active: bool
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/cameras", response_model=CameraOut, status_code=201)
async def create_camera(
    body: CameraCreate,
    _user: User = Depends(require_admin),
):
    """Add a new camera to the system."""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.camera import Camera

    async with async_session_factory() as db:
        cam = Camera(
            name=body.name,
            rtsp_url=body.rtsp_url,
            type=body.type,
            onvif_host=body.onvif_host,
            onvif_port=body.onvif_port,
            onvif_user=body.onvif_user,
            onvif_password=body.onvif_password,
            is_active=True,
        )
        db.add(cam)
        await db.commit()
        await db.refresh(cam)
        return CameraOut(
            id=str(cam.id),
            name=cam.name,
            rtsp_url=cam.rtsp_url,
            type=cam.type,
            onvif_host=cam.onvif_host,
            onvif_port=cam.onvif_port,
            is_active=cam.is_active,
            created_at=cam.created_at.isoformat() if cam.created_at else None,
        )


@router.get("/cameras", response_model=List[CameraOut])
async def list_cameras(_user: User = Depends(get_current_user)):
    """List all cameras."""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.camera import Camera

    async with async_session_factory() as db:
        r = await db.execute(select(Camera).order_by(Camera.created_at))
        cams = r.scalars().all()
        return [
            CameraOut(
                id=str(c.id),
                name=c.name,
                rtsp_url=c.rtsp_url,
                type=c.type,
                onvif_host=c.onvif_host,
                onvif_port=c.onvif_port,
                is_active=c.is_active,
                created_at=c.created_at.isoformat() if c.created_at else None,
            )
            for c in cams
        ]


@router.put("/cameras/{camera_id}", response_model=CameraOut)
async def update_camera(
    camera_id: str,
    body: CameraUpdate,
    _user: User = Depends(require_admin),
):
    """Update a camera's configuration."""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.camera import Camera
    from app.ptz.controller import CameraManager
    import uuid

    async with async_session_factory() as db:
        r = await db.execute(select(Camera).where(Camera.id == uuid.UUID(camera_id)))
        cam = r.scalar_one_or_none()
        if not cam:
            raise HTTPException(status_code=404, detail="Camera not found")

        for field, val in body.model_dump(exclude_unset=True).items():
            setattr(cam, field, val)
        await db.commit()
        await db.refresh(cam)

        # Restart controller if RTSP URL changed
        if body.rtsp_url is not None:
            CameraManager.remove_camera(camera_id)

        return CameraOut(
            id=str(cam.id),
            name=cam.name,
            rtsp_url=cam.rtsp_url,
            type=cam.type,
            onvif_host=cam.onvif_host,
            onvif_port=cam.onvif_port,
            is_active=cam.is_active,
            created_at=cam.created_at.isoformat() if cam.created_at else None,
        )


@router.delete("/cameras/{camera_id}")
async def delete_camera(
    camera_id: str,
    _user: User = Depends(require_admin),
):
    """Delete a camera."""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.camera import Camera
    from app.ptz.controller import CameraManager
    import uuid

    async with async_session_factory() as db:
        r = await db.execute(select(Camera).where(Camera.id == uuid.UUID(camera_id)))
        cam = r.scalar_one_or_none()
        if not cam:
            raise HTTPException(status_code=404, detail="Camera not found")
        await db.delete(cam)
        await db.commit()

    CameraManager.remove_camera(camera_id)
    return {"status": "deleted", "id": camera_id}


@router.get("/cameras/{camera_id}/status")
async def get_camera_status(
    camera_id: str,
    _user: User = Depends(get_current_user),
):
    """Check if a camera's stream is alive."""
    from app.ptz.controller import CameraManager
    ctrl = CameraManager.get_camera(camera_id)
    if ctrl is None:
        return {"camera_id": camera_id, "streaming": False, "reason": "not_started"}
    try:
        with ctrl._frame_lock:
            has_frame = ctrl._latest_frame is not None
        return {"camera_id": camera_id, "streaming": has_frame}
    except Exception:
        return {"camera_id": camera_id, "streaming": False}


# ---------------------------------------------------------------------------
# Per-camera WebSocket stream
# ---------------------------------------------------------------------------

from fastapi import WebSocket, WebSocketDisconnect
import base64
from concurrent.futures import ThreadPoolExecutor

_cam_frame_executor = ThreadPoolExecutor(max_workers=8)


async def _ensure_camera_ctrl(camera_id: str):
    """Ensure a CameraManager controller exists for camera_id (lazy-load from DB)."""
    from app.ptz.controller import CameraManager
    ctrl = CameraManager.get_camera(camera_id)
    if ctrl is not None:
        return ctrl

    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.camera import Camera
    import uuid

    async with async_session_factory() as db:
        r = await db.execute(select(Camera).where(Camera.id == uuid.UUID(camera_id)))
        cam = r.scalar_one_or_none()

    if cam is None:
        return None

    return CameraManager.add_camera(
        camera_id=camera_id,
        rtsp_url=cam.rtsp_url,
        onvif_host=cam.onvif_host,
        onvif_port=cam.onvif_port,
        onvif_user=cam.onvif_user,
        onvif_password=cam.onvif_password,
    )


def _encode_camera_jpeg(camera_id: str) -> bytes | None:
    """Encode latest frame as JPEG (runs in thread pool)."""
    try:
        from app.ptz.controller import CameraManager
        ctrl = CameraManager.get_camera(camera_id)
        if ctrl is None:
            return None
        return ctrl.capture_frame_jpeg(quality=60)
    except Exception as e:
        logger.debug("Camera %s frame encode failed: %s", camera_id, e)
        return None


@router.websocket("/cameras/{camera_id}/ws")
async def ws_camera_stream(ws: WebSocket, camera_id: str):
    """Per-camera WebSocket stream. Sends JPEG frames at up to 30 FPS."""
    await ws.accept()
    logger.info("WebSocket camera %s client connected", camera_id)

    # Ensure camera controller is started
    ctrl = await _ensure_camera_ctrl(camera_id)
    if ctrl is None:
        await ws.close(code=4004, reason="Camera not found")
        return

    fps = 30
    interval = 1.0 / fps
    loop = asyncio.get_event_loop()

    try:
        while True:
            t0 = time.monotonic()

            # JPEG encode in thread pool (cv2.imencode is CPU-bound)
            jpeg = await loop.run_in_executor(
                _cam_frame_executor, _encode_camera_jpeg, camera_id
            )
            if jpeg is not None:
                # Send binary instead of base64 text — ~33% smaller payload
                await ws.send_bytes(jpeg)

            # Adaptive sleep: subtract encode+send time to maintain target FPS
            elapsed = time.monotonic() - t0
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
    except WebSocketDisconnect:
        logger.info("WebSocket camera %s client disconnected", camera_id)
    except Exception as e:
        logger.warning("WebSocket camera %s stream error: %s", camera_id, e)


class PresetInfo(BaseModel):
    token: str
    name: str
    pan: Optional[float] = None
    tilt: Optional[float] = None
    zoom: Optional[float] = None


class MoveRequest(BaseModel):
    preset_token: str


class PTZStatus(BaseModel):
    connected: bool
    current_preset: Optional[str] = None
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 1.0


@router.get("/status", response_model=PTZStatus)
async def get_ptz_status(_user: User = Depends(get_current_user)):
    """Get current PTZ camera status."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        status = ptz.get_status()
        return PTZStatus(
            connected=True,
            pan=status.get("pan", 0.0),
            tilt=status.get("tilt", 0.0),
            zoom=status.get("zoom", 1.0),
        )
    except Exception as e:
        return PTZStatus(connected=False)


@router.get("/presets", response_model=List[PresetInfo])
async def list_presets(_user: User = Depends(get_current_user)):
    """List all configured PTZ presets."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        presets = ptz.get_presets()
        return [
            PresetInfo(token=p["token"], name=p.get("name", f"Preset {p['token']}"))
            for p in presets
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera not available: {e}")


@router.post("/move")
async def move_to_preset(
    body: MoveRequest,
    _user: User = Depends(require_admin),
):
    """Move camera to a preset position."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.move_to_preset(body.preset_token)
        return {"status": "ok", "preset": body.preset_token}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera error: {e}")


class ContinuousMoveRequest(BaseModel):
    pan: float = 0.0   # -1.0 (left) to 1.0 (right)
    tilt: float = 0.0  # -1.0 (down) to 1.0 (up)
    zoom: float = 0.0  # -1.0 (wide) to 1.0 (tele)


@router.post("/continuous-move")
async def continuous_move(
    body: ContinuousMoveRequest,
    _user: User = Depends(get_current_user),
):
    """Start continuous PTZ movement."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.continuous_move(body.pan, body.tilt, body.zoom)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera error: {e}")


@router.post("/stop")
async def stop_ptz(_user: User = Depends(get_current_user)):
    """Stop all PTZ movement."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.stop_move()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera error: {e}")


# ---------------------------------------------------------------------------
# Focus Control
# ---------------------------------------------------------------------------

@router.post("/focus-in")
async def focus_in(_user: User = Depends(get_current_user)):
    """Start continuous focus near (focus in)."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.focus_move(-0.5)  # negative = near/in
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Focus error: {e}")


@router.post("/focus-out")
async def focus_out(_user: User = Depends(get_current_user)):
    """Start continuous focus far (focus out)."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.focus_move(0.5)  # positive = far/out
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Focus error: {e}")


@router.post("/focus-stop")
async def focus_stop(_user: User = Depends(get_current_user)):
    """Stop continuous focus movement."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.focus_stop()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Focus error: {e}")


@router.post("/focus-auto")
async def focus_auto(_user: User = Depends(get_current_user)):
    """Set focus to auto mode."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        ptz.focus_auto()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Focus error: {e}")


@router.get("/all-presets")
async def get_all_presets(_user: User = Depends(get_current_user)):
    """Get ALL presets from camera (unfiltered)."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        return ptz.get_all_presets()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera error: {e}")


@router.post("/capture")
async def capture_frame(_user: User = Depends(require_admin)):
    """Capture a single frame from camera (for testing/preview)."""
    try:
        from app.ptz.controller import PTZController

        import os
        import uuid
        from app.config import get_settings

        settings = get_settings()
        ptz = PTZController.get_instance()
        frame = ptz.capture_frame()

        # Save frame
        os.makedirs(os.path.join(settings.MEDIA_ROOT, "captures"), exist_ok=True)
        filename = f"capture_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(settings.MEDIA_ROOT, "captures", filename)
        cv2.imwrite(filepath, frame)

        return {"status": "ok", "image_path": filepath}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera error: {e}")


# ---------------------------------------------------------------------------
# WebSocket Live Stream
# ---------------------------------------------------------------------------

# (WebSocket, base64, ThreadPoolExecutor already imported above)


def _grab_frame() -> bytes | None:
    """Blocking: grab a JPEG frame from the PTZ camera (runs in thread pool)."""
    try:
        from app.ptz.controller import PTZController
        ptz = PTZController.get_instance()
        return ptz.capture_frame_jpeg(quality=60)
    except Exception as e:
        logger.debug("Frame grab failed: %s", e)
        return None


@router.websocket("/ws")
async def ws_video_stream(ws: WebSocket):
    """
    WebSocket live stream from PTZ camera.
    Sends JPEG frames as binary messages at up to 30 FPS.
    """
    await ws.accept()
    logger.info("WebSocket video client connected")

    fps = 30
    interval = 1.0 / fps
    loop = asyncio.get_event_loop()

    try:
        while True:
            t0 = time.monotonic()

            jpeg = await loop.run_in_executor(_cam_frame_executor, _grab_frame)
            if jpeg is not None:
                await ws.send_bytes(jpeg)

            elapsed = time.monotonic() - t0
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
    except WebSocketDisconnect:
        logger.info("WebSocket video client disconnected")
    except Exception as e:
        logger.warning("WebSocket stream error: %s", e)


# ---------------------------------------------------------------------------
# Bulk Enrollment from local folder
# ---------------------------------------------------------------------------

class EnrollFolderRequest(BaseModel):
    folder_path: str  # e.g. "/media/edabk/edabk1_500gb/Bocchi/Thesis/408"
    class_name: str = "408"


class EnrollFolderResult(BaseModel):
    class_name: str
    students_created: int = 0
    embeddings_created: int = 0
    errors: list = []


@router.post("/enroll-folder", response_model=EnrollFolderResult)
async def enroll_from_folder(
    body: EnrollFolderRequest,
    _user: User = Depends(get_current_user),
):
    """
    Bulk enroll students from a local folder.
    Folder structure: root/<StudentName>/<image.jpg|png|bmp|webp>
    Creates class, students, and face embeddings.
    """
    import os
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.database import async_session_factory
    from app.models.class_ import Class
    from app.models.student import Student
    from app.models.face_embedding import FaceEmbedding

    folder = body.folder_path
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")

    result = EnrollFolderResult(class_name=body.class_name)

    # Lazy-load CV pipeline (InsightFace buffalo_l)
    from app.cv.pipeline import CVPipeline
    pipeline = CVPipeline.get_instance()

    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}

    async with async_session_factory() as db:
        # 1. Create or get class
        r = await db.execute(select(Class).where(Class.name == body.class_name))
        cls = r.scalar_one_or_none()
        if not cls:
            cls = Class(name=body.class_name, subject="General")
            db.add(cls)
            await db.flush()
            await db.refresh(cls)

        # 2. Iterate subfolders
        for student_name in sorted(os.listdir(folder)):
            student_dir = os.path.join(folder, student_name)
            if not os.path.isdir(student_dir):
                continue

            student_code = f"{body.class_name}_{student_name}"

            # Create or get student
            r = await db.execute(
                select(Student).where(Student.student_code == student_code)
            )
            student = r.scalar_one_or_none()
            if not student:
                student = Student(
                    student_code=student_code,
                    full_name=student_name,
                    class_id=cls.id,
                )
                db.add(student)
                await db.flush()
                await db.refresh(student)
                result.students_created += 1

            # 3. Process images
            for fname in os.listdir(student_dir):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in IMAGE_EXTS:
                    continue

                img_path = os.path.join(student_dir, fname)
                try:
                    frame = cv2.imread(img_path)
                    if frame is None:
                        result.errors.append(f"{student_name}/{fname}: cannot read")
                        continue

                    faces = pipeline.detect_faces(frame)
                    if len(faces) == 0:
                        result.errors.append(f"{student_name}/{fname}: no face")
                        continue

                    # Use the largest face
                    face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    embedding = pipeline.compute_embedding(frame, face)
                    if embedding is None:
                        result.errors.append(f"{student_name}/{fname}: no embedding")
                        continue

                    db.add(FaceEmbedding(
                        student_id=student.id,
                        embedding=embedding.tolist(),
                        image_path=img_path,
                    ))
                    result.embeddings_created += 1

                except Exception as e:
                    result.errors.append(f"{student_name}/{fname}: {e}")

        await db.commit()

    logger.info(
        "Enrollment done: %d students, %d embeddings, %d errors",
        result.students_created, result.embeddings_created, len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Upload-based bulk enrollment (ZIP or images)
# ---------------------------------------------------------------------------

from fastapi import UploadFile, File, Form

@router.post("/enroll-upload")
async def enroll_from_upload(
    class_name: str = Form("408"),
    files: List[UploadFile] = File(..., description="Face images or a ZIP file"),
    _user: User = Depends(get_current_user),
):
    """
    Upload face images for enrollment.
    - Single images: filename = StudentName.jpg → creates student & embedding
    - ZIP: contains folders like StudentName/image.jpg
    Supports jpg, jpeg, png, bmp, webp, tiff.
    """
    import os
    import tempfile
    import zipfile
    import shutil
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.models.class_ import Class
    from app.models.student import Student
    from app.models.face_embedding import FaceEmbedding
    from app.cv.pipeline import CVPipeline

    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
    pipeline = CVPipeline.get_instance()
    results = {"students_created": 0, "embeddings_created": 0, "errors": []}

    async with async_session_factory() as db:
        # Get or create class
        r = await db.execute(select(Class).where(Class.name == class_name))
        cls = r.scalar_one_or_none()
        if not cls:
            cls = Class(name=class_name, subject="General")
            db.add(cls)
            await db.flush()
            await db.refresh(cls)

        tmpdir = tempfile.mkdtemp()
        try:
            for f in files:
                fname = f.filename or "unknown"
                ext = os.path.splitext(fname)[1].lower()
                content = await f.read()

                if ext == ".zip":
                    # Extract ZIP to tmpdir
                    zip_path = os.path.join(tmpdir, fname)
                    with open(zip_path, "wb") as zf:
                        zf.write(content)
                    with zipfile.ZipFile(zip_path) as z:
                        z.extractall(tmpdir)
                elif ext in IMAGE_EXTS:
                    # Single image → use filename stem as student name
                    student_name = os.path.splitext(fname)[0]
                    sdir = os.path.join(tmpdir, student_name)
                    os.makedirs(sdir, exist_ok=True)
                    with open(os.path.join(sdir, fname), "wb") as wf:
                        wf.write(content)

            # Now process all folders in tmpdir (same as enroll-folder)
            for student_name in sorted(os.listdir(tmpdir)):
                sdir = os.path.join(tmpdir, student_name)
                if not os.path.isdir(sdir):
                    continue

                student_code = f"{class_name}_{student_name}"
                r = await db.execute(
                    select(Student).where(Student.student_code == student_code)
                )
                student = r.scalar_one_or_none()
                if not student:
                    student = Student(
                        student_code=student_code,
                        full_name=student_name,
                        class_id=cls.id,
                    )
                    db.add(student)
                    await db.flush()
                    await db.refresh(student)
                    results["students_created"] += 1

                for img_name in os.listdir(sdir):
                    iext = os.path.splitext(img_name)[1].lower()
                    if iext not in IMAGE_EXTS:
                        continue
                    img_path = os.path.join(sdir, img_name)
                    try:
                        frame = cv2.imread(img_path)
                        if frame is None:
                            continue
                        faces = pipeline.detect_faces(frame)
                        if not faces:
                            results["errors"].append(f"{student_name}/{img_name}: no face")
                            continue
                        face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
                        emb = pipeline.compute_embedding(frame, face)
                        if emb is None:
                            continue
                        db.add(FaceEmbedding(
                            student_id=student.id,
                            embedding=emb.tolist(),
                            image_path=img_path,
                        ))
                        results["embeddings_created"] += 1
                    except Exception as e:
                        results["errors"].append(f"{student_name}/{img_name}: {e}")

            await db.commit()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return results


# ---------------------------------------------------------------------------
# Enrollment Stats — total students + embeddings in DB
# ---------------------------------------------------------------------------

@router.get("/enrollment-stats")
async def get_enrollment_stats(_user: User = Depends(get_current_user)):
    """Return total students and face embeddings in the database."""
    from sqlalchemy import select, func
    from app.database import async_session_factory
    from app.models.student import Student
    from app.models.face_embedding import FaceEmbedding

    async with async_session_factory() as db:
        r_students = await db.execute(select(func.count(Student.id)))
        r_embeddings = await db.execute(select(func.count(FaceEmbedding.id)))
        return {
            "total_students": r_students.scalar() or 0,
            "total_embeddings": r_embeddings.scalar() or 0,
        }



_attendance_active = False
_attendance_results: list = []
_attendance_lock = __import__("threading").Lock()


@router.post("/start-attendance")
async def start_attendance(_user: User = Depends(get_current_user)):
    """Start live attendance recognition from PTZ camera."""
    global _attendance_active
    if _attendance_active:
        return {"status": "already_running"}

    _attendance_active = True
    with _attendance_lock:
        _attendance_results.clear()

    import threading
    threading.Thread(target=_attendance_loop, daemon=True).start()
    return {"status": "started"}


@router.post("/stop-attendance")
async def stop_attendance(_user: User = Depends(get_current_user)):
    """Stop live attendance recognition."""
    global _attendance_active
    _attendance_active = False
    return {"status": "stopped"}


@router.get("/attendance-results")
async def get_attendance_results(_user: User = Depends(get_current_user)):
    """Get current attendance results (recognized students)."""
    with _attendance_lock:
        return {"active": _attendance_active, "recognized": list(_attendance_results)}


def _attendance_loop():
    """Background thread: capture frames + run recognition."""
    global _attendance_active
    import time as _time
    import traceback
    from datetime import date, time as dt_time, datetime, timezone

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        from app.ptz.controller import PTZController
        from app.cv.pipeline import CVPipeline
        from app.config import get_settings
        from app.models.session import Session
        from app.models.class_ import Class
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        settings = get_settings()

        # Create a DEDICATED engine for this thread's event loop
        # (asyncpg connections are bound to the loop that created them)
        bg_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=2,
            pool_pre_ping=True,
        )
        bg_session_factory = async_sessionmaker(
            bg_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        ptz = PTZController.get_instance()
        pipeline = CVPipeline.get_instance()

        recognized_codes: set = set()

        async def _run():
            global _attendance_active

            async with bg_session_factory() as db:
                # Get first class
                r = await db.execute(select(Class).limit(1))
                cls = r.scalar_one_or_none()
                class_id = cls.id if cls else None

                now = datetime.now(timezone.utc)

                # Reuse existing session for today, or create new
                r = await db.execute(
                    select(Session).where(
                        Session.class_id == class_id,
                        Session.session_date == now.date(),
                    )
                )
                session = r.scalar_one_or_none()
                if session:
                    session.status = "scanning"
                    await db.flush()
                else:
                    session = Session(
                        class_id=class_id,
                        session_date=now.date(),
                        start_time=now.time(),
                        end_time=dt_time(23, 59, 59),
                        enrolled_count=0,
                        status="scanning",
                    )
                    db.add(session)
                    await db.flush()
                session_id = session.id

                logger.info("Attendance started, session=%s", session_id)
                print(f"[ATTENDANCE] Started, session={session_id}")

                while _attendance_active:
                    try:
                        frame = ptz.capture_frame()
                        result = await pipeline.process_frame(
                            frame=frame,
                            session_id=session_id,
                            db=db,
                            class_id=class_id,
                            skip_dedup=True,
                        )
                        await db.commit()

                        # Collect newly recognized
                        for fr in result.recognized:
                            if fr.match and fr.match.student_code not in recognized_codes:
                                recognized_codes.add(fr.match.student_code)
                                entry = {
                                    "student_code": fr.match.student_code,
                                    "full_name": fr.match.full_name,
                                    "score": round(fr.match.score, 3),
                                    "time": _time.strftime("%H:%M:%S"),
                                }
                                with _attendance_lock:
                                    _attendance_results.append(entry)
                                logger.info("ATTENDANCE: %s (%s) score=%.3f",
                                           fr.match.full_name, fr.match.student_code, fr.match.score)
                                print(f"[ATTENDANCE] Recognized: {fr.match.full_name} ({fr.match.student_code}) score={fr.match.score:.3f}")

                        if result.total_faces > 0:
                            print(f"[ATTENDANCE] Frame: {result.total_faces} faces, "
                                  f"{len(result.recognized)} recognized, "
                                  f"{len(result.unrecognized)} unknown, "
                                  f"{len(result.spoofs)} spoofs")

                    except Exception as e:
                        logger.error("Attendance frame error: %s", e)
                        print(f"[ATTENDANCE] Frame error: {e}")
                        traceback.print_exc()

                    await asyncio.sleep(0.5)  # ~2 FPS for recognition

                session.status = "done"
                await db.commit()
                logger.info("Attendance stopped, session=%s", session_id)
                print(f"[ATTENDANCE] Stopped, session={session_id}")

            # Clean up dedicated engine
            await bg_engine.dispose()

        loop.run_until_complete(_run())
    except Exception as e:
        logger.error("Attendance loop crashed: %s", e)
        print(f"[ATTENDANCE] CRASH: {e}")
        traceback.print_exc()
    finally:
        _attendance_active = False
        loop.close()


# ---------------------------------------------------------------------------
# Auto-Scan — PTZ preset cycling with face recognition
# ---------------------------------------------------------------------------

import threading as _threading

_scan_active = False
_scan_status: dict = {
    "state": "idle",         # idle | scanning | done
    "current_zone": "",
    "current_sweep": 0,
    "total_sweeps": 0,
    "zones_total": 0,
    "zones_done": 0,
    "frames_processed": 0,
    "recognized_count": 0,
    "coverage_pct": 0.0,
    "recognized": [],        # list of recognized entries
    "error": None,
}
_scan_lock = _threading.Lock()


def _reset_scan_status():
    global _scan_status
    with _scan_lock:
        _scan_status = {
            "state": "idle",
            "current_zone": "",
            "current_sweep": 0,
            "total_sweeps": 0,
            "zones_total": 0,
            "zones_done": 0,
            "frames_processed": 0,
            "recognized_count": 0,
            "coverage_pct": 0.0,
            "recognized": [],
            "error": None,
        }


class AutoScanRequest(BaseModel):
    sweeps: int = 2           # number of cycles through all presets
    dwell_seconds: float = 4.0  # seconds to stay at each preset
    frames_per_zone: int = 6    # frames to capture per zone per sweep
    class_name: Optional[str] = None  # class to scan for (None = first class)
    preset_tokens: Optional[List[str]] = None  # specific presets to use (None = all)


@router.post("/start-auto-scan")
async def start_auto_scan(
    body: AutoScanRequest = AutoScanRequest(),
    _user: User = Depends(get_current_user),
):
    """Start auto-scanning: cycle through PTZ presets and recognize faces."""
    global _scan_active
    if _scan_active:
        return {"status": "already_running"}
    if _attendance_active:
        return {"status": "error", "detail": "Attendance is running, stop it first"}

    _scan_active = True
    _reset_scan_status()

    _threading.Thread(
        target=_auto_scan_loop,
        args=(body.sweeps, body.dwell_seconds, body.frames_per_zone, body.class_name, body.preset_tokens),
        daemon=True,
    ).start()
    return {"status": "started"}


@router.post("/stop-auto-scan")
async def stop_auto_scan(_user: User = Depends(get_current_user)):
    """Stop auto-scanning."""
    global _scan_active
    _scan_active = False
    return {"status": "stopped"}


@router.get("/auto-scan-status")
async def get_auto_scan_status(_user: User = Depends(get_current_user)):
    """Get current auto-scan progress."""
    with _scan_lock:
        return dict(_scan_status)


def _auto_scan_loop(
    sweeps: int,
    dwell_seconds: float,
    frames_per_zone: int,
    class_name: Optional[str],
    preset_tokens: Optional[List[str]] = None,
):
    """Background thread: cycle presets → capture → recognize → track coverage."""
    global _scan_active
    import time as _time
    import traceback
    from datetime import date, time as dt_time, datetime, timezone

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        from app.ptz.controller import PTZController
        from app.cv.pipeline import CVPipeline
        from app.config import get_settings
        from app.models.session import Session
        from app.models.class_ import Class
        from app.models.student import Student
        from sqlalchemy import select, func
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        settings = get_settings()
        bg_engine = create_async_engine(
            settings.DATABASE_URL, echo=False,
            pool_size=5, max_overflow=2, pool_pre_ping=True,
        )
        bg_session_factory = async_sessionmaker(
            bg_engine, class_=AsyncSession, expire_on_commit=False,
        )

        ptz = PTZController.get_instance()
        pipeline = CVPipeline.get_instance()

        async def _run():
            global _scan_active

            async with bg_session_factory() as db:
                # --- Resolve class ---
                if class_name:
                    r = await db.execute(select(Class).where(Class.name == class_name))
                else:
                    r = await db.execute(select(Class).limit(1))
                cls = r.scalar_one_or_none()
                class_id = cls.id if cls else None

                # Count enrolled students
                enrolled_count = 0
                if class_id:
                    r = await db.execute(
                        select(func.count(Student.id)).where(Student.class_id == class_id)
                    )
                    enrolled_count = r.scalar() or 0

                # --- Get presets from ONVIF ---
                # Use get_all_presets (unfiltered) for scanning
                try:
                    all_presets = ptz.get_all_presets()
                except Exception:
                    all_presets = []

                if not all_presets:
                    # Fallback: single zone at current position
                    all_presets = [{"token": "1", "name": "Default"}]
                    logger.warning("No ONVIF presets found, using single zone")

                # Filter by requested preset tokens if specified
                if preset_tokens:
                    preset_list = [p for p in all_presets if p["token"] in preset_tokens]
                    if not preset_list:
                        preset_list = all_presets  # fallback to all
                else:
                    preset_list = all_presets

                zones = preset_list
                zone_count = len(zones)

                with _scan_lock:
                    _scan_status["state"] = "scanning"
                    _scan_status["total_sweeps"] = sweeps
                    _scan_status["zones_total"] = zone_count

                # --- Create/reuse session ---
                now = datetime.now(timezone.utc)
                r = await db.execute(
                    select(Session).where(
                        Session.class_id == class_id,
                        Session.session_date == now.date(),
                    )
                )
                session = r.scalar_one_or_none()
                if session:
                    session.status = "scanning"
                    session.enrolled_count = enrolled_count
                    await db.flush()
                else:
                    session = Session(
                        class_id=class_id,
                        session_date=now.date(),
                        start_time=now.time(),
                        end_time=dt_time(23, 59, 59),
                        enrolled_count=enrolled_count,
                        status="scanning",
                    )
                    db.add(session)
                    await db.flush()
                session_id = session.id

                logger.info(
                    "=== AUTO-SCAN START: session=%s, %d zones × %d sweeps, "
                    "dwell=%.1fs, %d frames/zone, enrolled=%d ===",
                    session_id, zone_count, sweeps, dwell_seconds,
                    frames_per_zone, enrolled_count,
                )
                print(f"[AUTO-SCAN] Starting: {zone_count} zones × {sweeps} sweeps")

                recognized_codes: set = set()
                total_frames = 0

                # --- Main scan loop ---
                for sweep_idx in range(sweeps):
                    if not _scan_active:
                        break

                    with _scan_lock:
                        _scan_status["current_sweep"] = sweep_idx + 1
                        _scan_status["zones_done"] = 0

                    logger.info("=== Sweep %d/%d ===", sweep_idx + 1, sweeps)
                    print(f"[AUTO-SCAN] Sweep {sweep_idx + 1}/{sweeps}")

                    for zone_idx, zone in enumerate(zones):
                        if not _scan_active:
                            break

                        zone_name = zone.get("name", f"Zone {zone_idx + 1}")
                        preset_token = zone.get("token", str(zone_idx + 1))

                        with _scan_lock:
                            _scan_status["current_zone"] = zone_name

                        logger.info("Moving to %s (preset %s)...", zone_name, preset_token)
                        print(f"[AUTO-SCAN] → {zone_name} (preset {preset_token})")

                        # Move PTZ
                        try:
                            ptz.move_to_preset(preset_token)
                        except Exception as e:
                            logger.error("Move to preset %s failed: %s", preset_token, e)
                            continue

                        # Wait for camera to settle + warm-up time
                        _time.sleep(max(1.5, dwell_seconds * 0.4))

                        # Capture frames at this position
                        frame_interval = max(0.3, (dwell_seconds * 0.6) / frames_per_zone)
                        for frame_idx in range(frames_per_zone):
                            if not _scan_active:
                                break

                            try:
                                frame = ptz.capture_frame()
                                result = await pipeline.process_frame(
                                    frame=frame,
                                    session_id=session_id,
                                    db=db,
                                    class_id=class_id,
                                    zone_id=f"zone_{zone_idx}",
                                    skip_dedup=False,
                                )
                                await db.commit()
                                total_frames += 1

                                # Track recognized
                                for fr in result.recognized:
                                    if fr.match and fr.match.student_code not in recognized_codes:
                                        recognized_codes.add(fr.match.student_code)
                                        entry = {
                                            "student_code": fr.match.student_code,
                                            "full_name": fr.match.full_name,
                                            "score": round(fr.match.score, 3),
                                            "time": _time.strftime("%H:%M:%S"),
                                            "zone": zone_name,
                                        }
                                        with _scan_lock:
                                            _scan_status["recognized"].append(entry)
                                            _scan_status["recognized_count"] = len(recognized_codes)
                                            if enrolled_count > 0:
                                                _scan_status["coverage_pct"] = round(
                                                    len(recognized_codes) * 100.0 / enrolled_count, 1
                                                )

                                        print(f"[AUTO-SCAN] ✓ {fr.match.full_name} "
                                              f"({fr.match.student_code}) score={fr.match.score:.3f} "
                                              f"@ {zone_name}")

                                with _scan_lock:
                                    _scan_status["frames_processed"] = total_frames

                            except Exception as e:
                                logger.error("Auto-scan frame error: %s", e)

                            _time.sleep(frame_interval)

                        with _scan_lock:
                            _scan_status["zones_done"] = zone_idx + 1

                # --- Done ---
                session.status = "done"
                await db.commit()

                coverage = round(
                    len(recognized_codes) * 100.0 / enrolled_count, 1
                ) if enrolled_count > 0 else 0.0

                with _scan_lock:
                    _scan_status["state"] = "done"
                    _scan_status["coverage_pct"] = coverage

                logger.info(
                    "=== AUTO-SCAN COMPLETE: %d recognized / %d enrolled (%.1f%%), "
                    "%d frames processed ===",
                    len(recognized_codes), enrolled_count, coverage, total_frames,
                )
                print(f"[AUTO-SCAN] Done: {len(recognized_codes)}/{enrolled_count} "
                      f"({coverage}%), {total_frames} frames")

            await bg_engine.dispose()

        loop.run_until_complete(_run())
    except Exception as e:
        logger.error("Auto-scan loop crashed: %s", e)
        print(f"[AUTO-SCAN] CRASH: {e}")
        import traceback
        traceback.print_exc()
        with _scan_lock:
            _scan_status["state"] = "idle"
            _scan_status["error"] = str(e)
    finally:
        _scan_active = False
        loop.close()
