"""
Closed-loop PTZ control + lightweight target tracking for the fence module.

Two self-contained pieces used by :class:`PatrolTracker` to replace the old
fixed-step "center a bit → zoom → sleep 1s → repeat" loop:

1. :class:`PID` — single-axis proportional-integral-derivative controller with
   output clamping, integral anti-windup and a deadband. One instance drives
   pan, one tilt, one zoom. Smoother convergence and fewer overshoots than the
   bang-bang stepping it replaces.

2. :class:`TargetTracker` — ByteTrack-style multi-object tracker. It gives each
   detected person a *stable* integer id (IoU + centroid gating, linear
   assignment via the ``lap`` package when installed, greedy fallback
   otherwise). The controller locks onto ONE id so the PTZ keeps following the
   same intruder across re-detections instead of re-picking the largest box
   every frame — the box that "jumps" between people in a crowd.

Pure Python (stdlib only) so it is unit-testable on a dev box with no GPU, no
PTZ hardware, no OpenCV and no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

BBox = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# PID controller
# ---------------------------------------------------------------------------

@dataclass
class PID:
    """Single-axis PID controller.

    ``update(error, dt)`` returns a control effort clamped to
    ``[-output_limit, output_limit]``. Errors whose magnitude is within
    ``deadband`` produce zero effort (avoids jitter around the setpoint) and
    also bleed the integral term so it does not wind up while parked.
    """

    kp: float
    ki: float = 0.0
    kd: float = 0.0
    output_limit: float = 1.0
    integral_limit: float = 1.0
    deadband: float = 0.0

    _integral: float = field(default=0.0, init=False)
    _prev_error: Optional[float] = field(default=None, init=False)

    def reset(self) -> None:
        """Clear integral + derivative history (call before a new target)."""
        self._integral = 0.0
        self._prev_error = None

    def update(self, error: float, dt: float) -> float:
        # Inside the deadband: no drive, and decay the integral toward 0 so it
        # never accumulates while the target is already centered.
        if abs(error) <= self.deadband:
            self._integral *= 0.5
            self._prev_error = error
            return 0.0

        # Proportional
        p = self.kp * error

        # Integral with anti-windup clamp
        if dt > 0:
            self._integral += error * dt
            self._integral = _clamp(self._integral, self.integral_limit)
        i = self.ki * self._integral

        # Derivative (skipped on the first sample and when dt is unknown)
        d = 0.0
        if self._prev_error is not None and dt > 0:
            d = self.kd * (error - self._prev_error) / dt
        self._prev_error = error

        return _clamp(p + i + d, self.output_limit)


def _clamp(value: float, limit: float) -> float:
    if value > limit:
        return limit
    if value < -limit:
        return -limit
    return value


def map_effort(
    effort: float,
    *,
    step_min: int = 1,
    step_max: int = 8,
    dur_min: float = 0.08,
    dur_max: float = 0.35,
) -> tuple[int, float]:
    """Map a PID effort in ``[-1, 1]`` to a PTZ ``(step, duration)`` pair.

    The PTZ API is bang-bang — ``move_direction(cmd, step, duration)`` runs at
    ``step`` speed for ``duration`` seconds. Larger |effort| → faster step and
    longer pulse, so the controller takes big swings when far off and gentle
    nudges near the setpoint. Sign is dropped here; the caller picks the
    direction command.
    """
    magnitude = min(1.0, abs(effort))
    step = round(step_min + magnitude * (step_max - step_min))
    step = int(max(step_min, min(step_max, step)))
    duration = dur_min + magnitude * (dur_max - dur_min)
    return step, duration


# ---------------------------------------------------------------------------
# Lightweight multi-object tracker (ByteTrack-style association)
# ---------------------------------------------------------------------------

def iou(a: BBox, b: BBox) -> float:
    """Intersection-over-union of two ``(x1, y1, x2, y2)`` boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(bbox: BBox) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


@dataclass
class Track:
    """One tracked person."""

    id: int
    bbox: BBox
    score: float = 0.0
    hits: int = 1
    age: int = 0
    time_since_update: int = 0
    # Last observed per-frame velocity of the box center (for prediction while
    # the camera is panning between detections).
    vx: float = 0.0
    vy: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        return _center(self.bbox)

    @property
    def area(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0]) * max(0.0, self.bbox[3] - self.bbox[1])

    def predicted_bbox(self) -> BBox:
        """Bbox shifted by last velocity — helps match after a camera move."""
        x1, y1, x2, y2 = self.bbox
        return (x1 + self.vx, y1 + self.vy, x2 + self.vx, y2 + self.vy)


