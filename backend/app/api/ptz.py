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


def _grab_camera_frame(camera_id: str) -> bytes | None:
    """Grab a JPEG frame from a managed camera (runs in thread pool)."""
    try:
        from app.ptz.controller import CameraManager
        from app.database import async_session_factory
        ctrl = CameraManager.get_camera(camera_id)
        if ctrl is None:
            # Lazy-start: read DB and add to CameraManager
            import asyncio
            from sqlalchemy import select
            from app.models.camera import Camera
            import uuid

            async def _load():
                async with async_session_factory() as db:
                    r = await db.execute(select(Camera).where(Camera.id == uuid.UUID(camera_id)))
                    return r.scalar_one_or_none()

            loop = asyncio.new_event_loop()
            try:
                cam = loop.run_until_complete(_load())
            finally:
                loop.close()

            if cam is None:
                return None
            ctrl = CameraManager.add_camera(
                camera_id=camera_id,
                rtsp_url=cam.rtsp_url,
                onvif_host=cam.onvif_host,
                onvif_port=cam.onvif_port,
                onvif_user=cam.onvif_user,
                onvif_password=cam.onvif_password,
            )

        frame = ctrl.capture_frame()
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()
    except Exception as e:
        logger.debug("Camera %s frame grab failed: %s", camera_id, e)
        return None


@router.websocket("/cameras/{camera_id}/ws")
async def ws_camera_stream(ws: WebSocket, camera_id: str):
    """Per-camera WebSocket stream. Sends base64 JPEG frames at ~10 FPS."""
    await ws.accept()
    logger.info("WebSocket camera %s client connected", camera_id)

    fps = 10
    interval = 1.0 / fps
    loop = asyncio.get_event_loop()

    try:
        while True:
            jpeg = await loop.run_in_executor(
                _cam_frame_executor, _grab_camera_frame, camera_id
            )
            if jpeg is not None:
                b64 = base64.b64encode(jpeg).decode("ascii")
                await ws.send_text(b64)
            await asyncio.sleep(interval)
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
        frame = ptz.capture_frame()
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()
    except Exception as e:
        logger.debug("Frame grab failed: %s", e)
        return None


@router.websocket("/ws")
async def ws_video_stream(ws: WebSocket):
    """
    WebSocket live stream from PTZ camera.
    Sends base64 JPEG frames as text messages at ~10 FPS.
    """
    await ws.accept()
    logger.info("WebSocket video client connected")

    fps = 10
    interval = 1.0 / fps
    loop = asyncio.get_event_loop()

    try:
        while True:
            # Run blocking capture in thread pool
            jpeg = await loop.run_in_executor(_cam_frame_executor, _grab_frame)

            if jpeg is not None:
                b64 = base64.b64encode(jpeg).decode("ascii")
                await ws.send_text(b64)

            await asyncio.sleep(interval)
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



