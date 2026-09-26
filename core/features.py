#!/usr/bin/env python3
"""Optional SDRCC feature selection.

Missing configuration intentionally means all features are enabled so existing
installations retain their current behaviour after an update.
"""
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_CONFIG = PROJECT_ROOT / "config" / "features.yaml"
DEFAULT_FEATURES = {
    "satellite": True,
    "traffic_voice": True,
    "radio_receiver": True,
}

def get_features():
    features = dict(DEFAULT_FEATURES)
    if not FEATURES_CONFIG.exists():
        return features
    data = yaml.safe_load(FEATURES_CONFIG.read_text(encoding="utf-8")) or {}
    configured = data.get("features", {}) if isinstance(data, dict) else {}
    if isinstance(configured, dict):
        for name in features:
            if name in configured:
                features[name] = bool(configured[name])
    return features

def feature_enabled(name):
    return bool(get_features().get(name, True))
