#!/usr/bin/env python3
from pathlib import Path
import ast
import json
import tempfile
import wave
import numpy as np
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core import iss_voice, iss_voice_audio

checks=[]
def check(ok,msg):
    if not ok: raise AssertionError(msg)
    print(f"PASS: {msg}")

v=iss_voice.validate_config(); check(v["ok"],"ISS Voice config validates")
c=v["config"]
check(c["offline_demodulation_enabled"] is True,"offline demodulation enabled")
check(c["execution_enabled"] is False,"automatic execution remains disabled")
source=(ROOT/'core/iss_voice_audio.py').read_text()
check('systemctl' not in source,"audio module contains no systemctl authority")
check('receiver_manager' not in source,"audio module contains no receiver authority")
check('numpy' in source and 'wave' in source,"NumPy and stdlib wave backend present")
check('scipy' not in source and 'soundfile' not in source,"no SciPy or soundfile dependency")
check('np.angle' in source,"quadrature FM discriminator present")
check('deemphasis' in source,"de-emphasis present")
check('/api/iss-voice/demodulate' in (ROOT/'dashboard/app.py').read_text(),"explicit offline demodulation endpoint present")

# Synthetic 1 s FM tone at current configured rates, stored within a temporary
# mission under the real recordings root so path-boundary validation is tested.
mission='validator_audio_test'
directory=iss_voice_audio.RECORDINGS_ROOT/mission
directory.mkdir(parents=True,exist_ok=True)
try:
    rf=int(c['rf_sample_rate_hz']); audio=int(c['audio_sample_rate_hz'])
    t=np.arange(rf,dtype=np.float64)/rf
    message=np.sin(2*np.pi*1000*t)
    phase=np.cumsum(2*np.pi*3000*message/rf)
    iq=np.exp(1j*phase)
    raw=np.empty(rf*2,dtype=np.uint8)
    raw[0::2]=np.clip(np.real(iq)*127.5+127.5,0,255).astype(np.uint8)
    raw[1::2]=np.clip(np.imag(iq)*127.5+127.5,0,255).astype(np.uint8)
    (directory/'recording.iq').write_bytes(raw.tobytes())
    result=iss_voice_audio.demodulate_mission(mission,c)
    check(result['ok'],"synthetic IQ demodulation succeeds")
    check(result['audio_sample_rate_hz']==audio,"WAV sample rate correct")
    check(abs(result['audio_duration_seconds']-1.0)<0.01,"WAV duration correct")
    with wave.open(str(directory/'audio.wav'),'rb') as wav:
        check(wav.getnchannels()==1,"WAV is mono")
        check(wav.getsampwidth()==2,"WAV is 16-bit PCM")
        check(wav.getframerate()==audio,"WAV header sample rate correct")
    check((directory/'demodulation.json').is_file(),"demodulation metadata written")
finally:
    import shutil; shutil.rmtree(directory,ignore_errors=True)
print('\nISS Voice offline audio demodulation validation PASS')
