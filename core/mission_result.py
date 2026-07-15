from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
import re


IMAGE_PATTERNS = ("*.png", "*.jpg", "*.jpeg")
CADU_FRAME_BYTES = 8192
KNOWN_RESULTS = {
    "SUCCESS",
    "NO IMAGES",
    "NO SYNC",
    "NO SIGNAL",
    "FAILED",
    "CANCELLED",
}


@dataclass(frozen=True)
class MissionResult:
    success: bool
    result: str
    detail: str
    error: Optional[str]
    peak_snr_db: Optional[float]
    frames: int
    cadu_bytes: int
    image_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def inspect_output(output_path: Optional[str | Path]) -> dict[str, int]:
    cadu_bytes = 0
    image_count = 0

    if output_path:
        output_dir = Path(output_path)
        if output_dir.exists():
            cadu_bytes = sum(
                item.stat().st_size
                for item in output_dir.rglob("*.cadu")
                if item.is_file()
            )
            image_count = sum(
                1
                for pattern in IMAGE_PATTERNS
                for item in output_dir.rglob(pattern)
                if item.is_file()
            )

    return {
        "cadu_bytes": cadu_bytes,
        "frames": cadu_bytes // CADU_FRAME_BYTES,
        "image_count": image_count,
    }


def extract_peak_snr(stdout: str = "", stderr: str = "") -> Optional[float]:
    combined = f"{stdout or ''}\n{stderr or ''}".upper()
    values = [
        float(value)
        for value in re.findall(r"SNR\s*:\s*(-?\d+(?:\.\d+)?)\s*DB", combined)
    ]
    return max(values) if values else None


def classify(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    output_path: Optional[str | Path] = None,
    frames: Optional[int] = None,
    cadu_bytes: Optional[int] = None,
    image_count: Optional[int] = None,
    peak_snr_db: Optional[float] = None,
    cancelled: bool = False,
) -> dict[str, Any]:
    combined_upper = f"{stdout or ''}\n{stderr or ''}".upper()
    inspected = inspect_output(output_path)

    effective_cadu = max(_as_int(cadu_bytes), inspected["cadu_bytes"])
    effective_frames = max(
        _as_int(frames),
        inspected["frames"],
        effective_cadu // CADU_FRAME_BYTES,
    )
    effective_images = max(_as_int(image_count), inspected["image_count"])
    effective_snr = (
        _as_optional_float(peak_snr_db)
        if peak_snr_db is not None
        else extract_peak_snr(stdout, stderr)
    )

    metrics = {
        "peak_snr_db": effective_snr,
        "frames": effective_frames,
        "cadu_bytes": effective_cadu,
        "image_count": effective_images,
    }

    if cancelled:
        outcome = MissionResult(
            False,
            "CANCELLED",
            "Missie geannuleerd",
            None,
            **metrics,
        )
    elif effective_images > 0:
        warning = (
            f"; SatDump eindigde met waarschuwing/foutcode {returncode}"
            if returncode != 0
            else ""
        )
        outcome = MissionResult(
            True,
            "SUCCESS",
            (
                f"Decode voltooid; {effective_frames} frames, "
                f"{effective_cadu} bytes CADU-data, "
                f"{effective_images} afbeelding(en){warning}"
            ),
            None,
            **metrics,
        )
    elif returncode != 0:
        detail = f"SatDump stopte met foutcode {returncode}"
        outcome = MissionResult(False, "FAILED", detail, detail, **metrics)
    elif effective_cadu > 0 or effective_frames > 0 or "DEFRAMER : SYNC" in combined_upper:
        outcome = MissionResult(
            False,
            "NO IMAGES",
            (
                f"LRPT-data ontvangen ({effective_frames} frames, "
                f"{effective_cadu} bytes CADU), maar SatDump produceerde geen afbeelding"
            ),
            None,
            **metrics,
        )
    elif "NOSYNC" in combined_upper and effective_snr is not None:
        outcome = MissionResult(
            False,
            "NO SYNC",
            (
                "Signaal gezien, maar geen decoder-lock; "
                f"piek-SNR {effective_snr:.2f} dB, 0 frames"
            ),
            None,
            **metrics,
        )
    else:
        outcome = MissionResult(
            False,
            "NO SIGNAL",
            "Geen bruikbaar LRPT-signaal, frames of afbeeldingen gevonden",
            None,
            **metrics,
        )

    return outcome.to_dict()


def normalize_history_mission(mission: Mapping[str, Any]) -> dict[str, Any]:
    """Geef een niet-destructief, actueel beoordeelde History-weergave terug."""
    normalized = dict(mission)
    stored_result = str(normalized.get("result") or normalized.get("status") or "").upper()

    if stored_result == "CANCELLED":
        evaluated = classify(
            cancelled=True,
            frames=_as_int(normalized.get("frames")),
            cadu_bytes=_as_int(normalized.get("cadu_bytes")),
            image_count=_as_int(normalized.get("image_count")),
            peak_snr_db=_as_optional_float(normalized.get("peak_snr_db")),
        )
    elif stored_result == "FAILED":
        evaluated = classify(
            returncode=1,
            frames=_as_int(normalized.get("frames")),
            cadu_bytes=_as_int(normalized.get("cadu_bytes")),
            image_count=_as_int(normalized.get("image_count")),
            peak_snr_db=_as_optional_float(normalized.get("peak_snr_db")),
        )
    else:
        evaluated = classify(
            returncode=0,
            output_path=normalized.get("output_path"),
            frames=_as_int(normalized.get("frames")),
            cadu_bytes=_as_int(normalized.get("cadu_bytes")),
            image_count=_as_int(normalized.get("image_count")),
            peak_snr_db=_as_optional_float(normalized.get("peak_snr_db")),
        )

        # Bewaar een expliciet NO SYNC-resultaat wanneer oude logs geen stdout bevatten.
        if (
            stored_result == "NO SYNC"
            and evaluated["result"] == "NO SIGNAL"
            and evaluated["image_count"] == 0
            and evaluated["cadu_bytes"] == 0
        ):
            evaluated["result"] = "NO SYNC"
            evaluated["detail"] = str(
                normalized.get("detail") or "Signaal gezien, maar geen decoder-lock"
            )

    normalized.update(evaluated)
    normalized["stored_result"] = stored_result or None
    normalized["result_reclassified"] = bool(
        stored_result and stored_result != evaluated["result"]
    )
    return normalized
