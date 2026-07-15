from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional
import json
import math


DIAGNOSTICS_DIRNAME = "diagnostics"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_clean(dict(payload)), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _inventory(output_path: Path) -> dict[str, Any]:
    image_extensions = {".png", ".jpg", ".jpeg"}
    images = []
    cadu_files = []
    product_files = []
    logs = []

    if output_path.exists():
        for item in output_path.rglob("*"):
            if not item.is_file() or DIAGNOSTICS_DIRNAME in item.parts:
                continue
            try:
                size = item.stat().st_size
            except OSError:
                size = 0
            relative = str(item.relative_to(output_path)).replace("\\", "/")
            entry = {"path": relative, "bytes": size}
            suffix = item.suffix.lower()
            if suffix in image_extensions:
                images.append(entry)
            elif suffix == ".cadu":
                cadu_files.append(entry)
            elif suffix in {".cbor", ".json", ".product"} or "product" in item.name.lower():
                product_files.append(entry)
            elif suffix in {".log", ".txt"} or "log" in item.name.lower():
                logs.append(entry)

    return {
        "images": images,
        "image_count": len(images),
        "cadu_files": cadu_files,
        "cadu_bytes": sum(item["bytes"] for item in cadu_files),
        "product_files": product_files,
        "logs": logs,
    }


def calculate_quality(
    *,
    result: Optional[str],
    max_elevation: Optional[float],
    min_elevation: Optional[float],
    peak_snr_db: Optional[float],
    frames: Optional[int],
    image_count: Optional[int],
) -> dict[str, Any]:
    result_value = str(result or "UNKNOWN").upper()
    result_points = {
        "SUCCESS": 30,
        "NO IMAGES": 18,
        "NO SYNC": 8,
        "NO SIGNAL": 0,
        "FAILED": 0,
        "CANCELLED": 0,
    }.get(result_value, 0)

    images = max(0, _integer(image_count))
    image_points = min(25, images * 2)

    snr = max(0.0, _number(peak_snr_db))
    snr_points = min(20, round((snr / 15.0) * 20))

    elevation = max(0.0, _number(max_elevation))
    threshold = max(0.0, _number(min_elevation))
    if elevation <= 0:
        elevation_points = 0
    elif elevation <= threshold:
        elevation_points = round((elevation / max(threshold, 1.0)) * 7)
    else:
        elevation_points = min(
            15,
            7 + round(((elevation - threshold) / max(90.0 - threshold, 1.0)) * 8),
        )

    frame_count = max(0, _integer(frames))
    frame_points = min(10, round((frame_count / 500.0) * 10))

    score = int(max(0, min(100, result_points + image_points + snr_points + elevation_points + frame_points)))
    if score >= 85:
        grade = "EXCELLENT"
    elif score >= 70:
        grade = "GOOD"
    elif score >= 50:
        grade = "FAIR"
    elif score >= 25:
        grade = "POOR"
    else:
        grade = "FAILED"

    return {
        "score": score,
        "grade": grade,
        "components": {
            "result": {"points": result_points, "maximum": 30, "value": result_value},
            "images": {"points": image_points, "maximum": 25, "value": images},
            "snr": {"points": snr_points, "maximum": 20, "value_db": peak_snr_db},
            "elevation": {
                "points": elevation_points,
                "maximum": 15,
                "max_elevation": max_elevation,
                "min_elevation": min_elevation,
            },
            "frames": {"points": frame_points, "maximum": 10, "value": frame_count},
        },
        "method": "SDRCC Mission Quality v1",
    }


