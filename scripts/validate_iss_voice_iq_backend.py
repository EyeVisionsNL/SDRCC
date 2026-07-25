#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core import execution_factory, iss_voice, plugin_registry
from core.wideband_iq_recorder import build_spec, build_command, describe_capture, validate_runtime

def check(ok, message):
    if not ok: raise AssertionError(message)
    print("PASS:", message)

def main():
    cfg=iss_voice.validate_config(); check(cfg["ok"], "ISS Voice config validates")
    check(cfg["config"].get("execution_backend_enabled") is True, "IQ backend enabled")
    check(cfg["config"].get("execution_enabled") is False, "mission execution remains disabled")
    plugin=plugin_registry.get_plugin("iss_voice"); check(plugin.get("executor")=="wideband_iq", "registry resolves wideband_iq executor")
    adapter=execution_factory.get_adapter("iss_voice"); desc=adapter.describe().as_dict()
    check(desc["metadata_valid"], "wideband IQ adapter metadata valid")
    plan=adapter.build_plan({"target":"ISS (ZARYA)"}).as_dict()
    check(plan["target_type"]=="wideband_iq_capture", "plan targets wideband IQ capture")
    check(plan["executable"] is False and plan["read_only"] is True, "plan remains fail-closed")
    spec=build_spec(mission_id="validator",receiver_serial="24006572",frequency_hz=437800000,sample_rate_hz=240000,duration_seconds=10)
    cmd=build_command(spec); check(cmd[0]=="rtl_sdr" and "2400000" in cmd, "bounded rtl_sdr command uses exact sample count")
    info=describe_capture(spec); check(info["expected_bytes"]==4800000, "CU8 expected size calculated")
    runtime=validate_runtime()
    print(("PASS" if runtime["ok"] else "INFO") + ": rtl_sdr runtime " + ("available" if runtime["ok"] else "not available in validation host"))
    print("\nISS Voice wideband IQ backend validation PASS")
if __name__=="__main__": main()
