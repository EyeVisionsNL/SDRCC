#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_rtlsdr_airband_auto_gain.py <input-rtlsdr.cpp>")
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
old = """    r = rtlsdr_set_tuner_gain_mode(rtl, 1);\n    r |= rtlsdr_set_tuner_gain(rtl, ngain);"""
new = """    if (dev_data->gain < 0) {\n        r = rtlsdr_set_tuner_gain_mode(rtl, 0);\n    } else {\n        r = rtlsdr_set_tuner_gain_mode(rtl, 1);\n        r |= rtlsdr_set_tuner_gain(rtl, ngain);\n    }"""
if old not in s:
    raise SystemExit("expected manual-gain block not found exactly once")
if s.count(old) != 1:
    raise SystemExit(f"expected one manual-gain block, found {s.count(old)}")
s = s.replace(old, new, 1)
old_log = '        log(LOG_INFO, "Device #%d: gain set to %0.2f dB\\n", dev_data->index, (float)rtlsdr_get_tuner_gain(rtl) / 10.f);'
new_log = '''        if (dev_data->gain < 0)\n            log(LOG_INFO, "Device #%d: automatic tuner gain enabled\\n", dev_data->index);\n        else\n            log(LOG_INFO, "Device #%d: gain set to %0.2f dB\\n", dev_data->index, (float)rtlsdr_get_tuner_gain(rtl) / 10.f);'''
if old_log not in s:
    raise SystemExit("expected gain log line not found")
s = s.replace(old_log, new_log, 1)
p.write_text(s, encoding="utf-8")
print(f"patched {p}")
