"""
Backward-compatible re-export.

New locations:
- Generic functions: src.backend.core.utils.polygon
- Fence-specific functions: src.backend.modules.fence.geometry
"""
# Generic polygon utilities
from src.backend.core.utils.polygon import *  # noqa: F401,F403

# Fence-specific (backward compat for treo_rao.py, test_algorithm.py, test_fence.py)
from src.backend.modules.fence.geometry import *  # noqa: F401,F403
