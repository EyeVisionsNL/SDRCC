#!/usr/bin/env python3
"""Record one unfiltered browser stream and compare offline speech denoisers.

Never opens an SDR or changes receiver settings. Native denoisers are loaded
only when a comparison is requested, not by the SDRCC dashboard.
"""
from __future__ import annotations
import argparse
import ctypes as ct
import ctypes.util
from datetime import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import wave
from urllib.request import urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.traffic_voice_audio import MarineSpeechFilter

RATE = 16000
RUNTIME = ROOT / 'data/audio-comparison/runtime'


def load_library(name: str, runtime: Path):
    local = runtime / 'lib' / f'lib{name}.so'
    candidate = str(local) if local.is_file() else ct.util.find_library(name)
    if not candidate:
        raise RuntimeError(f'{name} unavailable: run ./install.sh --audio-comparison')
    return ct.CDLL(candidate)


def speex(pcm: bytes, runtime: Path, suppress_db: int = -12) -> bytes:
    lib = load_library('speexdsp', runtime)
    lib.speex_preprocess_state_init.argtypes = [ct.c_int, ct.c_int]
    lib.speex_preprocess_state_init.restype = ct.c_void_p
    lib.speex_preprocess_ctl.argtypes = [ct.c_void_p, ct.c_int, ct.c_void_p]
    lib.speex_preprocess_ctl.restype = ct.c_int
    lib.speex_preprocess_run.argtypes = [ct.c_void_p, ct.POINTER(ct.c_int16)]
    lib.speex_preprocess_run.restype = ct.c_int
    lib.speex_preprocess_state_destroy.argtypes = [ct.c_void_p]
    lib.speex_preprocess_state_destroy.restype = None
    state = lib.speex_preprocess_state_init(320, RATE)
    if not state:
        raise RuntimeError('SpeexDSP state allocation failed')
    out = bytearray()
    try:
        # Denoise on, AGC off; VAD stays disabled (SpeexDSP default).
        for request, value in ((0, 1), (2, 0), (18, suppress_db)):
            parameter = ct.c_int(value)
            if lib.speex_preprocess_ctl(state, request, ct.byref(parameter)) != 0:
                raise RuntimeError('SpeexDSP rejected a setting')
        for offset in range(0, len(pcm), 640):
            block = pcm[offset:offset+640]
            samples = np.frombuffer(block.ljust(640, b'\0'), dtype='<i2').astype(np.int16)
            lib.speex_preprocess_run(state, samples.ctypes.data_as(ct.POINTER(ct.c_int16)))
            out.extend(samples.astype('<i2').tobytes()[:len(block)])
    finally:
        lib.speex_preprocess_state_destroy(state)
    return bytes(out)


def resample(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-f', 's16le', '-ar', str(source_rate), '-ac', '1', '-i', 'pipe:0',
        '-f', 's16le', '-ar', str(target_rate), '-ac', '1', 'pipe:1'],
        input=pcm, capture_output=True, timeout=120, check=True)
    return result.stdout


def rnnoise(pcm: bytes, runtime: Path) -> bytes:
    lib = load_library('rnnoise', runtime)
    lib.rnnoise_create.argtypes = [ct.c_void_p]
    lib.rnnoise_create.restype = ct.c_void_p
    lib.rnnoise_destroy.argtypes = [ct.c_void_p]
    lib.rnnoise_destroy.restype = None
    lib.rnnoise_process_frame.argtypes = [ct.c_void_p, ct.POINTER(ct.c_float), ct.POINTER(ct.c_float)]
    lib.rnnoise_process_frame.restype = ct.c_float
    lib.rnnoise_get_frame_size.argtypes = []
    lib.rnnoise_get_frame_size.restype = ct.c_int
    if lib.rnnoise_get_frame_size() != 480:
        raise RuntimeError('Unsupported RNNoise frame size')
    data = resample(pcm, RATE, 48000)
    state = lib.rnnoise_create(None)  # Embedded, pinned model; no network inference.
    if not state:
        raise RuntimeError('RNNoise state allocation failed')
    out = bytearray()
    try:
        for offset in range(0, len(data), 960):
            block = data[offset:offset+960]
            # RNNoise expects float samples on the PCM16 scale, NOT [-1, 1].
            samples = np.frombuffer(block.ljust(960, b'\0'), dtype='<i2').astype(np.float32)
            pointer = samples.ctypes.data_as(ct.POINTER(ct.c_float))
            lib.rnnoise_process_frame(state, pointer, pointer)
            if not np.isfinite(samples).all():
                raise RuntimeError('RNNoise returned non-finite audio')
            out.extend(np.clip(np.rint(samples), -32768, 32767).astype('<i2').tobytes()[:len(block)])
    finally:
        lib.rnnoise_destroy(state)
    return resample(bytes(out), 48000, RATE)[:len(pcm)].ljust(len(pcm), b'\0')


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, 'NONE'):
            raise ValueError('Input must be uncompressed mono PCM16 WAV at 16000 Hz')
        if source.getnframes() > RATE * 300:
            raise ValueError('Maximum input duration is 300 seconds')
        return source.readframes(source.getnframes())


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm)


