"""
Record 5 RTSP camera streams with OpenCV + GStreamer.

- Read each RTSP stream with `cv2.VideoCapture(..., cv2.CAP_GSTREAMER)`
- One recorder thread per camera to reduce cross-camera blocking
- Save 1-minute MP4 segments from 07:30 to 19:00
- Output layout:
    recordings/
      cam1/
        YYYYMMDD/
          HHMMSS.mp4
"""

import argparse
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, time as dt_time

import cv2

CAMERA_FPS = 30.0
SEGMENT_SECONDS = 60
RECORD_BASE_DIR = "recordings"
WINDOW_START = dt_time(hour=7, minute=30)
WINDOW_END = dt_time(hour=20, minute=0)
GST_LATENCY = 300
GST_MAX_BUFFERS = 3
OPEN_VALIDATE_SECONDS = 5.0
OPEN_VALIDATE_READS = 30
ENABLE_UDP_FALLBACK = False
ENABLE_H265_FALLBACK = False
WRITER_FOURCCS = ("avc1", "H264", "mp4v")
FRAME_QUEUE_SIZE = 1
ENCODER_BITRATE_KBPS = 2048
ENCODER_GOP = int(CAMERA_FPS)
GST_WRITER_QUEUE_BUFFERS = 2

RTSP_URLS = {
    "cam1": "rtsp://admin:Hanet123@10.128.55.225:554/media/live/102",
    "cam2": "rtsp://admin:Hanet123@10.128.55.222:554/media/live/102",
    "cam3": "rtsp://admin:Hanet123@10.128.55.223:554/media/live/102",
    "cam4": "rtsp://admin:Hanet123@10.128.55.237:554/media/live/102",
}


def _gst_element_exists(name: str) -> bool:
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2.0,
        )
        return result.returncode == 0
    except Exception:
        return False


def _select_decoder(codec: str, use_hwaccel: bool) -> str:
    if not use_hwaccel:
        return "avdec_h265 output-corrupt=false" if codec == "h265" else "avdec_h264 output-corrupt=false"

    if _gst_element_exists("nvv4l2decoder"):
        # Jetson/Tegra: NVIDIA V4L2 decoder handles both H264/H265.
        return (
            "nvv4l2decoder discard-corrupted-frames=true "
            "automatic-request-sync-points=true max-errors=-1 disable-dpb=true"
        )
    if codec == "h265" and _gst_element_exists("nvh265dec"):
        return (
            "nvh265dec num-output-surfaces=8 discard-corrupted-frames=true "
            "automatic-request-sync-points=true max-errors=-1"
        )
    if codec == "h264" and _gst_element_exists("nvh264dec"):
        return (
            "nvh264dec num-output-surfaces=8 discard-corrupted-frames=true "
            "automatic-request-sync-points=true max-errors=-1"
        )
    return "avdec_h265 output-corrupt=false" if codec == "h265" else "avdec_h264 output-corrupt=false"


def in_record_time(now: datetime) -> bool:
    return WINDOW_START <= now.time() < WINDOW_END


