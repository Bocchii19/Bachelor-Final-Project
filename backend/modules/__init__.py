"""
Modules package — Detection module registry.

Cung cấp:
- BaseModule: Interface chuẩn cho mọi module
- get_available_modules(): Liệt kê module có sẵn
- get_module(): Lấy module entry point theo tên
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from .base import BaseModule

logger = logging.getLogger(__name__)

# Danh sách module đã đăng ký
_REGISTERED_MODULES: dict[str, str] = {
    "fence": "src.backend.modules.fence.main",
}


def get_available_modules() -> list[str]:
    """Liệt kê tên các module có sẵn."""
    modules_dir = Path(__file__).parent
    available = []
    for child in sorted(modules_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            available.append(child.name)
    return available


def get_module_entrypoint(name: str):
    """
    Lấy hàm main() của module theo tên.

    Returns:
        Callable main function, hoặc None nếu không tìm thấy.
    """
    module_path = _REGISTERED_MODULES.get(name)
    if module_path is None:
        # Try auto-discovery
        module_path = f"src.backend.modules.{name}.main"

    try:
        mod = importlib.import_module(module_path)
        main_fn = getattr(mod, "main", None)
        if main_fn is None:
            logger.error("Module '%s' không có hàm main().", name)
            return None
        return main_fn
    except ImportError as e:
        logger.error("Không thể import module '%s': %s", name, e)
        return None


__all__ = ["BaseModule", "get_available_modules", "get_module_entrypoint"]
