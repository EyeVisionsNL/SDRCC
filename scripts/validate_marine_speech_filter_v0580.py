#!/usr/bin/env python3
"""Validate audible filtering, stream continuity, mode bypass and ATIS isolation."""
from pathlib import Path
import math
import struct
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import traffic_voice_audio as audio


def tone(hz):
    return b''.join(struct.pack('<h', round(10000 * math.sin(2 * math.pi * hz * n / 16000)))
                    for n in range(16000))


def rms(pcm):
    samples = [x[0] for x in struct.iter_unpack('<h', pcm)][1000:]
    return math.sqrt(sum(x*x for x in samples) / len(samples))


def main():
    for hz, minimum, maximum in ((1000, -0.1, 0.1), (3000, -3.2, -2.8), (6000, -60, -40)):
        source = tone(hz)
        result = audio.MarineSpeechFilter(16000).process(source)
        db = 20 * math.log10(rms(result) / rms(source))
        assert minimum < db < maximum, (hz, db)
        print(f'PASS: {hz} Hz response {db:.2f} dB')
    source = tone(4500)
    whole = audio.MarineSpeechFilter(16000).process(source)
    split_filter = audio.MarineSpeechFilter(16000)
    split = b''.join(split_filter.process(source[i:i+514]) for i in range(0, len(source), 514))
    assert whole == split
    split_filter.reset()
    assert split_filter.process(source) == whole
    print('PASS: chunk boundaries are continuous; reset reproduces fresh filter')

    settings = {'selected_mode': 'marine_ais', 'backend': {'audio_sample_rate_hz': 16000}}
    payload = b''.join(struct.pack('<f', x[0] / 32767) for x in struct.iter_unpack('<h', source))
    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def bind(self, *args): pass
        def settimeout(self, *args): pass
        def recvfrom(self, *args):
            if getattr(self, 'sent', False): raise OSError('end of test stream')
            self.sent = True
            return payload, ('127.0.0.1', 1)

    with patch.object(audio, 'ensure_listener'), patch.object(audio.config, 'get_traffic_voice_config', return_value=settings):
        stream = audio.LiveWavStream()
        try:
            assert next(stream).startswith(b'RIFF')
            with patch.object(audio.socket, 'socket', return_value=FakeSocket()), patch.object(audio.traffic_voice_atis, 'observe_float32') as observer:
                audio._listen()
                observer.assert_called_once_with(payload)
            raw = audio.float32_to_pcm16(payload)
            assert audio._chunks[-1][1] == raw
            assert next(stream) == audio.MarineSpeechFilter(16000).process(raw)
            settings['selected_mode'] = 'airband_adsb'
            stream._mode_check_at = 0
            audio._sequence += 1
            audio._chunks.append((audio._sequence, raw))
            assert next(stream) == raw
            settings['selected_mode'] = 'marine_ais'
            stream._mode_check_at = 0
            audio._sequence += 2  # Simulate queue overrun.
            audio._chunks.append((audio._sequence, raw))
            assert next(stream) == audio.MarineSpeechFilter(16000).process(raw)
        finally:
            stream.close()
        assert audio._active_clients == 0
    print('PASS: ATIS input unchanged; only marine playback filtered; airband bypass and mode reset work')


if __name__ == '__main__':
    main()
    from validate_traffic_voice_atis_v0550d import validate_decoder
    validate_decoder()
