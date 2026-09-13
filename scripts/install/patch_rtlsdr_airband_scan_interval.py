#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_rtlsdr_airband_scan_interval.py <rtl_airband.cpp>")
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")

old_globals = """bool multiple_output_threads = false;\nbool log_scan_activity = false;\nchar* stats_filepath = NULL;"""
new_globals = """bool multiple_output_threads = false;\nbool log_scan_activity = false;\nint scan_interval_ms = 200;\nchar* stats_filepath = NULL;"""
if s.count(old_globals) != 1:
    raise SystemExit(f"expected one scan globals block, found {s.count(old_globals)}")
s = s.replace(old_globals, new_globals, 1)

old_loop = """    while (!do_exit) {\n        SLEEP(200);\n        if (dev->channels[0].axcindicate == NO_SIGNAL) {"""
new_loop = """    while (!do_exit) {\n        SLEEP(scan_interval_ms);\n        if (dev->channels[0].axcindicate == NO_SIGNAL) {"""
if s.count(old_loop) != 1:
    raise SystemExit(f"expected one scan controller sleep block, found {s.count(old_loop)}")
s = s.replace(old_loop, new_loop, 1)

old_parser = """        if (root.exists(\"log_scan_activity\") && (bool)root[\"log_scan_activity\"] == true)\n            log_scan_activity = true;\n        if (root.exists(\"stats_filepath\"))\n            stats_filepath = strdup(root[\"stats_filepath\"]);"""
new_parser = """        if (root.exists(\"log_scan_activity\") && (bool)root[\"log_scan_activity\"] == true)\n            log_scan_activity = true;\n        if (root.exists(\"scan_interval_ms\")) {\n            scan_interval_ms = (int)root[\"scan_interval_ms\"];\n            if (scan_interval_ms < 100 || scan_interval_ms > 500 || scan_interval_ms % 50 != 0) {\n                cerr << \"Configuration error: scan_interval_ms must be 100..500 ms in 50 ms steps\\n\";\n                error();\n            }\n        }\n        if (root.exists(\"stats_filepath\"))\n            stats_filepath = strdup(root[\"stats_filepath\"]);"""
if s.count(old_parser) != 1:
    raise SystemExit(f"expected one global config parser block, found {s.count(old_parser)}")
s = s.replace(old_parser, new_parser, 1)

p.write_text(s, encoding="utf-8")
print(f"patched {p}: configurable scan_interval_ms 100..500")
