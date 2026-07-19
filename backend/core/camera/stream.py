"""
GStreamer pipeline building and RTSP camera capture.

Consolidated from duplicated code across 7+ scripts.
"""

from __future__ import annotations

import subprocess
import time

import cv2

from src.backend.core.config import (
    GST_LATENCY,
    GST_MAX_BUFFERS,
    OPEN_VALIDATE_SECONDS,
    OPEN_VALIDATE_READS,
)
from src.backend.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# GStreamer helpers
# ---------------------------------------------------------------------------

def gst_element_exists(name: str) -> bool:
    """Check if a GStreamer element plugin is available."""
    try:
        r = subprocess.run(
            ["gst-inspect-1.0", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2.0,
        )
        return r.returncode == 0
    except Exception:
        return False


def select_decoder() -> str:
    """nvv4l2decoder only — full DPB for maximum decode quality."""
    if not gst_element_exists("nvv4l2decoder"):
        raise RuntimeError(
            "nvv4l2decoder not found! Hardware decoder is required. "
            "Ensure you are running on Jetson with GStreamer nvidia plugins."
        )
    return (
        "nvv4l2decoder "
        "discard-corrupted-frames=true "
        "automatic-request-sync-points=true "
        "max-errors=-1 "
        # disable-dpb=false → giữ full reference frames → chất lượng nét nhất
        "disable-dpb=false "
        # Tăng output surfaces để decoder có nhiều buffer hơn, giảm artifact
        "num-extra-surfaces=4"
    )


def build_gstreamer_pipeline(rtsp_url: str) -> str:
    """
    Build GStreamer pipeline: RTSP → nvv4l2decoder → BGR appsink.

    Tối ưu cho nét nhất:
    - TCP only (không mất gói như UDP)
    - disable-dpb=false (giữ full reference frames)
    - interpolation-method=5 (Lanczos — nét nhất khi scale)
    - Không drop frame ở decoder queue, chỉ drop ở appsink
    """
    decoder = select_decoder()

    rtspsrc_opts = (
        f"latency={GST_LATENCY} "
        f"buffer-mode=auto "
        f"drop-on-latency=false "
        f"do-retransmission=true "
        f"do-rtsp-keep-alive=true "
        f"ntp-sync=false "
        f"retry=5"
    )

    src = (
        f'rtspsrc location="{rtsp_url}" protocols=tcp '
        f"tcp-timeout=20000000 {rtspsrc_opts} "
    )

    # nvvidconv interpolation-method:
    #   1 = Nearest, 2 = Bilinear, 3 = 5-tap, 4 = 10-tap, 5 = Smart/Lanczos
    #   5 = nét nhất (Lanczos-like adaptive filtering)
    convert_chain = (
        "! nvvidconv interpolation-method=5 "
        "! video/x-raw,format=BGRx "
        "! videoconvert n-threads=4 ! video/x-raw,format=BGR "
    )

    return (
        f"{src} "
        f"! application/x-rtp,media=video,encoding-name=H264 "
        f"! rtph264depay ! h264parse config-interval=-1 disable-passthrough=true "
        f"! video/x-h264,alignment=au,parsed=true "
        f"! {decoder} "
        f"! queue max-size-buffers=4 max-size-bytes=0 max-size-time=0 "
        f"leaky=downstream silent=true "
        f"{convert_chain}"
        f"! appsink max-buffers=2 drop=true sync=false wait-on-eos=false"
    )


# ---------------------------------------------------------------------------
# Capture open / validate
# ---------------------------------------------------------------------------

# Track all open captures for cleanup on exit
_all_captures: list[cv2.VideoCapture] = []
_cleanup_registered = False


def _atexit_cleanup() -> None:
    """Release all tracked captures on process exit."""
    for cap in _all_captures:
        try:
            if cap.isOpened():
                cap.release()
        except Exception:
            pass
    _all_captures.clear()


def _register_cleanup() -> None:
    global _cleanup_registered
    if not _cleanup_registered:
        import atexit
        atexit.register(_atexit_cleanup)
        _cleanup_registered = True


def build_software_pipeline(rtsp_url: str) -> str:
    """Build GStreamer pipeline with software decoder (avdec_h264) — fallback."""
    rtspsrc_opts = (
        f"latency={GST_LATENCY} "
        f"buffer-mode=auto "
        f"drop-on-latency=true "
        f"do-rtsp-keep-alive=true "
        f"ntp-sync=false "
        f"retry=5"
    )
    return (
        f'rtspsrc location="{rtsp_url}" protocols=tcp '
        f"tcp-timeout=20000000 {rtspsrc_opts} "
        f"! application/x-rtp,media=video,encoding-name=H264 "
        f"! rtph264depay ! h264parse config-interval=-1 "
        f"! avdec_h264 "
        f"! videoconvert n-threads=4 ! video/x-raw,format=BGR "
        f"! appsink max-buffers=2 drop=true sync=false wait-on-eos=false"
    )


def validate_capture(cap: cv2.VideoCapture) -> tuple[bool, object | None]:
    """Try reading frames until one succeeds or timeout."""
    deadline = time.time() + OPEN_VALIDATE_SECONDS
    attempts = 0
    while time.time() < deadline and attempts < OPEN_VALIDATE_READS:
        ok, frame = cap.read()
        attempts += 1
        if ok and frame is not None and frame.size > 0:
            return True, frame
        time.sleep(0.05)
    return False, None


def open_capture(
    rtsp_url: str,
    use_hwaccel: bool = True,
    debug_label: str | None = None,
) -> tuple[cv2.VideoCapture | None, str, object | None]:
    """
    Open RTSP stream — try nvv4l2decoder first, fallback to avdec_h264 (SW).

    Returns (cap, mode_string, first_frame) or (None, "", None) on failure.
    """
    _register_cleanup()

    # ── Try HW decode first when requested ──
    if use_hwaccel:
        try:
            pipeline = build_gstreamer_pipeline(rtsp_url)
            if debug_label:
                logger.info("%s: opening with nvv4l2decoder (tcp|h264|hw)", debug_label)

            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                valid, first_frame = validate_capture(cap)
                if valid:
                    _all_captures.append(cap)
                    if debug_label:
                        logger.info("%s: OK (tcp|h264|hw|nvv4l2)", debug_label)
                    return cap, "tcp|h264|hw|nvv4l2", first_frame
            cap.release()
        except Exception as e:
            if debug_label:
                logger.warning("%s: HW decoder error: %s", debug_label, e)

        # ── Fallback to software decode ──
        if debug_label:
            logger.warning("%s: HW decoder failed — falling back to avdec_h264 (SW)", debug_label)
    elif debug_label:
        logger.info("%s: opening with avdec_h264 (tcp|h264|sw)", debug_label)
    try:
        sw_pipeline = build_software_pipeline(rtsp_url)
        cap = cv2.VideoCapture(sw_pipeline, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            valid, first_frame = validate_capture(cap)
            if valid:
                _all_captures.append(cap)
                if debug_label:
                    logger.info("%s: OK (tcp|h264|sw|avdec)", debug_label)
                return cap, "tcp|h264|sw|avdec", first_frame
        cap.release()
    except Exception as e:
        if debug_label:
            logger.warning("%s: SW decoder also failed: %s", debug_label, e)

    if debug_label:
        logger.error("%s: FAILED to open stream (both HW and SW)", debug_label)
    return None, "", None
