#!/usr/bin/env python3
"""Single-owner live HF backend for the SDRCC HF Amateur Monitor.

The backend opens one RTL-SDR through ``librtlsdr`` and derives spectrum,
waterfall and browser audio from that same IQ stream.  It never stops or
starts services and never reserves a receiver; those authorities remain with
the caller and Receiver Manager.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
import ctypes
import ctypes.util
import math
import struct
import threading
import time
from typing import Any, Iterator

import numpy as np


VERSION = "0.56.0d"
BACKEND_ID = "librtlsdr_qbranch_dsp"
SAMPLE_RATE_HZ = 240_000
AUDIO_SAMPLE_RATE_HZ = 16_000
READ_BYTES = 32_768
FFT_SIZE = 2048
SPECTRUM_POINTS = 256
MAX_WATERFALL_ROWS = 72
MAX_AUDIO_CHUNKS = 128
MAX_AUDIO_CLIENTS = 3


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _wav_header(sample_rate: int) -> bytes:
    return b"".join((
        b"RIFF", struct.pack("<I", 0xFFFFFFFF), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16),
        b"data", struct.pack("<I", 0xFFFFFFFF - 36),
    ))


def _design_lowpass(cutoff_hz: float, sample_rate_hz: float, taps: int) -> np.ndarray:
    if taps < 3 or taps % 2 == 0:
        raise ValueError("FIR tap count must be an odd integer >= 3")
    normalized = float(cutoff_hz) / float(sample_rate_hz)
    positions = np.arange(taps, dtype=np.float64) - ((taps - 1) / 2.0)
    coefficients = 2.0 * normalized * np.sinc(2.0 * normalized * positions)
    coefficients *= np.hamming(taps)
    coefficients /= np.sum(coefficients)
    return coefficients.astype(np.float32)


class _FIRDecimator:
    def __init__(self, taps: np.ndarray, factor: int) -> None:
        self.taps = np.asarray(taps, dtype=np.float32)
        self.factor = int(factor)
        self.state = np.zeros(len(self.taps) - 1, dtype=np.float32)
        self.phase = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        values = np.asarray(samples, dtype=np.float32)
        if values.size == 0:
            return np.empty(0, dtype=np.float32)
        combined = np.concatenate((self.state, values))
        filtered = np.convolve(combined, self.taps, mode="valid").astype(np.float32)
        self.state = combined[-(len(self.taps) - 1):].copy()
        start = (-self.phase) % self.factor
        output = filtered[start::self.factor]
        self.phase = (self.phase + len(filtered)) % self.factor
        return output


class _ComplexFIRFilter:
    def __init__(self, taps: np.ndarray) -> None:
        self.taps = np.asarray(taps, dtype=np.complex64)
        self.state = np.zeros(len(self.taps) - 1, dtype=np.complex64)

    def process(self, samples: np.ndarray) -> np.ndarray:
        values = np.asarray(samples, dtype=np.complex64)
        combined = np.concatenate((self.state, values))
        filtered = np.convolve(combined, self.taps, mode="valid").astype(np.complex64)
        self.state = combined[-(len(self.taps) - 1):].copy()
        return filtered


def _design_sideband(sample_rate_hz: int, *, upper: bool) -> np.ndarray:
    taps = 481
    center_hz = 1_850.0 if upper else -1_850.0
    base = _design_lowpass(1_700.0, float(sample_rate_hz), taps).astype(np.complex64)
    positions = np.arange(taps, dtype=np.float64) - ((taps - 1) / 2.0)
    modulation = np.exp(2j * math.pi * center_hz * positions / sample_rate_hz)
    return (base * modulation).astype(np.complex64)


class HFSignalProcessor:
    """Measured IQ to spectrum and 16 kHz mono PCM conversion."""

    def __init__(self, *, center_frequency_hz: int, mode: str,
                 sample_rate_hz: int = SAMPLE_RATE_HZ,
                 squelch_enabled: bool = False,
                 squelch_threshold_dbfs: float = -42.0) -> None:
        self.center_frequency_hz = int(center_frequency_hz)
        self.mode = str(mode).upper()
        self.sample_rate_hz = int(sample_rate_hz)
        if self.sample_rate_hz != SAMPLE_RATE_HZ:
            raise ValueError(f"Radio Receiver backend sample rate must be {SAMPLE_RATE_HZ} Hz")
        if self.mode not in {"LSB", "USB", "CW", "AM", "NFM", "FM", "WFM"}:
            raise ValueError(f"Unsupported Radio Receiver mode: {mode}")
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._first = _FIRDecimator(
            _design_lowpass(8_000.0, self.sample_rate_hz, 161), 5,
        )
        self._second = _FIRDecimator(
            _design_lowpass(3_400.0, self.sample_rate_hz / 5.0, 129), 3,
        )
        self._wfm_audio = _FIRDecimator(
            _design_lowpass(7_200.0, self.sample_rate_hz, 241), 15,
        )
        self._sideband = (
            _ComplexFIRFilter(_design_sideband(self.sample_rate_hz, upper=self.mode == "USB"))
            if self.mode in {"USB", "LSB"} else None
        )
        self._oscillator_phase = 0.0
        self._agc_gain = 1.0
        self._spectrum_average: np.ndarray | None = None
        self._blocks = 0
        self._fm_previous: np.complex64 | None = None
        self.squelch_enabled = bool(squelch_enabled)
        self.squelch_threshold_dbfs = float(squelch_threshold_dbfs)
        self.last_signal_dbfs: float | None = None
        self.squelch_open = True

    @staticmethod
    def decode_cu8(payload: bytes) -> np.ndarray:
        usable = len(payload) - (len(payload) % 2)
        if usable <= 0:
            return np.empty(0, dtype=np.complex64)
        values = np.frombuffer(payload[:usable], dtype=np.uint8).astype(np.float32)
        values = (values - 127.5) / 127.5
        iq = values[0::2] + (1j * values[1::2])
        iq = iq.astype(np.complex64)
        iq -= np.mean(iq)
        return iq

    def _mix(self, iq: np.ndarray, frequency_hz: float) -> np.ndarray:
        count = len(iq)
        increment = (2.0 * math.pi * float(frequency_hz)) / self.sample_rate_hz
        phase = self._oscillator_phase + increment * np.arange(count, dtype=np.float64)
        mixed = iq * np.exp(-1j * phase).astype(np.complex64)
        self._oscillator_phase = float((self._oscillator_phase + increment * count) % (2.0 * math.pi))
        return mixed

    def _audio_source(self, iq: np.ndarray) -> np.ndarray:
        if self.mode in {"USB", "LSB"}:
            return np.real(self._sideband.process(iq)).astype(np.float32)
        if self.mode == "CW":
            # A carrier tuned to the selected frequency becomes a 700 Hz tone.
            return np.real(self._mix(iq, -700.0)).astype(np.float32)
        if self.mode in {"NFM", "FM", "WFM"}:
            # Shared phase discriminator for monitor-quality mono FM modes.
            # Preserve the previous complex sample so block boundaries do not
            # introduce an audible click or lose phase change.
            if iq.size == 0:
                return np.empty(0, dtype=np.float32)
            previous = self._fm_previous
            self._fm_previous = np.complex64(iq[-1])
            if previous is None:
                pairs = iq[1:] * np.conj(iq[:-1])
                discriminator = np.angle(pairs).astype(np.float32)
                return np.concatenate((np.zeros(1, dtype=np.float32), discriminator))
            first = np.angle(iq[0] * np.conj(previous)).astype(np.float32)
            rest = np.angle(iq[1:] * np.conj(iq[:-1])).astype(np.float32)
            return np.concatenate((np.asarray([first], dtype=np.float32), rest))
        envelope = np.abs(iq).astype(np.float32)
        return envelope - float(np.mean(envelope))

    def update_squelch(self, *, enabled: bool, threshold_dbfs: float) -> None:
        threshold = float(threshold_dbfs)
        if not -65.0 <= threshold <= -10.0:
            raise ValueError("Radio Receiver squelch threshold must be between -65 and -10 dBFS")
        self.squelch_enabled = bool(enabled)
        self.squelch_threshold_dbfs = threshold

    def _audio_pcm(self, iq: np.ndarray) -> bytes:
        rf_rms = float(np.sqrt(np.mean(np.abs(iq).astype(np.float64) ** 2)) + 1e-12)
        self.last_signal_dbfs = 20.0 * math.log10(max(rf_rms, 1e-12))
        self.squelch_open = (
            not self.squelch_enabled
            or self.last_signal_dbfs >= self.squelch_threshold_dbfs
        )
        source = self._audio_source(iq)
        audio = self._wfm_audio.process(source) if self.mode == "WFM" else self._second.process(self._first.process(source))
        if audio.size == 0:
            return b""
        if not self.squelch_open:
            return np.zeros(audio.size, dtype="<i2").tobytes()
        audio -= float(np.mean(audio))
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))) + 1e-9)
        desired = min(24.0, max(0.35, 0.16 / rms))
        self._agc_gain = (0.92 * self._agc_gain) + (0.08 * desired)
        audio = np.tanh(audio * self._agc_gain * 1.4)
        pcm = np.clip(np.rint(audio * 32767.0), -32768, 32767).astype("<i2")
        return pcm.tobytes()

    def _spectrum(self, iq: np.ndarray) -> tuple[list[dict[str, float]], list[float], float]:
        if len(iq) < FFT_SIZE:
            padded = np.zeros(FFT_SIZE, dtype=np.complex64)
            padded[-len(iq):] = iq
            block = padded
        else:
            block = iq[-FFT_SIZE:]
        transformed = np.fft.fftshift(np.fft.fft(block * self._window))
        magnitude = np.abs(transformed) / max(1.0, float(np.sum(self._window)))
        dbfs = (20.0 * np.log10(np.maximum(magnitude, 1e-9))).astype(np.float32)
        if self._spectrum_average is None:
            self._spectrum_average = dbfs
        else:
            self._spectrum_average = (0.72 * self._spectrum_average) + (0.28 * dbfs)
        grouped = self._spectrum_average.reshape(SPECTRUM_POINTS, FFT_SIZE // SPECTRUM_POINTS)
        reduced = np.max(grouped, axis=1)
        frequencies = np.linspace(
            self.center_frequency_hz - (self.sample_rate_hz / 2.0),
            self.center_frequency_hz + (self.sample_rate_hz / 2.0),
            SPECTRUM_POINTS,
            endpoint=False,
        )
        points = [
            {"frequency_hz": round(float(frequency), 1), "dbfs": round(float(level), 2)}
            for frequency, level in zip(frequencies, reduced)
        ]
        row = [round(float(level), 2) for level in reduced]
        return points, row, round(float(np.max(reduced)), 2)

    def process(self, payload: bytes) -> dict[str, Any]:
        iq = self.decode_cu8(payload)
        if iq.size == 0:
            return {"audio_pcm": b"", "spectrum": None}
        self._blocks += 1
        spectrum = self._spectrum(iq) if self._blocks == 1 or self._blocks % 4 == 0 else None
        return {"audio_pcm": self._audio_pcm(iq), "spectrum": spectrum}


class _RtlSdrDevice:
    def __init__(self, *, serial: str, center_frequency_hz: int,
                 sample_rate_hz: int) -> None:
        self.serial = str(serial)
        self.center_frequency_hz = int(center_frequency_hz)
        self.sample_rate_hz = int(sample_rate_hz)
        self.library = self._load_library()
        self.device = ctypes.c_void_p()
        self.index: int | None = None
        self.sampling_mode = "Q_BRANCH_DIRECT" if self.center_frequency_hz < 25_000_000 else "QUADRATURE_TUNER"
        self._configure_signatures()

    @staticmethod
    def _load_library() -> ctypes.CDLL:
        candidates = [ctypes.util.find_library("rtlsdr"), "librtlsdr.so.0", "librtlsdr.so"]
        errors = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return ctypes.CDLL(candidate)
            except OSError as error:
                errors.append(str(error))
        raise RuntimeError("librtlsdr is niet beschikbaar" + (f": {errors[-1]}" if errors else ""))

    def _configure_signatures(self) -> None:
        lib = self.library
        lib.rtlsdr_get_device_count.restype = ctypes.c_uint32
        lib.rtlsdr_get_device_usb_strings.argtypes = [
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        lib.rtlsdr_get_device_usb_strings.restype = ctypes.c_int
        lib.rtlsdr_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32]
        lib.rtlsdr_open.restype = ctypes.c_int
        lib.rtlsdr_close.argtypes = [ctypes.c_void_p]
        lib.rtlsdr_close.restype = ctypes.c_int
        lib.rtlsdr_set_sample_rate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.rtlsdr_set_sample_rate.restype = ctypes.c_int
        lib.rtlsdr_set_center_freq.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.rtlsdr_set_center_freq.restype = ctypes.c_int
        lib.rtlsdr_set_direct_sampling.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.rtlsdr_set_direct_sampling.restype = ctypes.c_int
        lib.rtlsdr_set_tuner_gain_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.rtlsdr_set_tuner_gain_mode.restype = ctypes.c_int
        lib.rtlsdr_get_tuner_gains.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        lib.rtlsdr_get_tuner_gains.restype = ctypes.c_int
        lib.rtlsdr_set_tuner_gain.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.rtlsdr_set_tuner_gain.restype = ctypes.c_int
        lib.rtlsdr_get_tuner_gain.argtypes = [ctypes.c_void_p]
        lib.rtlsdr_get_tuner_gain.restype = ctypes.c_int
        lib.rtlsdr_set_agc_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.rtlsdr_set_agc_mode.restype = ctypes.c_int
        lib.rtlsdr_reset_buffer.argtypes = [ctypes.c_void_p]
        lib.rtlsdr_reset_buffer.restype = ctypes.c_int
        lib.rtlsdr_read_sync.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
        ]
        lib.rtlsdr_read_sync.restype = ctypes.c_int

    def _check(self, result: int, operation: str) -> None:
        if int(result) != 0:
            raise RuntimeError(f"librtlsdr {operation} mislukt (code {int(result)})")

    def available_gains_db(self) -> list[float]:
        count = int(self.library.rtlsdr_get_tuner_gains(self.device, None))
        if count <= 0:
            return []
        gains = (ctypes.c_int * count)()
        returned = int(self.library.rtlsdr_get_tuner_gains(self.device, gains))
        if returned <= 0:
            return []
        return [round(float(gains[index]) / 10.0, 1) for index in range(returned)]

    def set_gain(self, *, gain_mode: str, gain_db: float) -> dict[str, Any]:
        mode = str(gain_mode).strip().lower()
        if mode not in {"auto", "manual"}:
            raise ValueError("Radio Receiver gain mode must be auto or manual")
        if mode == "auto":
            self._check(self.library.rtlsdr_set_tuner_gain_mode(self.device, 0), "automatic tuner gain")
            self._check(self.library.rtlsdr_set_agc_mode(self.device, 1), "digital AGC")
        else:
            self._check(self.library.rtlsdr_set_agc_mode(self.device, 0), "digital AGC off")
            if self.sampling_mode == "QUADRATURE_TUNER":
                self._check(self.library.rtlsdr_set_tuner_gain_mode(self.device, 1), "manual tuner gain")
                self._check(self.library.rtlsdr_set_tuner_gain(
                    self.device, int(round(float(gain_db) * 10.0))
                ), "manual tuner gain value")
            else:
                # Q-branch bypasses the tuner. 'Manual' therefore means fixed
                # direct-sampling ADC gain with RTL digital AGC disabled.
                self._check(self.library.rtlsdr_set_tuner_gain_mode(self.device, 0), "bypassed tuner gain")
        actual = round(float(self.library.rtlsdr_get_tuner_gain(self.device)) / 10.0, 1)
        return {
            "gain_mode": mode,
            "gain_db": float(gain_db),
            "actual_tuner_gain_db": actual,
            "manual_gain_effective": self.sampling_mode == "QUADRATURE_TUNER",
            "digital_agc": mode == "auto",
        }

    def open(self, *, gain_mode: str = "auto", gain_db: float = 28.0) -> dict[str, Any]:
        count = int(self.library.rtlsdr_get_device_count())
        for index in range(count):
            manufacturer = ctypes.create_string_buffer(256)
            product = ctypes.create_string_buffer(256)
            serial = ctypes.create_string_buffer(256)
            result = self.library.rtlsdr_get_device_usb_strings(
                index, manufacturer, product, serial,
            )
            if result == 0 and serial.value.decode("utf-8", errors="replace") == self.serial:
                self.index = index
                break
        if self.index is None:
            raise RuntimeError(f"RTL-SDR met serienummer {self.serial} is niet gevonden")
        self._check(self.library.rtlsdr_open(ctypes.byref(self.device), self.index), "open")
        try:
            self._check(self.library.rtlsdr_set_sample_rate(self.device, self.sample_rate_hz), "sample rate")
            direct = 2 if self.center_frequency_hz < 25_000_000 else 0
            self._check(self.library.rtlsdr_set_direct_sampling(self.device, direct), "sampling mode")
            self._check(self.library.rtlsdr_set_center_freq(self.device, self.center_frequency_hz), "frequency")
            gain_status = self.set_gain(gain_mode=gain_mode, gain_db=gain_db)
            self._check(self.library.rtlsdr_reset_buffer(self.device), "buffer reset")
            gain_status["valid_gains"] = self.available_gains_db()
            return gain_status
        except Exception:
            self.close()
            raise

    def read(self, byte_count: int = READ_BYTES) -> bytes:
        buffer = ctypes.create_string_buffer(int(byte_count))
        read = ctypes.c_int()
        result = self.library.rtlsdr_read_sync(
            self.device, buffer, int(byte_count), ctypes.byref(read),
        )
        self._check(result, "IQ read")
        return bytes(buffer.raw[:max(0, int(read.value))])

    def retune(self, center_frequency_hz: int) -> None:
        """Retune the already-open device without changing its sampling path."""
        target = int(center_frequency_hz)
        direct = target < 25_000_000
        if direct != (self.sampling_mode == "Q_BRANCH_DIRECT"):
            raise RuntimeError("Live retune mag de RTL-SDR sampling mode niet wijzigen")
        self._check(self.library.rtlsdr_set_center_freq(self.device, target), "live frequency")
        self._check(self.library.rtlsdr_reset_buffer(self.device), "live buffer reset")
        self.center_frequency_hz = target

    def close(self) -> None:
        if self.device:
            try:
                self.library.rtlsdr_close(self.device)
            finally:
                self.device = ctypes.c_void_p()


_lock = threading.Condition(threading.RLock())
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_ready_event = threading.Event()
_state = "STOPPED"
_error: str | None = None
_settings: dict[str, Any] = {}
_started_at: str | None = None
_stopped_at: str | None = None
_last_iq_epoch: float | None = None
_last_audio_epoch: float | None = None
_samples_received = 0
_spectrum_points: list[dict[str, float]] = []
_waterfall: deque[list[float]] = deque(maxlen=MAX_WATERFALL_ROWS)
_spectrum_peak_dbfs: float | None = None
_audio_chunks: deque[tuple[int, bytes]] = deque(maxlen=MAX_AUDIO_CHUNKS)
_audio_sequence = 0
_active_audio_clients = 0
_retune_request: dict[str, int] | None = None
_retune_sequence = 0
_retune_completed_id = 0
_retune_error: str | None = None
_rf_request: dict[str, Any] | None = None
_rf_sequence = 0
_rf_completed_id = 0
_rf_error: str | None = None
_signal_dbfs: float | None = None
_squelch_open = True


def validate_runtime() -> dict[str, Any]:
    try:
        library = _RtlSdrDevice._load_library()
        direct = getattr(library, "rtlsdr_set_direct_sampling", None)
        ready = direct is not None
        return {
            "ok": ready,
            "backend": BACKEND_ID,
            "library": str(getattr(library, "_name", "librtlsdr")),
            "direct_sampling_api": ready,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "audio_sample_rate_hz": AUDIO_SAMPLE_RATE_HZ,
            "single_iq_owner": True,
        }
    except Exception as error:  # noqa: BLE001 - runtime capability probe
        return {
            "ok": False,
            "backend": BACKEND_ID,
            "direct_sampling_api": False,
            "error": str(error),
            "single_iq_owner": True,
        }


def _worker(serial: str, center_frequency_hz: int, mode: str,
            gain_mode: str, gain_db: float, squelch_enabled: bool,
            squelch_threshold_dbfs: float) -> None:
    global _state, _error, _last_iq_epoch, _last_audio_epoch
    global _samples_received, _spectrum_points, _waterfall, _spectrum_peak_dbfs, _audio_sequence
    global _retune_request, _retune_completed_id, _retune_error
    global _rf_request, _rf_completed_id, _rf_error, _signal_dbfs, _squelch_open
    device: _RtlSdrDevice | None = None
    try:
        device = _RtlSdrDevice(
            serial=serial,
            center_frequency_hz=center_frequency_hz,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        gain_status = device.open(gain_mode=gain_mode, gain_db=gain_db)
        processor = HFSignalProcessor(
            center_frequency_hz=center_frequency_hz,
            mode=mode,
            sample_rate_hz=SAMPLE_RATE_HZ,
            squelch_enabled=squelch_enabled,
            squelch_threshold_dbfs=squelch_threshold_dbfs,
        )
        with _lock:
            _settings["sampling_mode"] = device.sampling_mode
            _settings.update(gain_status)
            _state = "LISTENING"
            _ready_event.set()
            _lock.notify_all()
        while not _stop_event.is_set():
            request = None
            with _lock:
                if _retune_request is not None:
                    request = dict(_retune_request)
                    _retune_request = None
            if request is not None:
                try:
                    target = int(request["frequency_hz"])
                    device.retune(target)
                    processor = HFSignalProcessor(
                        center_frequency_hz=target,
                        mode=mode,
                        sample_rate_hz=SAMPLE_RATE_HZ,
                        squelch_enabled=bool(_settings.get("squelch_enabled", False)),
                        squelch_threshold_dbfs=float(_settings.get("squelch_threshold_dbfs", -42.0)),
                    )
                    with _lock:
                        _settings["center_frequency_hz"] = target
                        _last_iq_epoch = None
                        _last_audio_epoch = None
                        _spectrum_points = []
                        _waterfall = deque(maxlen=MAX_WATERFALL_ROWS)
                        _spectrum_peak_dbfs = None
                        _audio_chunks.clear()
                        _retune_error = None
                        _retune_completed_id = int(request["id"])
                        _lock.notify_all()
                except Exception as error:  # noqa: BLE001 - fail closed through watchdog
                    with _lock:
                        _retune_error = str(error)
                        _retune_completed_id = int(request["id"])
                        _lock.notify_all()
                    raise RuntimeError(f"HF live retune mislukt: {error}") from error
            rf_request = None
            with _lock:
                if _rf_request is not None:
                    rf_request = dict(_rf_request)
                    _rf_request = None
            if rf_request is not None:
                try:
                    gain_status = device.set_gain(
                        gain_mode=str(rf_request["gain_mode"]),
                        gain_db=float(rf_request["gain_db"]),
                    )
                    processor.update_squelch(
                        enabled=bool(rf_request["squelch_enabled"]),
                        threshold_dbfs=float(rf_request["squelch_threshold_dbfs"]),
                    )
                    with _lock:
                        _settings.update(gain_status)
                        _settings["squelch_enabled"] = bool(rf_request["squelch_enabled"])
                        _settings["squelch_threshold_dbfs"] = float(rf_request["squelch_threshold_dbfs"])
                        _rf_error = None
                        _rf_completed_id = int(rf_request["id"])
                        _lock.notify_all()
                except Exception as error:  # noqa: BLE001
                    with _lock:
                        _rf_error = str(error)
                        _rf_completed_id = int(rf_request["id"])
                        _lock.notify_all()
                    raise RuntimeError(f"HF RF-instellingen mislukt: {error}") from error
            payload = device.read()
            if not payload:
                raise RuntimeError("librtlsdr leverde geen IQ-data")
            processed = processor.process(payload)
            now = time.time()
            with _lock:
                _last_iq_epoch = now
                _samples_received += len(payload) // 2
                pcm = processed["audio_pcm"]
                _signal_dbfs = processor.last_signal_dbfs
                _squelch_open = processor.squelch_open
                if pcm:
                    _audio_sequence += 1
                    _audio_chunks.append((_audio_sequence, pcm))
                    _last_audio_epoch = now
                spectrum = processed["spectrum"]
                if spectrum is not None:
                    points, row, peak = spectrum
                    _spectrum_points = points
                    _waterfall.append(row)
                    _spectrum_peak_dbfs = peak
                _lock.notify_all()
    except Exception as error:  # noqa: BLE001 - reflected in fail-closed state
        with _lock:
            _error = str(error)
            _state = "ERROR"
            _ready_event.set()
            _lock.notify_all()
    finally:
        if device is not None:
            device.close()
        with _lock:
            if _stop_event.is_set():
                _state = "STOPPED"
            _lock.notify_all()


def start(*, serial: str, receiver_id: str, center_frequency_hz: int,
          band: str, mode: str, gain_mode: str = "auto", gain_db: float = 28.0,
          squelch_enabled: bool = False, squelch_threshold_dbfs: float = -42.0,
          startup_timeout_seconds: float = 6.0) -> dict[str, Any]:
    global _thread, _state, _error, _settings, _started_at, _stopped_at
    global _last_iq_epoch, _last_audio_epoch, _samples_received
    global _spectrum_points, _waterfall, _spectrum_peak_dbfs, _audio_sequence
    global _retune_request, _retune_sequence, _retune_completed_id, _retune_error
    global _rf_request, _rf_sequence, _rf_completed_id, _rf_error, _signal_dbfs, _squelch_open
    capability = validate_runtime()
    if not capability["ok"]:
        raise RuntimeError(capability.get("error") or "HF backend is niet beschikbaar")
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("HF backend draait al")
        _stop_event.clear()
        _ready_event.clear()
        _state = "STARTING"
        _error = None
        _started_at = _now()
        _stopped_at = None
        _last_iq_epoch = None
        _last_audio_epoch = None
        _samples_received = 0
        _spectrum_points = []
        _waterfall = deque(maxlen=MAX_WATERFALL_ROWS)
        _spectrum_peak_dbfs = None
        _audio_chunks.clear()
        _audio_sequence = 0
        _retune_request = None
        _retune_sequence = 0
        _retune_completed_id = 0
        _retune_error = None
        _rf_request = None
        _rf_sequence = 0
        _rf_completed_id = 0
        _rf_error = None
        _signal_dbfs = None
        _squelch_open = True
        _settings = {
            "receiver_id": str(receiver_id),
            "serial": str(serial),
            "center_frequency_hz": int(center_frequency_hz),
            "band": str(band),
            "mode": str(mode).upper(),
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "audio_sample_rate_hz": AUDIO_SAMPLE_RATE_HZ,
            "sampling_mode": "PENDING",
            "gain_mode": str(gain_mode).lower(),
            "gain_db": float(gain_db),
            "squelch_enabled": bool(squelch_enabled),
            "squelch_threshold_dbfs": float(squelch_threshold_dbfs),
        }
        _thread = threading.Thread(
            target=_worker,
            args=(
                str(serial), int(center_frequency_hz), str(mode).upper(),
                str(gain_mode).lower(), float(gain_db), bool(squelch_enabled),
                float(squelch_threshold_dbfs),
            ),
            daemon=True,
            name="sdrcc-hf-monitor",
        )
        _thread.start()
    if not _ready_event.wait(float(startup_timeout_seconds)):
        stop()
        raise RuntimeError("HF backend gaf geen startbevestiging")
    status = get_status()
    if status["state"] != "LISTENING":
        stop()
        raise RuntimeError(status.get("error") or "HF backend kon niet starten")
    return status


def retune(*, center_frequency_hz: int, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Ask the existing IQ-owner thread to retune the open RTL-SDR."""
    global _retune_request, _retune_sequence, _retune_error
    target = int(center_frequency_hz)
    if target <= 0:
        raise ValueError("HF-frequentie moet groter zijn dan nul")
    with _lock:
        if _state != "LISTENING" or _thread is None or not _thread.is_alive():
            raise RuntimeError("HF backend luistert niet")
        current = int(_settings.get("center_frequency_hz") or 0)
        if (current < 25_000_000) != (target < 25_000_000):
            raise RuntimeError("Live retune mag de RTL-SDR sampling mode niet wijzigen")
        if target == current:
            return get_status()
        if _retune_request is not None:
            raise RuntimeError("Er staat al een HF live-retune klaar")
        _retune_sequence += 1
        request_id = _retune_sequence
        _retune_error = None
        _retune_request = {"id": request_id, "frequency_hz": target}
        _lock.notify_all()
        deadline = time.monotonic() + float(timeout_seconds)
        while _retune_completed_id < request_id:
            if _state not in {"LISTENING"}:
                raise RuntimeError(_error or "HF backend stopte tijdens live retune")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if _retune_request and int(_retune_request.get("id") or 0) == request_id:
                    _retune_request = None
                raise RuntimeError("HF backend bevestigde live retune niet tijdig")
            _lock.wait(min(0.25, remaining))
        if _retune_error:
            raise RuntimeError(_retune_error)
    return get_status()


