# HF Amateur Monitor foundation — v0.56.0a

## Scope

v0.56.0a adds a dedicated HF Amateur Monitor page. Receiver choice, amateur
band, mode, the future spectrum/waterfall and future browser audio live on that
page. No third Start control is added to System.

This release is intentionally read-only. It does not open an RTL-SDR, stop a
service or create audio/spectrum data. Start remains disabled until one backend
has demonstrated all required capabilities: HF tuning, SSB demodulation, a live
spectrum stream and PCM audio.

The obsolete planned MeshCore placeholder is removed. MeshCore remains outside
SDRCC and is not replaced by another Home Assistant integration path.

## Architecture and duplication audit

| Concern | Existing owner or reusable path | v0.56.0a decision |
|---|---|---|
| Receiver identity | `core.receiver_registry` | Reuse canonical IDs and serials; no new hardware registry. |
| Receiver assignment | `config/station.yaml:assignments` | Read AIS/ADS-B placement only; HF choice is page-local and is not persisted as a competing assignment. |
| Receiver handover | Receiver Manager | Declared as the only future handover authority; not called by this foundation. |
| Service control | Existing dashboard systemctl path | Declared as future lifecycle path; no HF action endpoint exists. |
| Exact restore | Receiver Manager durable handover contract | A later Start must preserve exact pre-start states and must not start an already inactive service. |
| Spectrum | Existing `rtl_power` diagnostic is a bounded one-shot scan | Not reused as a fake live waterfall. |
| Voice backend | RTLSDR-Airband provides the existing AM/NFM Traffic Voice path | Not presented as an SSB backend. |
| HF UI | No existing HF workspace | New page, stylesheet and read-only JavaScript projection. |

## Receiver choice

The API derives the side effect from the current assignment authority instead
of hardcoding serial numbers:

- the receiver assigned to AIS is labelled `pauses AIS`;
- the receiver assigned to ADS-B is labelled `pauses ADS-B`;
- a receiver without either context is labelled as having no continuous
  context assigned.

The future transaction must stop only the selected receiver's active context,
reserve that receiver through Receiver Manager, then restore the exact captured
state on Stop or on any failed start. A service that was inactive before Start
must remain inactive.

## Band foundation

The page offers the Region 1 amateur allocations for 80, 40, 20, 15 and 10
metres with LSB, USB, CW and AM as UI modes. Band values are configuration, not
a substitute for the operator's licence obligations or current national band
plan.

## Execution gate

An executable follow-up may enable Start only after validation proves:

1. one backend owns tuning, SSB demodulation, spectrum and PCM audio;
2. no second receiver or service authority is introduced;
3. handover persists its restore target before a service is stopped;
4. failure injection restores the selected receiver and exact service states;
5. the UI renders measured data only and never synthesizes signal activity.
