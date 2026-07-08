#!/usr/bin/env python3
from pathlib import Path
import yaml

cfg=Path(__file__).parent.parent/"config"/"station.yaml"
data=yaml.safe_load(cfg.read_text())

import sys
cmd=sys.argv[1] if len(sys.argv)>1 else "help"

if cmd=="status":
    print("SatStation v0.1")
    print("Locatie:",data["station"]["location"])
    print("Satellieten:")
    for s in data["satellites"]:
        print(" -",s)
elif cmd=="help":
    print("Gebruik: satstation.py status")
else:
    print("Onbekend commando")
