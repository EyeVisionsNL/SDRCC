#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(realpath "${1:?SDRCC project path required}")"
MODE="${2:---install}"
PYTHON="$PROJECT_ROOT/venv/bin/python"
case "$MODE" in --install|--refresh|--check) ;; *) echo 'Unknown mode'; exit 2;; esac
[[ -x "$PYTHON" ]] || { echo 'ISS SSTV decoder needs the SDRCC virtual environment'; exit 1; }

decoder_ready(){
  "$PYTHON" - <<'PY'
import importlib.metadata
import sstv

assert importlib.metadata.version("sstv") == "0.1.0"
assert hasattr(sstv.Mode, "ROBOT_36")
assert callable(sstv.decode_from_wav)
PY
}

if decoder_ready; then
  echo 'PASS: ISS SSTV decoder 0.1.0 ready'
  exit 0
fi

if [[ "$MODE" == --check ]]; then
  echo 'ISS SSTV decoder missing or incompatible; expected sstv==0.1.0'
  exit 1
fi

PROJECT_USER="$(stat -c '%U' "$PROJECT_ROOT")"
if [[ "$EUID" == 0 && "$PROJECT_USER" != root ]]; then
  runuser -u "$PROJECT_USER" -- "$PYTHON" -m pip install \
    --disable-pip-version-check --no-input --only-binary=:all: 'sstv==0.1.0'
else
  "$PYTHON" -m pip install --disable-pip-version-check --no-input \
    --only-binary=:all: 'sstv==0.1.0'
fi

decoder_ready || { echo 'FAIL: installed ISS SSTV decoder did not pass its import check'; exit 1; }
echo 'PASS: ISS SSTV decoder 0.1.0 installed'