def record(seconds: int) -> bytes:
    # Explicit off bypasses the browser speech filter, irrespective of its saved selection.
    with urlopen('http://127.0.0.1:8080/api/traffic-voice', timeout=5) as status:
        mode = json.load(status).get('selected_mode')
    if mode != 'marine_ais':
        raise RuntimeError('Select Marine Traffic before recording')
    url = 'http://127.0.0.1:8080/api/traffic-voice/audio-stream?speech_filter=off'
    with urlopen(url, timeout=20) as response:
        header = response.read(44)
        if (len(header) != 44 or header[:4] != b'RIFF' or header[8:16] != b'WAVEfmt '
                or header[36:40] != b'data' or struct.unpack_from('<HHI', header, 20) != (1, 1, RATE)
                or struct.unpack_from('<H', header, 34)[0] != 16):
            raise ValueError('Unexpected SDRCC audio stream format')
        pcm = bytearray()
        wanted = seconds * RATE * 2
        deadline = time.monotonic() + seconds + 30
        while len(pcm) < wanted:
            if time.monotonic() > deadline:
                raise RuntimeError('Recording timed out; check that Traffic Voice is running')
            chunk = response.read(min(8192, wanted - len(pcm)))
            if not chunk:
                raise RuntimeError('Audio stream ended before the recording completed')
            pcm.extend(chunk)
    return bytes(pcm)


def compare(pcm: bytes, output: Path, runtime: Path) -> dict:
    if not pcm or len(pcm) % 2:
        raise ValueError('Empty or incomplete PCM input')
    # Keep a common 100 ms silent tail, allowing denoiser latency to drain.
    padded = pcm + bytes(RATE // 10 * 2)
    write_wav(output / '01_original.wav', padded)
    strong = MarineSpeechFilter(RATE, 2400).process(padded)
    write_wav(output / '02_strong.wav', strong)
    report = {'sample_rate_hz': RATE, 'speech_filter_hz': 2400, 'speex_max_noise_attenuation_db': -12,
              'input_seconds': len(pcm) / (2 * RATE), 'silent_tail_ms': 100,
              'note': 'No volume normalization. Small algorithmic delays remain. Listen for lost words, not just quietness.',
              'results': {}}
    for name, processor in (('03_strong_speex', speex), ('04_strong_rnnoise', rnnoise)):
        started = time.monotonic()
        try:
            # Denoise BEFORE the same Strong filter in both candidates.
            result = MarineSpeechFilter(RATE, 2400).process(processor(padded, runtime))
            if len(result) != len(padded):
                raise RuntimeError('Denoiser changed the output length')
            write_wav(output / (name + '.wav'), result)
            report['results'][name] = {'ok': True, 'processing_seconds': round(time.monotonic()-started, 3)}
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            report['results'][name] = {'ok': False, 'error': str(error)}
    provenance = runtime / 'BUILD-PROVENANCE'
    report['runtime'] = provenance.read_text() if provenance.exists() else 'System libraries; no private build provenance'
    (output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', type=Path)
    group.add_argument('--record', type=int, metavar='SECONDS')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--runtime', type=Path, default=RUNTIME)
    args = parser.parse_args()
    if args.record is not None and not 5 <= args.record <= 300:
        parser.error('--record must be between 5 and 300 seconds')
    output = args.output or ROOT / 'data/audio-comparison' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True, exist_ok=False)
    try:
        if args.record:
            print(f'Recording {args.record} seconds from Traffic Voice; keep Voice running.', flush=True)
        pcm = record(args.record) if args.record else read_wav(args.input)
        report = compare(pcm, output, args.runtime)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print(f'Comparison saved: {output}')
    failed = [name for name, result in report['results'].items() if not result['ok']]
    for name in failed:
        print(f'UNAVAILABLE: {name}: {report["results"][name]["error"]}', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
