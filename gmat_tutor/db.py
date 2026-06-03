from __future__ import annotations

import base64
import binascii
import csv
import io
import zlib
from pathlib import Path
from typing import Any

from . import db_old as _core


def _seed_payload_part_files(path: Path, index: int) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.part{index:02d}.chunk*"))


def _seed_payload_parts(path: Path) -> list[Path]:
    parts: list[Path] = []
    index = 1
    while True:
        direct_part = path.parent / f"{path.name}.part{index:02d}"
        chunked_parts = _seed_payload_part_files(path, index)
        if direct_part.exists():
            parts.append(direct_part)
        elif chunked_parts:
            parts.extend(chunked_parts)
        else:
            break
        index += 1
    if parts:
        return parts
    return sorted(path.parent.glob(f"{path.name}.part*"))


def _seed_path_exists(path: Path) -> bool:
    return path.exists() or bool(_seed_payload_parts(path))


def _seed_payload_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="ascii").strip()

    parts: list[str] = []
    index = 1
    while True:
        direct_part = path.parent / f"{path.name}.part{index:02d}"
        chunked_parts = _seed_payload_part_files(path, index)
        if direct_part.exists():
            parts.append(direct_part.read_text(encoding="ascii").strip())
        elif chunked_parts:
            parts.append("".join(part.read_text(encoding="ascii").strip() for part in chunked_parts))
        else:
            break
        index += 1

    if parts:
        return "".join(parts)
    return "".join(part.read_text(encoding="ascii").strip() for part in sorted(path.parent.glob(f"{path.name}.part*")))


def _seed_rows(path: Path) -> list[dict[str, str]]:
    if path.name.endswith(".zlib.b64"):
        try:
            encoded = _seed_payload_text(path)
            payload = base64.b64decode(encoded, validate=True)
            text = zlib.decompress(payload).decode("utf-8-sig")
        except (ValueError, binascii.Error, zlib.error, UnicodeDecodeError):
            return []
        return list(csv.DictReader(io.StringIO(text)))

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


_core._seed_payload_part_files = _seed_payload_part_files
_core._seed_payload_parts = _seed_payload_parts
_core._seed_path_exists = _seed_path_exists
_core._seed_rows = _seed_rows

for _name in dir(_core):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_core, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
