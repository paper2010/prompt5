"""`python -m prompt5.api` 入口（package 形态需要 __main__.py）。"""

from __future__ import annotations

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
