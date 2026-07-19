"""
Unit tests for the closed-loop control + tracking module (1a upgrade).

Pure-Python, no GPU / PTZ / OpenCV — safe to run on a dev box:

    python -m src.backend.tests.test_control
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow "python src/backend/tests/test_control.py" from repo root.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.backend.modules.fence.control import (  # noqa: E402
    PID,
    TargetTracker,
    iou,
    map_effort,
)

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _failures.append(msg)


# ---------------------------------------------------------------------------
# PID
# ---------------------------------------------------------------------------

def test_pid_converges_on_first_order_plant():
    """Drive a simple plant y += 0.5*u toward setpoint 0; error should vanish."""
    pid = PID(kp=0.8, ki=0.05, kd=0.1, output_limit=1.0, deadband=0.01)
    y = 1.0  # start far from setpoint (0)
    dt = 0.1
    for _ in range(200):
        error = 0.0 - y
        u = pid.update(error, dt)
        y += 0.5 * u  # plant responds to control effort
    check(abs(y) < 0.05, f"PID converges near setpoint (final y={y:.4f})")


def test_pid_deadband_zero_output():
    pid = PID(kp=5.0, deadband=0.1)
    check(pid.update(0.05, 0.1) == 0.0, "PID returns 0 inside deadband")
    check(pid.update(0.5, 0.1) != 0.0, "PID drives outside deadband")


def test_pid_output_clamped():
    pid = PID(kp=100.0, output_limit=1.0)
    u = pid.update(10.0, 0.1)
    check(u == 1.0, f"PID output clamped to limit (u={u})")
    u2 = pid.update(-10.0, 0.1)
    check(u2 == -1.0, f"PID output clamped to negative limit (u={u2})")


def test_pid_reset_clears_state():
    # Wind the integral up, then compare a fresh sample with vs without reset.
    pid = PID(kp=1.0, ki=1.0, output_limit=100.0)
    for _ in range(5):
        pid.update(1.0, 0.1)
    wound_up = pid.update(1.0, 0.1)

    pid.reset()
    after_reset = pid.update(1.0, 0.1)
    # After reset only one integration step remains → output is p + ki*error*dt.
    check(abs(after_reset - (1.0 + 1.0 * 1.0 * 0.1)) < 1e-9, f"PID reset clears integral (u={after_reset:.4f})")
    check(after_reset < wound_up, f"reset output < wound-up output ({after_reset:.3f} < {wound_up:.3f})")


def test_map_effort_monotonic_and_bounded():
    s_lo, d_lo = map_effort(0.05)
    s_hi, d_hi = map_effort(1.0)
    check(1 <= s_lo <= 8 and 1 <= s_hi <= 8, "map_effort step within [1,8]")
    check(s_hi >= s_lo and d_hi >= d_lo, "map_effort grows with |effort|")
    check(map_effort(5.0)[0] == 8, "map_effort saturates step at 8")


# ---------------------------------------------------------------------------
# IoU + TargetTracker
# ---------------------------------------------------------------------------

def test_iou_basic():
    check(iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0, "IoU identical = 1.0")
    check(iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0, "IoU disjoint = 0.0")
    check(abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-9, "IoU half-overlap")


def test_tracker_stable_id_while_moving():
    """A single person drifting right keeps one stable id across frames."""
    trk = TargetTracker(iou_threshold=0.2)
    ids = set()
    for step in range(10):
        x = step * 5  # box slides right 5px/frame (overlaps previous)
        live = trk.update([(x, 0, x + 40, 80, 0.9)])
        check(len(live) == 1, f"frame {step}: exactly one live track")
        ids.add(live[0].id)
    check(len(ids) == 1, f"same id kept across motion (ids={ids})")


def test_tracker_keeps_two_people_distinct():
    trk = TargetTracker(iou_threshold=0.2)
    id_left = id_right = None
    for step in range(6):
        left = (step * 3, 0, step * 3 + 40, 80, 0.9)
        right = (300 + step * 3, 0, 340 + step * 3, 80, 0.9)
        live = trk.update([left, right])
        check(len(live) == 2, f"frame {step}: two live tracks")
        live_sorted = sorted(live, key=lambda t: t.center[0])
        if step == 0:
            id_left, id_right = live_sorted[0].id, live_sorted[1].id
        else:
            check(
                live_sorted[0].id == id_left and live_sorted[1].id == id_right,
                f"frame {step}: ids stay bound to their person",
            )
        check(id_left != id_right, "two people have distinct ids")


def test_tracker_reacquire_and_retire():
    """A track survives a short miss (max_age) then retires after long absence."""
    trk = TargetTracker(iou_threshold=0.2, max_age=3)
    trk.update([(0, 0, 40, 80, 0.9)])
    tid = trk.tracks[0].id
    # Miss for 2 frames — still remembered, not yet retired.
    trk.update([])
    trk.update([])
    check(trk.get(tid) is not None, "track remembered within max_age")
    # Reappears nearby → should re-match same id (predicted box overlaps).
    live = trk.update([(0, 0, 40, 80, 0.9)])
    check(len(live) == 1 and live[0].id == tid, "track reacquired with same id")
    # Now disappear long enough to retire.
    for _ in range(5):
        trk.update([])
    check(trk.get(tid) is None, "track retired after max_age exceeded")


def main() -> int:
    tests = [
        test_pid_converges_on_first_order_plant,
        test_pid_deadband_zero_output,
        test_pid_output_clamped,
        test_pid_reset_clears_state,
        test_map_effort_monotonic_and_bounded,
        test_iou_basic,
        test_tracker_stable_id_while_moving,
        test_tracker_keeps_two_people_distinct,
        test_tracker_reacquire_and_retire,
    ]
    for t in tests:
        print(f"\n[{t.__name__}]")
        t()

    print("\n" + "=" * 50)
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
