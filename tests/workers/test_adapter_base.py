"""Unit tests for shared adapter helpers in corp.workers.adapters.base."""

import os
import subprocess
import sys
from pathlib import Path

from corp.workers.adapters.base import content_hash, stable_id

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_content_hash_is_deterministic():
    assert content_hash("hello", "world") == content_hash("hello", "world")


def test_content_hash_distinguishes_inputs():
    assert content_hash("hello") != content_hash("world")


def test_stable_id_applies_prefix():
    assert stable_id("amz", "some review text") == f"amz_{content_hash('some review text')}"


def test_content_hash_is_stable_across_processes():
    """Guards against a regression back to the builtin hash(), which is
    salted per-process (PYTHONHASHSEED) and would make this id change on
    every worker restart, silently defeating dedup."""
    script = (
        "from corp.workers.adapters.base import content_hash; "
        "print(content_hash('same input'))"
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
