from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    protocol_version: str = "1.0"

    @classmethod
    def for_directory(cls, directory: str | Path) -> Settings:
        return cls(Path(directory).expanduser().resolve())