def build_gstreamer_pipeline(
    rtsp_url: str,
    use_hwaccel: bool = True,
    protocol: str = "tcp",
    codec: str = "h265",
) -> str:
    depay = "rtph265depay" if codec == "h265" else "rtph264depay"
    parser = "h265parse" if codec == "h265" else "h264parse"
    encoding_name = "H265" if codec == "h265" else "H264"
    parsed_caps = (
        "video/x-h265,alignment=au,parsed=true"
        if codec == "h265"
        else "video/x-h264,alignment=au,parsed=true"
    )
    rtspsrc_opts = (
        f"latency={GST_LATENCY} buffer-mode=auto drop-on-latency=false "
        f"do-retransmission=true do-rtsp-keep-alive=true ntp-sync=false retry=5"
    )

    if protocol == "udp":
        src = (
            f'rtspsrc location="{rtsp_url}" protocols=udp '
            f"udp-buffer-size=2097152 timeout=5000000 {rtspsrc_opts} "
        )
    else:
        src = (
            f'rtspsrc location="{rtsp_url}" protocols=tcp '
            f"tcp-timeout=20000000 {rtspsrc_opts} "
        )

    decoder = _select_decoder(codec, use_hwaccel)
    if "nvv4l2decoder" in decoder:
        convert_chain = (
            "! nvvidconv interpolation-method=1 "
            "! video/x-raw,format=BGRx "
            "! videoconvert n-threads=2 ! video/x-raw,format=BGR "
        )
    else:
        convert_chain = "! videoconvert n-threads=2 ! video/x-raw,format=BGR "

    return (
        f"{src} "
        f"! application/x-rtp,media=video,encoding-name={encoding_name} "
        f"! {depay} ! {parser} config-interval=-1 disable-passthrough=true "
        f"! {parsed_caps} ! {decoder} "
        f"! queue max-size-buffers={GST_MAX_BUFFERS} max-size-bytes=0 max-size-time=0 "
        f"leaky=downstream silent=true "
        f"{convert_chain}"
        f"! appsink max-buffers={GST_MAX_BUFFERS} drop=true sync=false wait-on-eos=false"
    )

def _validate_capture(cap: cv2.VideoCapture) -> tuple[bool, object | None]:
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
    use_hwaccel: bool,
    debug_label: str | None = None,
) -> tuple[cv2.VideoCapture | None, str, object | None]:
    attempts: list[tuple[str, str, bool]] = []
    if use_hwaccel:
        attempts.append(("tcp", "h264", True))
        if ENABLE_H265_FALLBACK:
            attempts.append(("tcp", "h265", True))
        if ENABLE_UDP_FALLBACK:
            attempts.append(("udp", "h264", True))
            if ENABLE_H265_FALLBACK:
                attempts.append(("udp", "h265", True))
    attempts.append(("tcp", "h264", False))
    if ENABLE_H265_FALLBACK:
        attempts.append(("tcp", "h265", False))
    if ENABLE_UDP_FALLBACK:
        attempts.append(("udp", "h264", False))
        if ENABLE_H265_FALLBACK:
            attempts.append(("udp", "h265", False))

    for protocol, codec, hw in attempts:
        pipeline = build_gstreamer_pipeline(
            rtsp_url,
            use_hwaccel=hw,
            protocol=protocol,
            codec=codec,
        )
        if debug_label:
            print(f"{debug_label}: try {protocol}|{codec}|{'hw' if hw else 'sw'}")
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            valid, first_frame = _validate_capture(cap)
            if valid:
                mode = f"{protocol}|{codec}|{'hw' if hw else 'sw'}"
                return cap, mode, first_frame
        if debug_label:
            print(f"{debug_label}: failed {protocol}|{codec}|{'hw' if hw else 'sw'}")
        cap.release()
    return None, "", None


def _build_writer_pipeline(output_path: str, size: tuple[int, int], fps: float) -> tuple[str | None, str | None]:
    width, height = size
    fps_num = max(1, int(round(fps * 1000)))
    fps_den = 1000
    if _gst_element_exists("nvh264enc"):
        gst_pipeline = (
            "appsrc is-live=true block=true format=time do-timestamp=true "
            f"! video/x-raw,format=BGR,width={width},height={height},framerate={fps_num}/{fps_den} "
            f"! queue max-size-buffers={GST_WRITER_QUEUE_BUFFERS} max-size-bytes=0 max-size-time=0 leaky=downstream "
            "! videoconvert n-threads=1 ! video/x-raw,format=BGRA "
            f"! nvh264enc rc-mode=cbr bitrate={ENCODER_BITRATE_KBPS} max-bitrate={ENCODER_BITRATE_KBPS} "
            f"gop-size={ENCODER_GOP} bframes=0 preset=p1 tune=ultra-low-latency "
            "repeat-sequence-header=true aud=true zerolatency=true strict-gop=true qos=false "
            "! video/x-h264,profile=main,stream-format=byte-stream "
            "! h264parse config-interval=-1 disable-passthrough=true "
            "! video/x-h264,stream-format=avc,alignment=au "
            "! mp4mux faststart=true "
            f'! filesink location="{output_path}" sync=false async=false'
        )
        return gst_pipeline, "gstreamer|nvh264enc"

    if _gst_element_exists("x264enc"):
        gst_pipeline = (
            "appsrc is-live=true block=true format=time do-timestamp=true "
            f"! video/x-raw,format=BGR,width={width},height={height},framerate={fps_num}/{fps_den} "
            f"! queue max-size-buffers={GST_WRITER_QUEUE_BUFFERS} max-size-bytes=0 max-size-time=0 leaky=downstream "
            "! videoconvert n-threads=1 ! video/x-raw,format=I420 "
            f"! x264enc bitrate={ENCODER_BITRATE_KBPS} speed-preset=veryfast tune=zerolatency "
            f"key-int-max={ENCODER_GOP} bframes=0 aud=true byte-stream=false "
            "! h264parse config-interval=-1 disable-passthrough=true "
            "! video/x-h264,stream-format=avc,alignment=au "
            "! mp4mux faststart=true "
            f'! filesink location="{output_path}" sync=false async=false'
        )
        return gst_pipeline, "gstreamer|x264enc"
    return None, None


