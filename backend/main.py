#!/usr/bin/env python3
"""
UBQN — Unified Entry Point.

Chạy trực tiếp:
    python3 src/backend/main.py --module fence
    python3 src/backend/main.py --module fence --no-ptz
    python3 src/backend/main.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── Setup sys.path ──────────────────────────────────────────────
# Đảm bảo import src.* hoạt động khi chạy trực tiếp python3 src/backend/main.py
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(
        description="UBQN — Hệ thống phát hiện bất thường",
        add_help=True,
    )
    parser.add_argument(
        "--module", "-m",
        type=str,
        help="Tên module cần chạy (ví dụ: fence, crowd, parking)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="Liệt kê các module có sẵn",
    )

    # Parse chỉ args đã biết, còn lại forward cho module
    args, remaining = parser.parse_known_args()

    if args.list:
        from src.backend.modules import get_available_modules
        modules = get_available_modules()
        print("\n╔══════════════════════════════════════╗")
        print("║     UBQN — Available Modules         ║")
        print("╠══════════════════════════════════════╣")
        for m in modules:
            print(f"║  • {m:<34}║")
        if not modules:
            print("║  (không có module nào)               ║")
        print("╚══════════════════════════════════════╝")
        print(f"\nSử dụng: python3 src/backend/main.py --module <tên>\n")
        return

    if not args.module:
        parser.print_help()
        print("\n⚠️  Vui lòng chỉ định module: python3 src/backend/main.py --module fence\n")
        sys.exit(1)

    # Forward remaining args cho module
    sys.argv = [f"src.backend.modules.{args.module}"] + remaining

    from src.backend.modules import get_module_entrypoint
    entry = get_module_entrypoint(args.module)
    if entry is None:
        print(f"\n❌ Module '{args.module}' không tìm thấy hoặc không có hàm main().")
        print(f"   Chạy: python3 src/backend/main.py --list để xem danh sách module.\n")
        sys.exit(1)

    print(f"\n🚀 Khởi chạy module: {args.module}\n")
    entry()


if __name__ == "__main__":
    main()