def write_mission_diagnostics(
    *,
    mission: Mapping[str, Any],
    pass_data: Optional[Mapping[str, Any]] = None,
    rf: Optional[Mapping[str, Any]] = None,
    analysis: Optional[Mapping[str, Any]] = None,
    live_returncode: Optional[int] = None,
    live_command: Optional[list[str]] = None,
    decode_data: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    mission_data = dict(mission or {})
    pass_payload = dict(pass_data or {})
    rf_payload = dict(rf or {})
    analysis_payload = dict(analysis or {})
    output_value = mission_data.get("output_path") or pass_payload.get("output_path")
    if not output_value:
        return {"available": False, "reason": "Geen output_path"}

    output_path = Path(str(output_value)).expanduser()
    diagnostics_dir = output_path / DIAGNOSTICS_DIRNAME
    products = _inventory(output_path)

    min_elevation = mission_data.get("min_elevation", pass_payload.get("min_elevation"))
    max_elevation = mission_data.get("max_elevation", pass_payload.get("max_elevation"))
    peak_snr = analysis_payload.get("peak_snr_db", mission_data.get("peak_snr_db"))
    frames = analysis_payload.get("frames", mission_data.get("frames"))
    images = max(
        _integer(analysis_payload.get("image_count")),
        _integer(mission_data.get("image_count")),
        _integer(products.get("image_count")),
    )
    result = analysis_payload.get("result", mission_data.get("result"))

    quality = calculate_quality(
        result=result,
        max_elevation=max_elevation,
        min_elevation=min_elevation,
        peak_snr_db=peak_snr,
        frames=frames,
        image_count=images,
    )

    telemetry = {
        "peak_snr_db": peak_snr,
        "frames": frames,
        "cadu_bytes": max(
            _integer(analysis_payload.get("cadu_bytes")),
            _integer(mission_data.get("cadu_bytes")),
            _integer(products.get("cadu_bytes")),
        ),
        "image_count": images,
        "duration_seconds": mission_data.get("duration_seconds"),
        "started_at": mission_data.get("started_at"),
        "ended_at": mission_data.get("ended_at"),
    }
    receiver = {
        "receiver": mission_data.get("receiver"),
        "receiver_id": mission_data.get("receiver_id"),
        "receiver_serial": mission_data.get("receiver_serial"),
        "frequency": mission_data.get("frequency", pass_payload.get("frequency")),
        "frequency_mhz": mission_data.get("frequency_mhz", pass_payload.get("frequency_mhz")),
        "sample_rate": mission_data.get("sample_rate", pass_payload.get("sample_rate")),
        "gain_mode": mission_data.get("gain_mode", rf_payload.get("gain_mode")),
        "gain_db": mission_data.get("gain_db", rf_payload.get("gain_db")),
        "dc_block": mission_data.get("dc_block", rf_payload.get("dc_block")),
        "iq_swap": mission_data.get("iq_swap", rf_payload.get("iq_swap")),
    }
    satdump = {
        "pipeline": mission_data.get("pipeline", pass_payload.get("pipeline")),
        "live": {"returncode": live_returncode, "command": live_command},
        "decode": {
            "attempted": (decode_data or {}).get("attempted", False),
            "returncode": (decode_data or {}).get("returncode"),
            "command": (decode_data or {}).get("command"),
            "cadu_file": (decode_data or {}).get("cadu_file"),
            "products_dir": (decode_data or {}).get("products_dir"),
            "log_file": (decode_data or {}).get("log_file"),
        },
        "result": result,
        "detail": analysis_payload.get("detail", mission_data.get("detail")),
        "error": analysis_payload.get("error", mission_data.get("error")),
    }
    diagnostics = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "mission": mission_data,
        "pass": {
            "name": pass_payload.get("name", mission_data.get("satellite")),
            "start": pass_payload.get("start"),
            "maximum": pass_payload.get("maximum"),
            "end": pass_payload.get("end"),
            "min_elevation": min_elevation,
            "max_elevation": max_elevation,
            "azimuth": pass_payload.get("azimuth", mission_data.get("azimuth")),
        },
        "telemetry": telemetry,
        "receiver": receiver,
        "satdump": satdump,
        "products": products,
        "quality": quality,
    }

    _write_json(diagnostics_dir / "diagnostics.json", diagnostics)
    _write_json(diagnostics_dir / "telemetry.json", telemetry)
    _write_json(diagnostics_dir / "receiver.json", receiver)
    _write_json(diagnostics_dir / "satdump.json", satdump)
    _write_json(diagnostics_dir / "products.json", products)
    _write_json(diagnostics_dir / "quality.json", quality)

    return {
        "available": True,
        "directory": str(diagnostics_dir),
        "diagnostics_file": str(diagnostics_dir / "diagnostics.json"),
        "quality_score": quality["score"],
        "quality_grade": quality["grade"],
        "quality": quality,
        "products": products,
    }


def read_mission_diagnostics(output_path: Optional[str | Path]) -> dict[str, Any]:
    if not output_path:
        return {"available": False}
    diagnostics_dir = Path(str(output_path)).expanduser() / DIAGNOSTICS_DIRNAME
    diagnostics_file = diagnostics_dir / "diagnostics.json"
    if not diagnostics_file.exists():
        return {"available": False, "directory": str(diagnostics_dir)}
    try:
        payload = json.loads(diagnostics_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"available": False, "error": str(error), "directory": str(diagnostics_dir)}
    return {"available": True, "directory": str(diagnostics_dir), **payload}
