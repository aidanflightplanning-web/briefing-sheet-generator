"""Remembered settings: attached MEL sheets and output options."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "BriefingSheetGenerator" / "settings.json"


@dataclass
class Settings:
    mel_paths: list[str] = field(default_factory=list)
    utc_offset_hours: float = -4.0     # dispatch office local time (Trinidad, UTC-4)
    dispatcher: str = ""               # used only if the flight plan has no dispatcher line
    append_to_flight_plan: bool = True
    open_when_done: bool = True
    output_dir: str = ""               # blank = same folder as the flight plan
    last_folder: str = ""

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass
