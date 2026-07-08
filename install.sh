#!/bin/bash
set -e
BASE=$HOME/SatStation
mkdir -p "$BASE"
cp -r . "$BASE"
python3 -m venv "$BASE/venv"
echo "Installatie voltooid in $BASE"