class TargetTracker:
    """Minimal SORT/ByteTrack-style tracker over person detections.

    ``update(detections)`` takes ``[(x1, y1, x2, y2, score), ...]`` and returns
    the list of currently *live* tracks (each with a persistent ``id``).
    Association cost is ``1 - IoU`` between the predicted track box and each
    detection, solved with ``lap.lapjv`` when the package is available and a
    greedy nearest-match otherwise. Matches whose IoU is below
    ``iou_threshold`` are rejected so distinct people never merge.
    """

    def __init__(
        self,
        iou_threshold: float = 0.2,
        max_age: int = 15,
        min_hits: int = 1,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        self._tracks: list[Track] = []
        self._next_id = 1

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def get(self, track_id: int) -> Optional[Track]:
        for t in self._tracks:
            if t.id == track_id:
                return t
        return None

    def update(self, detections: list[tuple]) -> list[Track]:
        dets: list[BBox] = [(float(d[0]), float(d[1]), float(d[2]), float(d[3])) for d in detections]
        scores = [float(d[4]) if len(d) > 4 else 0.0 for d in detections]

        for t in self._tracks:
            t.age += 1
            t.time_since_update += 1

        matches, unmatched_dets = self._associate(dets)

        # Update matched tracks
        for trk_idx, det_idx in matches:
            t = self._tracks[trk_idx]
            old_cx, old_cy = t.center
            t.bbox = dets[det_idx]
            new_cx, new_cy = t.center
            t.vx, t.vy = new_cx - old_cx, new_cy - old_cy
            t.score = scores[det_idx]
            t.hits += 1
            t.time_since_update = 0

        # Spawn new tracks for unmatched detections
        for det_idx in unmatched_dets:
            self._tracks.append(
                Track(id=self._next_id, bbox=dets[det_idx], score=scores[det_idx])
            )
            self._next_id += 1

        # Retire stale tracks
        self._tracks = [t for t in self._tracks if t.time_since_update <= self.max_age]
        return [t for t in self._tracks if t.time_since_update == 0]

    # ── association ──

    def _associate(self, dets: list[BBox]) -> tuple[list[tuple[int, int]], list[int]]:
        if not self._tracks or not dets:
            return [], list(range(len(dets)))

        # Cost matrix: 1 - IoU(predicted track box, detection).
        cost: list[list[float]] = []
        for t in self._tracks:
            pred = t.predicted_bbox()
            cost.append([1.0 - iou(pred, d) for d in dets])

        max_cost = 1.0 - self.iou_threshold  # reject matches below IoU threshold
        pairs = _solve_assignment(cost, max_cost)

        matched_dets = {d for _, d in pairs}
        unmatched = [j for j in range(len(dets)) if j not in matched_dets]
        return pairs, unmatched


def _solve_assignment(cost: list[list[float]], max_cost: float) -> list[tuple[int, int]]:
    """Return ``[(row, col), ...]`` matches with ``cost <= max_cost``.

    Uses ``lap.lapjv`` (as ByteTrack does) when importable; otherwise a greedy
    smallest-cost-first fallback that needs no third-party package.
    """
    try:
        import lap  # type: ignore

        # lapjv needs a square-ish matrix; extend_cost pads internally.
        import array

        n_rows = len(cost)
        n_cols = len(cost[0])
        # Build a flat cost matrix for lap (list-of-lists is accepted via numpy
        # normally, but we avoid numpy — fall back to greedy if lap needs it).
        try:
            import numpy as _np  # type: ignore

            matrix = _np.asarray(cost, dtype=float)
            _, x, _ = lap.lapjv(matrix, extend_cost=True, cost_limit=max_cost)
            pairs = [(r, int(c)) for r, c in enumerate(x) if c >= 0]
            return pairs
        except Exception:
            pass
    except Exception:
        pass

    return _greedy_assignment(cost, max_cost)


def _greedy_assignment(cost: list[list[float]], max_cost: float) -> list[tuple[int, int]]:
    """Greedy assignment: repeatedly take the globally smallest valid cost."""
    candidates = []
    for r, row in enumerate(cost):
        for c, val in enumerate(row):
            if val <= max_cost:
                candidates.append((val, r, c))
    candidates.sort()

    used_rows: set[int] = set()
    used_cols: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, r, c in candidates:
        if r in used_rows or c in used_cols:
            continue
        used_rows.add(r)
        used_cols.add(c)
        pairs.append((r, c))
    return pairs
