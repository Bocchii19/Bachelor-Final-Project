"""
PTZ Patrol — Intrusion Detection + PTZ Response + Face Capture
===============================================================
Kết hợp giám sát xâm nhập (treo_rao) với điều khiển PTZ tự động:
1. Fixed cameras detect người xâm phạm (YOLO + ROI + fence line)
2. Trigger PTZ quay đến preset tương ứng
3. PTZ detect + zoom & center vào người
4. InsightFace capture khuôn mặt
5. Lưu ảnh + metadata

Usage:
    python3 -m src.backend.modules.ptz_patrol
    python3 -m src.backend.modules.ptz_patrol --no-ptz
    python3 -m src.backend.modules.ptz_patrol --preset-manager
"""
