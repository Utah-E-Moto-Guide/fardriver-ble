"""Where fardriver-ble keeps the rider's data. Nothing personal lives in the package or the repo.

Default: $XDG_DATA_HOME/fardriver-ble (usually ~/.local/share/fardriver-ble).
Override with FARDRIVER_DATA, e.g. a private git repo of your own to keep the history.

    snapshots/       one folder per snapshot (snapshot.json + controller.heb)
    captures/        raw BLE logs of every write and save
    sessions/        tuning session logs
    factory/         the factory reference of each controller, by serial (see snapshot.py)
    knowledge.yml    your own notes, merged into the shipped knowledge (optional)
    config.yml       e.g. `profiles: [xpro-drax-apex]` to add a bike profile's notes (optional)
"""

import os
from pathlib import Path


def data_dir() -> Path:
    if os.environ.get("FARDRIVER_DATA"):
        return Path(os.environ["FARDRIVER_DATA"]).expanduser()
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
