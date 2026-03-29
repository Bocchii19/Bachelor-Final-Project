"""PTZ Camera API — Control endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import get_current_user, require_admin
from app.models.user import User

router = APIRouter()


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


@router.post("/capture")
async def capture_frame(_user: User = Depends(require_admin)):
    """Capture a single frame from camera (for testing/preview)."""
    try:
        from app.ptz.controller import PTZController

        import cv2
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