def open_video_writer(output_path: str, size: tuple[int, int], fps: float) -> tuple[cv2.VideoWriter, str]:
    gst_pipeline, gst_codec = _build_writer_pipeline(output_path, size, fps)
    if gst_pipeline is not None and gst_codec is not None:
        gst_writer = cv2.VideoWriter(gst_pipeline, cv2.CAP_GSTREAMER, 0, fps, size, True)
        if gst_writer.isOpened():
            return gst_writer, gst_codec
        gst_writer.release()

    last_writer = None
    for fourcc_name in WRITER_FOURCCS:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        writer = cv2.VideoWriter(output_path, fourcc, fps, size)
        if writer.isOpened():
            return writer, fourcc_name
        last_writer = writer
        writer.release()
    if last_writer is not None:
        last_writer.release()
    raise RuntimeError(f"cannot open writer: {output_path}")


class CameraRecorder:
    def __init__(self, camera_id: str, rtsp_url: str, use_hwaccel: bool, base_dir: str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.use_hwaccel = use_hwaccel
        self.base_dir = base_dir
        self.cap: cv2.VideoCapture | None = None
        self.writer: cv2.VideoWriter | None = None
        self.writer_size: tuple[int, int] | None = None
        self.current_segment: datetime | None = None
        self.open_mode: str | None = None
        self.writer_codec: str | None = None
        self.stop_event = threading.Event()
        self.frame_queue: queue.Queue[tuple[datetime, object]] = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True)

    def start(self):
        self.capture_thread.start()
        self.writer_thread.start()

    def _segment_start(self, now: datetime) -> datetime:
        return now.replace(second=0, microsecond=0)

    def _output_path(self, segment_start: datetime) -> str:
        day_folder = os.path.join(self.base_dir, self.camera_id, segment_start.strftime("%Y%m%d"))
        os.makedirs(day_folder, exist_ok=True)
        filename = f"{segment_start.strftime('%H%M%S')}.mp4"
        return os.path.join(day_folder, filename)

    def _drain_queue(self):
        while True:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                return

    def _push_frame(self, frame_time: datetime, frame):
        item = (frame_time, frame)
        try:
            self.frame_queue.put_nowait(item)
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(item)
            except queue.Full:
                pass

    def _close_writer(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            self.writer_size = None
            self.current_segment = None
            self.writer_codec = None

    def _close_capture(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            self.open_mode = None

    def _ensure_capture(self):
        if self.cap is not None and self.cap.isOpened():
            return
        self._close_capture()
        cap, mode, first_frame = open_capture(
            self.rtsp_url,
            self.use_hwaccel,
            debug_label=self.camera_id,
        )
        self.cap = cap
        self.open_mode = mode or None
        if self.cap is not None:
            print(f"{self.camera_id}: opened ({self.open_mode})")
            if first_frame is not None:
                self._push_frame(datetime.now(), first_frame)
        else:
            print(f"{self.camera_id}: cannot open stream")

    def _ensure_writer(self, frame, now: datetime):
        segment_start = self._segment_start(now)
        size = (frame.shape[1], frame.shape[0])
        if self.writer is not None and self.current_segment == segment_start and self.writer_size == size:
            return

        self._close_writer()
        output_path = self._output_path(segment_start)
        writer, writer_codec = open_video_writer(output_path, size, CAMERA_FPS)
        self.writer = writer
        self.writer_codec = writer_codec
        self.writer_size = size
        self.current_segment = segment_start
        print(f"{self.camera_id}: recording {output_path} ({writer_codec})")

    def _capture_loop(self):
        while not self.stop_event.is_set():
            now = datetime.now()
            if not in_record_time(now):
                self._close_capture()
                self._drain_queue()
                time.sleep(1.0)
                continue

            self._ensure_capture()
            if self.cap is None:
                time.sleep(2.0)
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                print(f"{self.camera_id}: read failed ({self.open_mode}), reconnecting...")
                self._close_capture()
                time.sleep(0.5)
                continue
            self._push_frame(datetime.now(), frame)

        self._close_capture()

    def _writer_loop(self):
        while not self.stop_event.is_set():
            try:
                frame_time, frame = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                if not in_record_time(datetime.now()):
                    self._close_writer()
                continue

            if not in_record_time(frame_time):
                self._close_writer()
                continue

            try:
                self._ensure_writer(frame, frame_time)
                if self.writer is not None:
                    self.writer.write(frame)
            except Exception as e:
                print(f"{self.camera_id}: writer error -> {e}")
                self._close_writer()
                time.sleep(0.2)

        self._close_writer()

    def stop(self):
        self.stop_event.set()
        self.capture_thread.join(timeout=3.0)
        self.writer_thread.join(timeout=3.0)
        self._close_writer()
        self._close_capture()


def main():
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Record 5 RTSP streams with OpenCV + GStreamer")
    parser.add_argument(
        "--no-hwaccel",
        action="store_true",
        help="Tat NVDEC hardware decode, chi dung software decode",
    )
    parser.add_argument(
        "--output-dir",
        default=RECORD_BASE_DIR,
        help="Thu muc goc luu video (mac dinh: recordings)",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Chi test ket noi tung camera, khong ghi file",
    )
    args = parser.parse_args()

    use_hwaccel = not args.no_hwaccel
    backend = (
        "NVDEC + OpenCV(GStreamer writer)"
        if use_hwaccel
        else "software decode + OpenCV(GStreamer writer)"
    )

    print(f"\nTim thay {len(RTSP_URLS)} camera:")
    for cam_id, url in RTSP_URLS.items():
        print(f"  {cam_id}: {url}")
    print(f"\nBackend: {backend}")
    print(f"Khung gio ghi: {WINDOW_START.strftime('%H:%M')} - {WINDOW_END.strftime('%H:%M')}")
    print(f"Segment length: {SEGMENT_SECONDS} seconds")
    print(f"Output dir: {args.output_dir}\n")

    if args.probe_only:
        print("Probe mode: test tung camera tuan tu.")
        for cam_id, url in RTSP_URLS.items():
            cap, mode, first_frame = open_capture(
                url,
                use_hwaccel=use_hwaccel,
                debug_label=cam_id,
            )
            if cap is None:
                print(f"{cam_id}: FAIL (khong mo duoc stream)")
                continue
            shape = tuple(first_frame.shape) if first_frame is not None else None
            print(f"{cam_id}: OK ({mode}), first_frame_shape={shape}")
            cap.release()
        return

    workers = [
        CameraRecorder(cam_id, url, use_hwaccel=use_hwaccel, base_dir=args.output_dir)
        for cam_id, url in RTSP_URLS.items()
    ]

    for worker in workers:
        worker.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping recorders...")
    finally:
        for worker in workers:
            worker.stop()
        print("Done.")


if __name__ == "__main__":
    main()
