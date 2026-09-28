#!/usr/bin/env python3
"""Check pre-demodulation filtering without changing station configuration."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config, receiver_registry, traffic_voice


def main():
    original = config.load_traffic_voice()
    assignments = config.get_receiver_assignments()
    receivers = receiver_registry.get_receivers()
    get_receiver = receiver_registry.get_receiver

    def bound_receiver(receiver_id):
        receiver = get_receiver(receiver_id)
        return {**receiver, "serial": "FILTER_TEST"} if receiver else None
    for mode_id in traffic_voice.MODE_ORDER:
        for tuning in ("fixed", "scan"):
            for opened in (False, True):
                payload = deepcopy(original)
                settings = payload["traffic_voice"]
                settings["selected_mode"] = mode_id
                settings["backend"]["open_squelch"] = opened
                mode = settings["modes"][mode_id]
                mode["tuning_mode"] = tuning
                for channel in mode["channels"]:
                    channel["scan_enabled"] = True
                context = receiver_registry.resolve_id(assignments[mode["context_plugin"]])
                voice = next(item["id"] for item in receivers if item["id"] != context)
                with (
                    patch.object(config, "load_traffic_voice", return_value=payload),
                    patch.object(config, "get_receiver_assignments", return_value={**assignments, "traffic_voice": voice}),
                    patch.object(receiver_registry, "get_receiver", side_effect=bound_receiver),
                ):
                    rendered = traffic_voice.render_rtlsdr_airband_config()
                if mode_id == "marine_ais":
                    assert rendered.count("bandwidth = 15000;") == 1
                    assert traffic_voice.MARINE_CHANNEL_BANDWIDTH_HZ < settings["backend"]["audio_sample_rate_hz"]
                else:
                    assert "bandwidth =" not in rendered
                if opened:
                    assert "squelch_snr_threshold = 0.0;" in rendered
                assert 'type = "udp_stream";' in rendered
                assert f"dest_port = {settings['backend']['audio_port']};" in rendered
                print(f"PASS: {mode_id}, {tuning}, open_squelch={opened}")
    assert config.load_traffic_voice() == original


if __name__ == "__main__":
    main()
