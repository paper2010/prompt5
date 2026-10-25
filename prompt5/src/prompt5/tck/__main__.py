"""`python -m prompt5.tck` 入口。"""

from __future__ import annotations

import argparse
import sys

from .suite import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prompt5.tck")
    parser.add_argument("--config", default="config.example.yaml")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args.config, verbose=not args.quiet)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
