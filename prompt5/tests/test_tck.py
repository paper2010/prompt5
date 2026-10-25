"""M6 DoD：TCK 套件必须全绿。"""

from __future__ import annotations

from pathlib import Path

from prompt5.tck.suite import run

CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_tck_all_green() -> None:
    summary = run(CONFIG, verbose=False)
    assert summary["ok"] is True, summary["results"]
    assert summary["failed"] == 0
    assert summary["passed"] >= 12
