# SDRCC v0.56.0d – HF FM, Auto Gain and Squelch

This release extends the existing single-owner HF Amateur Monitor without changing receiver or service authority.

## Added

- FM demodulation inside the existing `HFSignalProcessor`.
- Auto Gain checkbox for the HF receiver.
- Live manual tuner-gain selection on the normal tuner path (10 m).
- On Q-branch direct sampling (80/40/20/15 m), Auto Gain controls RTL digital AGC; numeric tuner gain is intentionally shown as ineffective because the tuner is bypassed.
- RF-power squelch with a configurable dBFS threshold.
- Live gain/squelch updates are acknowledged by the existing IQ-owner worker; no second RTL-SDR handle is opened.
- Current RF level and squelch-open/closed state are projected into the existing HF snapshot.

## Preserved contracts

- Receiver Manager owns receiver reservation and exact pre-start restoration.
- The dashboard only injects the existing service-control authority.
- Spectrum, waterfall and browser audio still originate from the same measured IQ stream.
- Live frequency retune remains bounded to the active sampling path.

## Traffic Voice Auto Gain

Marine/Aviation Traffic Voice remains unchanged in this package. The pinned RTLSDR-Airband 5.2.0 backend requires a numeric `gain` in its RTL-SDR device configuration and therefore forces a manual tuner-gain setting. SDRCC does not expose a misleading Auto Gain checkbox until that pinned backend is explicitly extended and rebuilt with a supported automatic-gain contract.
