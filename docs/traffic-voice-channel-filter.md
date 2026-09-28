# Marine Voice pre-demodulation channel filter

Marine Voice now renders `bandwidth = 15000;` for the existing RTLSDR-Airband
5.2.0 backend. This enables its second-order Bessel low-pass on complex I/Q,
after FFT channelization and frequency correction, before FM demodulation.
It applies to fixed reception, scanning and the open-squelch test. Aviation
keeps its existing settings. No local YAML migration or backend rebuild is needed.

15 kHz is the full I/Q bandwidth: the low-pass cutoff is 7.5 kHz. The pinned
NFM build processes channel I/Q at 16 kHz, so a 25 kHz bandwidth setting would
exceed this filter's Nyquist limit. The conservative cutoff avoids unnecessarily
narrowing marine FM sidebands, including the ATIS burst. Browser speech filtering
and denoising remain separate, downstream operations.

The upstream squelch also checks the filtered signal when this option is enabled.
This is not a replacement for tuner gain control or protection against front-end
overload. It cannot undo interference already aliased during channelization.
Improved sensitivity or parity with another receiver is not established by this change.

## Validation

Run `python3 scripts/validate_traffic_voice_channel_filter.py` for both modes,
fixed/scan reception and open/closed squelch configuration paths.

The actual `LowpassFilter` from pinned upstream commit
`61c5c4061967752da6b491a924664d72184b38fa` was compiled and exercised locally.
Measured I/Q tone attenuation: 0.06 dB at 5 kHz, 0.70 dB at 7 kHz and
24.12 dB at 7.9 kHz. Synthetic ATIS packet 9244089629 survived FM modulation,
this filter and an FM discriminator at peak deviations of 1.5, 3 and 5 kHz,
with valid ECC and no corrected symbols. This checks filter compatibility;
it does not reproduce a complete receiver, upstream squelch or weak-signal RF conditions.

After updating, stop and start Traffic Voice to regenerate the runtime config.
