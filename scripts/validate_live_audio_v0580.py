#!/usr/bin/env python3
"""Live processing isolation, resampling, all presets and optional native regression."""
from pathlib import Path
import argparse
import sys
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import traffic_voice_audio as audio, traffic_voice_denoise as dsp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path)
    args = parser.parse_args()
    rng = np.random.default_rng(2)
    samples = (rng.normal(size=32000)*800).astype('<i2')
    pcm = samples.tobytes()
    # The rate converter retains its history across arbitrary frame boundaries.
    whole = dsp.Resampler3()
    expected = whole.down(whole.up(samples))
    split = dsp.Resampler3()
    actual = np.concatenate([split.down(split.up(samples[i:i+160])) for i in range(0, len(samples), 160)])
    assert np.allclose(expected, actual)
    tone = np.sin(2*np.pi*1000*np.arange(16000)/16000)*10000
    resampler = dsp.Resampler3()
    result = resampler.down(resampler.up(tone))
    gain = np.std(result[1000:])/np.std(tone[1000:])
    assert 0.98 < gain < 1.02
    print('PASS: continuous 16/48 kHz converter preserves speech-band level and chunk continuity')

    settings = {'selected_mode': 'marine_ais', 'backend': {'audio_sample_rate_hz': 16000}}
    with patch.object(audio, 'ensure_listener'), patch.object(audio.config, 'get_traffic_voice_config', return_value=settings):
        def feed(stream):
            audio._sequence += 1
            audio._chunks.append((audio._sequence, pcm))
            return next(stream)
        for mode in ('marine_ais', 'airband_adsb'):
            settings['selected_mode'] = mode
            for preset in audio.SPEECH_FILTERS:
                stream = audio.LiveWavStream(preset, 'off', mode)
                try:
                    next(stream)
                    output = feed(stream)
                    if preset == 'off': assert output == pcm
                    else: assert output == audio.MarineSpeechFilter(16000, audio.SPEECH_FILTERS[preset]).process(pcm)
                finally: stream.close()
            stream = audio.LiveWavStream('strong', 'speex', mode)
            next(stream)
            with patch.object(dsp, 'Denoiser', side_effect=OSError('missing')):
                stream._reset_processor()
                assert feed(stream) == audio.MarineSpeechFilter(16000, 2400).process(pcm)
            stream.close()
        print('PASS: both modes support all speech filters, off is exact, missing denoiser falls back')
        settings['selected_mode'] = 'marine_ais'
        stream = audio.LiveWavStream('off', 'off', 'marine_ais')
        next(stream)
        settings['selected_mode'] = 'airband_adsb'
        try: feed(stream)
        except StopIteration: pass
        else: raise AssertionError('Old-mode stream kept processing')
        assert audio._active_clients == 0
        print('PASS: mode mismatch releases client, preventing use of another mode\'s preferences')
        settings['selected_mode'] = 'marine_ais'
        from unittest.mock import Mock
        broken = Mock()
        broken.process.side_effect = RuntimeError('simulated native error')
        with patch.object(dsp, 'Denoiser', return_value=broken):
            stream = audio.LiveWavStream('off', 'rnnoise', 'marine_ais')
            next(stream)
            assert feed(stream) == pcm
            assert stream._processor is None
            stream.close()
        assert audio._active_clients == 0
        print('PASS: runtime denoiser failure falls back to original audio and releases native state')

    if args.runtime:
        for engine in ('speex', 'rnnoise'):
            def process(chunks):
                state = dsp.Denoiser(engine, args.runtime)
                try: return b''.join(state.process(chunk) for chunk in chunks)
                finally: state.close()
            whole = process([pcm])
            chunks = process([pcm[i:i+514] for i in range(0, len(pcm), 514)])
            assert whole == chunks
            assert len(whole) == len(pcm)
            assert process([bytes(64000)]) == bytes(64000)
            original_factory = dsp.Denoiser
            with patch.object(audio, 'ensure_listener'), patch.object(audio.config, 'get_traffic_voice_config', return_value=settings), patch.object(dsp, 'Denoiser', side_effect=lambda name: original_factory(name, args.runtime)):
                for mode in ('marine_ais', 'airband_adsb'):
                    settings['selected_mode'] = mode
                    for preset in audio.SPEECH_FILTERS:
                        stream = audio.LiveWavStream(preset, engine, mode)
                        try:
                            next(stream)
                            output = feed(stream)
                            assert len(output) == len(pcm)
                            assert audio._chunks[-1][1] == pcm
                        finally: stream.close()
            print(f'PASS: {engine} real native streaming, arbitrary chunks, silence, all presets and both modes')
    else:
        print('SKIP: native libraries (pass --runtime)')

if __name__ == '__main__': main()
