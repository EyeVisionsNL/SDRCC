#!/usr/bin/env bash
# Shared live/offline audio libraries; never changes SDR receiver services.
set -euo pipefail
PROJECT_ROOT="$(realpath "${1:?SDRCC project path required}")"
MODE="${2:---install}"
RUNTIME="$PROJECT_ROOT/data/audio-comparison/runtime"
RNNOISE_COMMIT="904a876dce1f9ab8860c0a5000ed151f9f6eef58"
MODEL="rnnoise_data-0b50c45.tar.gz"
MODEL_SHA="4ac81c5c0884ec4bd5907026aaae16209b7b76cd9d7f71af582094a2f98f4b43"
case "$MODE" in --install|--refresh|--check) ;; *) echo 'Unknown mode'; exit 2;; esac
[[ -f "$PROJECT_ROOT/VERSION" ]] || { echo 'Not an SDRCC project'; exit 2; }
# --refresh remains a compatibility option for older updater helpers.
if [[ "$MODE" == --refresh && ! -f "$RUNTIME/BUILD-PROVENANCE" ]]; then exit 0; fi
runtime_ready(){
  [[ -f "$RUNTIME/BUILD-PROVENANCE" ]] || return 1
  grep -Fxq "rnnoise_commit=$RNNOISE_COMMIT" "$RUNTIME/BUILD-PROVENANCE" || return 1
  grep -Fxq "model_sha256=$MODEL_SHA" "$RUNTIME/BUILD-PROVENANCE" || return 1
  command -v ffmpeg >/dev/null || return 1
  python3 - "$RUNTIME" <<'PY'
import ctypes, ctypes.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
try:
    speex = ctypes.util.find_library('speexdsp')
    if not speex: raise OSError('SpeexDSP missing')
    ctypes.CDLL(speex).speex_preprocess_run
    ctypes.CDLL(str(root / 'lib/librnnoise.so')).rnnoise_process_frame
except (OSError, AttributeError):
    raise SystemExit(1)
PY
}
if runtime_ready; then echo 'PASS: audio processing dependencies ready'; exit 0; fi
if [[ "$MODE" == --check ]]; then echo 'Audio comparison dependencies missing'; exit 1; fi
as_root(){ if [[ "$EUID" == 0 ]]; then "$@"; else sudo "$@"; fi; }
as_root apt-get update
as_root apt-get install -y libspeexdsp1 ffmpeg git curl ca-certificates build-essential
mkdir -p "$(dirname "$RUNTIME")"
WORK="$(mktemp -d)"
STAGE="$(mktemp -d "$(dirname "$RUNTIME")/runtime-build.XXXXXX")"
cleanup(){ rm -rf "$WORK" "$STAGE"; }
trap cleanup EXIT
# Commit and model checksum are fixed. No moving-main build or network inference.
git -C "$WORK" init -q
git -C "$WORK" fetch -q --depth 1 https://github.com/xiph/rnnoise.git "$RNNOISE_COMMIT"
git -C "$WORK" checkout -q --detach FETCH_HEAD
[[ "$(git -C "$WORK" rev-parse HEAD)" == "$RNNOISE_COMMIT" ]]
curl -fL --retry 2 --connect-timeout 15 --max-time 180 \
  "https://media.xiph.org/rnnoise/models/$MODEL" -o "$WORK/$MODEL"
printf '%s  %s\n' "$MODEL_SHA" "$WORK/$MODEL" | sha256sum -c -
tar --no-same-owner -xzf "$WORK/$MODEL" -C "$WORK"
mkdir -p "$STAGE/lib" "$STAGE/licenses"
# Portable reference build using upstream RNNOISE_SOURCES, without CPU-specific flags.
(cd "$WORK" && cc -O2 -fPIC -shared -DRNNOISE_BUILD -Iinclude -Isrc \
  src/denoise.c src/rnn.c src/pitch.c src/kiss_fft.c src/celt_lpc.c \
  src/nnet.c src/nnet_default.c src/parse_lpcnet_weights.c \
  src/rnnoise_data.c src/rnnoise_tables.c -o "$STAGE/lib/librnnoise.so" -lm)
cp "$WORK/COPYING" "$STAGE/licenses/RNNoise-COPYING"
printf 'rnnoise_commit=%s\nmodel_sha256=%s\nspeex_package=%s\n' \
  "$RNNOISE_COMMIT" "$MODEL_SHA" "$(dpkg-query -W -f='${Version}' libspeexdsp1)" > "$STAGE/BUILD-PROVENANCE"
python3 - "$STAGE/lib/librnnoise.so" <<'PY'
import ctypes, sys
lib = ctypes.CDLL(sys.argv[1])
lib.rnnoise_create.argtypes = [ctypes.c_void_p]
lib.rnnoise_create.restype = ctypes.c_void_p
lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
state = lib.rnnoise_create(None)
if not state: raise SystemExit('RNNoise model could not load')
lib.rnnoise_destroy(state)
PY
# Only replace an old runtime after the complete new build passes its smoke test.
if [[ -d "$RUNTIME" ]]; then mv "$RUNTIME" "$STAGE/previous-runtime"; fi
mv "$STAGE" "$RUNTIME"
if [[ "$EUID" == 0 ]]; then chown -R "$(stat -c '%u:%g' "$PROJECT_ROOT")" "$PROJECT_ROOT/data/audio-comparison"; fi
echo 'PASS: audio libraries installed; receiver settings and ATIS unchanged'
