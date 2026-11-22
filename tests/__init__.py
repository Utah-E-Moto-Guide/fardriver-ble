"""Tests never touch a rider's real data: TRAILTUNE_DATA points at a throwaway folder and no bike
profile or untested-firmware opt-in is turned on, before any trailtune module reads its paths."""

import os
import tempfile
from pathlib import Path

os.environ["TRAILTUNE_DATA"] = tempfile.mkdtemp(prefix="trailtune-test-")
os.environ["TRAILTUNE_PROFILE"] = ""
os.environ["TRAILTUNE_ALLOW_UNTESTED"] = ""

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAPSHOTS = FIXTURES / "snapshots"  # real captures from one controller (an X-Pro Drax Apex, WC72V150)
CAPTURES = FIXTURES / "captures"
