"""Tests never touch a rider's real data: FARDRIVER_DATA points at a throwaway folder and no bike
profile or untested-firmware opt-in is turned on, before any fardriver_ble module reads its paths."""

import os
import tempfile
from pathlib import Path

os.environ["FARDRIVER_DATA"] = tempfile.mkdtemp(prefix="fardriver-test-")
os.environ["FARDRIVER_PROFILE"] = ""
os.environ["FARDRIVER_ALLOW_UNTESTED"] = ""

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAPSHOTS = FIXTURES / "snapshots"  # real captures from one controller (an X-Pro Drax Apex, WC72V150)
CAPTURES = FIXTURES / "captures"
