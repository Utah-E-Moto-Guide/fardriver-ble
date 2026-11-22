"""Where fardriver-ble keeps the rider's data. Nothing personal lives in the package or the repo.

Default: Linux $XDG_DATA_HOME/fardriver-ble (usually ~/.local/share/fardriver-ble), macOS
~/Library/Application Support/fardriver-ble, Windows %LOCALAPPDATA%\\fardriver-ble.
Override with FARDRIVER_DATA, e.g. a private git repo of your own to keep the history.

    snapshots/       one folder per snapshot (snapshot.json + controller.heb)
    captures/        raw BLE logs of every write and save
    sessions/        tuning session logs
    factory/         the factory reference of each controller, by serial (see snapshot.py)
    knowledge.yml    your own notes, merged into the shipped knowledge (optional)
    config.yml       optional: `profiles: [xpro-drax-apex]` (bike profile notes),
                     `allow_untested_firmware: true` (writes on unverified firmware, at your own risk)
"""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    if os.environ.get("FARDRIVER_DATA"):
        return Path(os.environ["FARDRIVER_DATA"]).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "fardriver-ble"


DATA = data_dir()
SNAPSHOTS = DATA / "snapshots"
CAPTURES = DATA / "captures"
SESSIONS = DATA / "sessions"
FACTORY = DATA / "factory"
LOCAL_KNOWLEDGE = DATA / "knowledge.yml"
CONFIG = DATA / "config.yml"

PACKAGE = Path(__file__).resolve().parent
KNOWLEDGE = PACKAGE / "knowledge" / "settings.yml"
PROFILES = PACKAGE / "knowledge" / "profiles"


def config() -> dict:
    """<data>/config.yml as a dict ({} if missing)."""
    if not CONFIG.exists():
        return {}
    import yaml

    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}

