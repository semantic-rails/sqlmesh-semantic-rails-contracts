"""Deterministic SQLMesh process settings for the contract test suite."""

import os

os.environ.setdefault("MAX_FORK_WORKERS", "1")
