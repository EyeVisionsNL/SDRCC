#!/usr/bin/env python3
"""Generic Mission Recordings inventory for images and audio."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import mimetypes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = (PROJECT_ROOT / "data" / "recordings").resolve()
AUDIO = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def safe_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    path.relative_to(ROOT)
    if not path.is_file():
        raise FileNotFoundError(value)
    return path


def inventory(limit: int = 100) -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in AUDIO | IMAGES:
            continue
        stat = path.stat()
        rel = path.relative_to(ROOT)
        rows.append({
            "name": path.name, "relative_path": str(rel),
            "kind": "audio" if path.suffix.lower() in AUDIO else "image",
            "format": path.suffix.lower().lstrip("."), "size_bytes": stat.st_size,
            "modified_epoch": int(stat.st_mtime),
            "mission_id": rel.parts[-2] if len(rel.parts) > 1 else None,
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "url": "/api/mission-recordings/file/" + str(rel),
        })
    rows.sort(key=lambda item: item["modified_epoch"], reverse=True)
    return {"ok": True, "version": "0.48.0a", "count": len(rows[:limit]), "recordings": rows[:limit]}
