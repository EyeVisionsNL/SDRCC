# SDRCC v0.55.0b — Marine Voice execution

## Scope

This release enables only **Marine Voice + AIS**. **Airband Voice + ADS-B**
remains configured but non-executable. The station continues to use exactly
two RTL-SDR receivers.

## Runtime contract

- Receiver Registry owns immutable receiver identity and serials.
- config/station.yaml:assignments remains the only persistent role authority.
- On every Marine start, the voice receiver is derived as the one receiver
  opposite the current AIS assignment.
- Start stops ADS-B, ensures AIS is active, writes only the derived
  traffic_voice assignment and starts sdrcc-traffic-voice.service.
- Any failed start restores the preceding assignment and all three observed
  service states.
- Start persists the preceding Traffic Voice assignment and all three observed
  service states in `data/state/traffic_voice_session.json` before changing the
  topology.
- Stop first stops Traffic Voice and then restores the exact preceding
  assignment and AIS/ADS-B service states. ADS-B is restarted only when it was
  active before Start; an initially inactive service remains inactive.
- A restore failure retains the session state so recovery can be retried and
  never silently reports a successful Stop.
- Traffic Voice holds no Receiver Manager reservation. Its registered handover
  service is observed on its assigned receiver, so an existing mission
  handover stops it and restores it only when it was active before the mission.
- All systemd calls still pass through the existing dashboard
  run_systemctl adapter.

## Backend and data path

The installer builds pinned RTLSDR-Airband 5.2.0 commit
61c5c4061967752da6b491a924664d72184b38fa with NFM support. Its runtime
configuration is generated immediately before service start using the current
Receiver Registry serial.

RTLSDR-Airband is the sole SDR owner. It sends continuous 16 kHz float32 audio
to localhost UDP port 49555. The dashboard converts that existing audio stream
to PCM16/WAV in memory; it never opens the receiver. The backend also writes
Prometheus-format channel statistics every 15 seconds. The UI labels the
strongest/possibly active channel but does not claim an FFT spectrum or a
certain speaker identity.

## r3 receiver controls

The Traffic Voice page now controls the existing backend without introducing a
second settings or lifecycle authority:

- Scan all configured Marine channels or listen to one fixed channel.
- Click any channel row to switch directly to that fixed channel.
- Select an exact RTL-SDR tuner gain from the shared supported-gain list.
- Set the normal SNR squelch threshold from 1.0 through 30.0 dB.
- Open squelch explicitly for audio testing. This temporarily forces the
  selected fixed channel and renders the backend-supported 0.0 dB SNR
  threshold. Stop Voice and the next Start both clear this test state.
- Use a custom live-audio button and browser-volume slider. The streaming WAV
  element is hidden, so its intentionally unbounded header cannot show a
  misleading multi-hour duration.

All persistent receiver controls remain in `config/traffic_voice.yaml`. When
Voice is running, applying a setting restarts only
`sdrcc-traffic-voice.service`. AIS and ADS-B are untouched. If the restart
fails, the exact previous YAML document and prior Voice state are restored.
Receiver Manager blocks a settings change during an active handover.

## User channel banks

The source is `RT-950PRO_CPS_ChannelListChirpData_laatste.csv`.

- `coen_rotterdam` contains the 27 local Marine favourites from CH16_NOOD
  through V19_HCC, including Botlek, Waalhaven, Vlaardingen, Roeiers and
  Boluda. RTLSDR-Airband scans five frequencies per second, so a silent full
  bank takes approximately 5.4 seconds per cycle.
- `coen_zestienhoven` contains 13 AM favourites: Rotterdam Tower, Delivery
  and Approach, emergency, helicopter and SAR channels, plus the three
  military entries around 139–141 MHz.
- Airband remains configured but non-executable in v0.55.0b.
- For 8.33 kHz channels, both the spoken channel designator and actual SDR
  carrier are stored. For example, Rotterdam Tower channel 118.205 tunes the
  SDR to 118.200000 MHz. The current official EHRD AIP designators remain the
  user-facing labels.

## Service lifecycle

sdrcc-traffic-voice.service is installed disabled at boot and is not started
by the installer. Operator start is available only from the Traffic Voice
page. The service uses /opt/sdrcc/traffic_voice/bin/rtl_airband and creates
its generated configuration/statistics below /run/sdrcc-traffic-voice.
