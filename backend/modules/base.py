"""
Base module interface cho tất cả detection modules.

Mỗi module (fence, crowd, parking...) phải kế thừa BaseModule
và implement các method chuẩn.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseModule(ABC):
    """Interface chung cho mọi detection module."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config: dict[str, Any] = {}
        self._config_path = config_path
        self._logger = logging.getLogger(f"module.{self.name}")
        self._running = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Tên module (ví dụ: 'fence', 'crowd', 'parking')."""
        ...

    @abstractmethod
    def load_config(self) -> dict[str, Any]:
        """Load config riêng cho module từ configs/<name>.yaml."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Khởi chạy module."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Dừng module gracefully."""
        ...

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def config(self) -> dict[str, Any]:
        return self._config
