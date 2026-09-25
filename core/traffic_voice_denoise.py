"""Per-listener native denoisers. Never receives or modifies the ATIS input."""
from __future__ import annotations
import ctypes as ct
import ctypes.util
from pathlib import Path
import threading
import time
import numpy as np

ENGINES = ('off', 'speex', 'rnnoise')
RUNTIME = Path(__file__).resolve().parents[1] / 'data/audio-comparison/runtime'
_status_lock = threading.RLock()
_status_cache = {}
_status_until = 0.0
_errors = {}


def library(name, runtime=RUNTIME):
    local = runtime / 'lib' / f'lib{name}.so'
    path = str(local) if local.is_file() else ct.util.find_library(name)
    if not path:
        raise OSError(f'{name} is not installed')
    return ct.CDLL(path)


def report_error(engine, error):
    with _status_lock:
        if error is None:
            _errors.pop(engine, None)
        else:
            _errors[engine] = str(error)


def capabilities():
    global _status_cache, _status_until
    with _status_lock:
        if time.monotonic() >= _status_until:
            result = {'off': {'available': True}}
            for engine in ENGINES[1:]:
                try:
                    processor = Denoiser(engine)
                    processor.close()
                    result[engine] = {'available': True}
                except (OSError, ValueError, RuntimeError, AttributeError) as error:
                    result[engine] = {'available': False, 'error': str(error)}
            _status_cache = result
            _status_until = time.monotonic() + 30
        return {key: {**value, 'last_error': _errors.get(key)} for key, value in _status_cache.items()}


class Resampler3:
    """Continuous 16/48 kHz FIR conversion; no per-packet subprocess or reset."""
    def __init__(self):
        n = np.arange(63) - 31
        h = np.sinc(n / 3) / 3 * np.kaiser(63, 8.0)
        self.h = h / h.sum()
        self.up_tail = np.zeros(62)
        self.down_tail = np.zeros(62)

    def up(self, samples):
        data = np.zeros(len(samples) * 3)
        data[::3] = samples
        joined = np.concatenate((self.up_tail, data))
        self.up_tail = joined[-62:].copy()
        return np.convolve(joined, self.h * 3, mode='valid').astype(np.float32)

    def down(self, samples):
        joined = np.concatenate((self.down_tail, samples))
        self.down_tail = joined[-62:].copy()
        return np.convolve(joined, self.h, mode='valid')[::3]


class Denoiser:
    def __init__(self, engine, runtime=RUNTIME):
        if engine not in ENGINES[1:]:
            raise ValueError('Unknown denoiser')
        self.engine = engine
        self.lock = threading.RLock()
        self.state = None
        self.pending = b''
        self.lib = library('speexdsp' if engine == 'speex' else 'rnnoise', runtime)
        lib = self.lib
        if engine == 'speex':
            lib.speex_preprocess_state_init.argtypes = [ct.c_int, ct.c_int]
            lib.speex_preprocess_state_init.restype = ct.c_void_p
            lib.speex_preprocess_ctl.argtypes = [ct.c_void_p, ct.c_int, ct.c_void_p]
            lib.speex_preprocess_ctl.restype = ct.c_int
            lib.speex_preprocess_run.argtypes = [ct.c_void_p, ct.POINTER(ct.c_int16)]
            lib.speex_preprocess_run.restype = ct.c_int
            lib.speex_preprocess_state_destroy.argtypes = [ct.c_void_p]
            lib.speex_preprocess_state_destroy.restype = None
            self.state = lib.speex_preprocess_state_init(320, 16000)
            self.frame_bytes = 640
            try:
                if not self.state: raise RuntimeError('SpeexDSP allocation failed')
                for request, value in ((0, 1), (2, 0), (18, -12)):
                    setting = ct.c_int(value)
                    if lib.speex_preprocess_ctl(self.state, request, ct.byref(setting)):
                        raise RuntimeError('SpeexDSP setting failed')
            except Exception:
                self.close()
                raise
        else:
            lib.rnnoise_create.argtypes = [ct.c_void_p]
            lib.rnnoise_create.restype = ct.c_void_p
            lib.rnnoise_destroy.argtypes = [ct.c_void_p]
            lib.rnnoise_destroy.restype = None
            lib.rnnoise_get_frame_size.argtypes = []
            lib.rnnoise_get_frame_size.restype = ct.c_int
            lib.rnnoise_process_frame.argtypes = [ct.c_void_p, ct.POINTER(ct.c_float), ct.POINTER(ct.c_float)]
            lib.rnnoise_process_frame.restype = ct.c_float
            if lib.rnnoise_get_frame_size() != 480:
                raise RuntimeError('Unsupported RNNoise frame size')
            self.state = lib.rnnoise_create(None)
            if not self.state: raise RuntimeError('RNNoise allocation failed')
            self.frame_bytes = 320
            self.resampler = Resampler3()

    def process(self, pcm):
        with self.lock:
            if not self.state: raise RuntimeError('Denoiser closed')
            self.pending += pcm
            out = bytearray()
            while len(self.pending) >= self.frame_bytes:
                block, self.pending = self.pending[:self.frame_bytes], self.pending[self.frame_bytes:]
                samples = np.frombuffer(block, dtype='<i2')
                if self.engine == 'speex':
                    samples = samples.astype(np.int16)
                    self.lib.speex_preprocess_run(self.state, samples.ctypes.data_as(ct.POINTER(ct.c_int16)))
                else:
                    samples = self.resampler.up(samples)
                    ptr = samples.ctypes.data_as(ct.POINTER(ct.c_float))
                    self.lib.rnnoise_process_frame(self.state, ptr, ptr)
                    samples = self.resampler.down(samples)
                if not np.isfinite(samples).all():
                    raise RuntimeError('Non-finite denoiser output')
                out.extend(np.clip(np.rint(samples), -32768, 32767).astype('<i2').tobytes())
            return bytes(out)

    def close(self):
        with self.lock:
            if self.state:
                if self.engine == 'speex': self.lib.speex_preprocess_state_destroy(self.state)
                else: self.lib.rnnoise_destroy(self.state)
                self.state = None
            self.pending = b''