def update_rf_controls(*, gain_mode: str, gain_db: float, squelch_enabled: bool,
                       squelch_threshold_dbfs: float, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Apply gain and squelch inside the existing IQ-owner worker."""
    global _rf_request, _rf_sequence, _rf_error
    mode = str(gain_mode).strip().lower()
    if mode not in {"auto", "manual"}:
        raise ValueError("Radio Receiver gain mode must be auto or manual")
    threshold = float(squelch_threshold_dbfs)
    if not -65.0 <= threshold <= -10.0:
        raise ValueError("Radio Receiver squelch threshold must be between -65 and -10 dBFS")
    with _lock:
        if _state != "LISTENING" or _thread is None or not _thread.is_alive():
            raise RuntimeError("HF backend luistert niet")
        if _rf_request is not None:
            raise RuntimeError("Er staat al een HF RF-instelling klaar")
        _rf_sequence += 1
        request_id = _rf_sequence
        _rf_error = None
        _rf_request = {
            "id": request_id,
            "gain_mode": mode,
            "gain_db": float(gain_db),
            "squelch_enabled": bool(squelch_enabled),
            "squelch_threshold_dbfs": threshold,
        }
        _lock.notify_all()
        deadline = time.monotonic() + float(timeout_seconds)
        while _rf_completed_id < request_id:
            if _state != "LISTENING":
                raise RuntimeError(_error or "HF backend stopte tijdens RF-instelling")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if _rf_request and int(_rf_request.get("id") or 0) == request_id:
                    _rf_request = None
                raise RuntimeError("HF backend bevestigde RF-instelling niet tijdig")
            _lock.wait(min(0.25, remaining))
        if _rf_error:
            raise RuntimeError(_rf_error)
    return get_status()


def stop() -> dict[str, Any]:
    global _thread, _state, _stopped_at, _last_iq_epoch, _last_audio_epoch
    global _spectrum_points, _waterfall, _spectrum_peak_dbfs, _retune_request
    global _rf_request, _signal_dbfs, _squelch_open
    with _lock:
        thread = _thread
        _stop_event.set()
        if thread is not None and thread.is_alive():
            _state = "STOPPING"
    if thread is not None and thread.is_alive():
        thread.join(timeout=4.0)
    with _lock:
        if thread is not None and thread.is_alive():
            raise RuntimeError("HF backend kon niet tijdig stoppen")
        _thread = None
        _state = "STOPPED"
        _stopped_at = _now()
        _last_iq_epoch = None
        _last_audio_epoch = None
        _spectrum_points = []
        _waterfall = deque(maxlen=MAX_WATERFALL_ROWS)
        _spectrum_peak_dbfs = None
        _audio_chunks.clear()
        _retune_request = None
        _rf_request = None
        _signal_dbfs = None
        _squelch_open = True
        _lock.notify_all()
    return get_status()


def get_status() -> dict[str, Any]:
    capability = validate_runtime()
    with _lock:
        now = time.time()
        iq_age = now - _last_iq_epoch if _last_iq_epoch else None
        audio_age = now - _last_audio_epoch if _last_audio_epoch else None
        spectrum_available = bool(_state == "LISTENING" and _spectrum_points and iq_age is not None and iq_age < 3.0)
        audio_available = bool(_state == "LISTENING" and _audio_chunks and audio_age is not None and audio_age < 3.0)
        return {
            "ok": capability["ok"] and _state != "ERROR",
            "version": VERSION,
            "backend": BACKEND_ID,
            "available": capability["ok"],
            "state": _state,
            "error": _error or capability.get("error"),
            "settings": dict(_settings),
            "rf_controls": {
                "gain_mode": str(_settings.get("gain_mode") or "auto"),
                "gain_db": float(_settings.get("gain_db") or 0.0),
                "actual_tuner_gain_db": _settings.get("actual_tuner_gain_db"),
                "manual_gain_effective": bool(_settings.get("manual_gain_effective")),
                "digital_agc": bool(_settings.get("digital_agc", True)),
                "valid_gains": list(_settings.get("valid_gains") or []),
                "squelch_enabled": bool(_settings.get("squelch_enabled", False)),
                "squelch_threshold_dbfs": float(_settings.get("squelch_threshold_dbfs", -42.0)),
                "signal_dbfs": round(float(_signal_dbfs), 2) if _signal_dbfs is not None else None,
                "squelch_open": bool(_squelch_open),
            },
            "started_at": _started_at,
            "stopped_at": _stopped_at,
            "samples_received": _samples_received,
            "last_iq_age_seconds": round(iq_age, 2) if iq_age is not None else None,
            "spectrum": {
                "available": spectrum_available,
                "source": "measured_librtlsdr_iq" if spectrum_available else None,
                "points": list(_spectrum_points) if spectrum_available else [],
                "waterfall": list(_waterfall) if spectrum_available else [],
                "peak_dbfs": _spectrum_peak_dbfs if spectrum_available else None,
                "sample_rate_hz": SAMPLE_RATE_HZ,
            },
            "audio": {
                "available": audio_available,
                "stream_url": "/api/hf-monitor/audio-stream" if audio_available else None,
                "sample_rate_hz": AUDIO_SAMPLE_RATE_HZ,
                "active_clients": _active_audio_clients,
                "max_clients": MAX_AUDIO_CLIENTS,
                "last_audio_age_seconds": round(audio_age, 2) if audio_age is not None else None,
            },
            "capability": capability,
            "generated_at": _now(),
        }


class LiveWavStream:
    def __init__(self) -> None:
        global _active_audio_clients
        with _lock:
            if _state != "LISTENING":
                raise RuntimeError("HF-ontvanger draait niet")
            if _active_audio_clients >= MAX_AUDIO_CLIENTS:
                raise RuntimeError("Maximum aantal HF-audioclients bereikt")
            _active_audio_clients += 1
            self._next_sequence = _audio_sequence + 1
        self._closed = False
        self._header_sent = False

    def __iter__(self) -> "LiveWavStream":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        if not self._header_sent:
            self._header_sent = True
            return _wav_header(AUDIO_SAMPLE_RATE_HZ)
        deadline = time.monotonic() + 12.0
        with _lock:
            while not self._closed:
                for sequence, chunk in _audio_chunks:
                    if sequence >= self._next_sequence:
                        self._next_sequence = sequence + 1
                        return chunk
                if _state not in {"STARTING", "LISTENING"}:
                    self.close()
                    raise StopIteration
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise StopIteration
                _lock.wait(min(1.0, remaining))
        raise StopIteration

    def close(self) -> None:
        global _active_audio_clients
        if self._closed:
            return
        with _lock:
            self._closed = True
            _active_audio_clients = max(0, _active_audio_clients - 1)
            _lock.notify_all()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def stream_wav() -> Iterator[bytes]:
    return LiveWavStream()
