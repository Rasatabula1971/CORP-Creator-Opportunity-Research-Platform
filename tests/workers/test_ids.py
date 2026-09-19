"""Unit tests for corp.workers.adapters.ids.stable_id."""

import os
import subprocess
import sys
from pathlib import Path

from corp.workers.adapters.ids import stable_id

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_stable_id_is_deterministic():
    assert stable_id("amz_", "hello", "world") == stable_id("amz_", "hello", "world")


def test_stable_id_distinguishes_inputs():
    assert stable_id("amz_", "hello") != stable_id("amz_", "world")


def test_stable_id_applies_prefix():
    assert stable_id("amz_", "text").startswith("amz_")


def test_stable_id_is_stable_across_processes():
    """Guards against a regression to the builtin hash(), which is salted
    per-process (PYTHONHASHSEED) and would make this id change on every
    worker restart, silently defeating dedup."""
    script = (
        "from corp.workers.adapters.ids import stable_id; "
        "print(stable_id('amz_', 'same input'))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        ).stdout.strip()
        for seed in ("0", "1", "42")
    }
    assert len(outputs) == 1
