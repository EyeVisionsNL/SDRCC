#!/usr/bin/env python3
"""Exercise offline comparison, optional-library failure and native DSP if supplied."""
import argparse
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import wave

import numpy as np
import compare_marine_audio as compare
from core.traffic_voice_audio import _wav_header


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path)
    args = parser.parse_args()
    rng = np.random.default_rng(12)
    time = np.arange(32000) / compare.RATE
    pcm = (2000*np.sin(2*np.pi*700*time) + rng.normal(0, 600, len(time))).astype('<i2').tobytes()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(compare, 'load_library', side_effect=OSError('dependency absent')):
            report = compare.compare(pcm, root, root/'missing')
        assert not any(value['ok'] for value in report['results'].values())
        assert not (root/'03_strong_speex.wav').exists()
        assert compare.read_wav(root/'01_original.wav') == pcm + bytes(3200)
        assert (root/'02_strong.wav').is_file()
        print('PASS: missing native libraries retain original/Strong and report unavailable candidates honestly')
        with wave.open(str(root/'bad.wav'), 'wb') as output:
            output.setnchannels(2); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(pcm)
        try: compare.read_wav(root/'bad.wav')
        except ValueError: pass
        else: raise AssertionError('Stereo accepted')
        print('PASS: invalid input format rejected')

        class Response:
            def __init__(self, content=b'{"selected_mode": "marine_ais"}'):
                self.raw = BytesIO(content)
            def read(self, *args): return self.raw.read(*args)
            def json(self): return {'selected_mode': 'marine_ais'}
            def __enter__(self): return self
            def __exit__(self, *args): self.raw.close()
        # Two seconds is enough for this internal test (CLI requires >=5).
        with patch.object(compare, 'urlopen', side_effect=[Response(), Response(_wav_header(16000)+pcm)]) as get:
            assert compare.record(2) == pcm
            assert get.call_args_list[1].args[0].endswith('speech_filter=off')
        with patch.object(compare, 'urlopen', side_effect=[Response(), Response(_wav_header(16000)+pcm[:100])]):
            try: compare.record(2)
            except RuntimeError: pass
            else: raise AssertionError('Truncated stream accepted')
        print('PASS: recorder reads unfiltered PCM and detects interrupted streams')

        project = root/'project'; project.mkdir(); (project/'VERSION').write_text('0.58.0-r2\n')
        helper = compare.ROOT/'scripts/install/prepare_audio_comparison.sh'
        assert subprocess.run(['bash', str(helper), str(project), '--refresh']).returncode == 0
        assert not (project/'data').exists()
        assert subprocess.run(['bash', str(helper), str(project), '--check'], capture_output=True).returncode == 1
        assert not (project/'data').exists()
        print('PASS: dependency refresh skips non-opted-in stations; check mode is read-only')

        if args.runtime:
            native = root/'native'; native.mkdir()
            report = compare.compare(pcm, native, args.runtime)
            assert all(value['ok'] for value in report['results'].values()), report
            for name in ('03_strong_speex', '04_strong_rnnoise'):
                output = compare.read_wav(native/(name+'.wav'))
                assert len(output) == len(pcm) + 3200
                assert any(output)
            for processor in (compare.speex, compare.rnnoise):
                silence = processor(bytes(64000), args.runtime)
                assert max(abs(np.frombuffer(silence, '<i2').astype(float))) <= 1
                short = processor(pcm[:642], args.runtime)
                assert len(short) == 642
            print('PASS: real SpeexDSP and RNNoise process audio, silence and partial frames at the correct sample rates')
        else:
            print('SKIP: native DSP tests (supply --runtime for installed libraries)')

if __name__ == '__main__': main()
