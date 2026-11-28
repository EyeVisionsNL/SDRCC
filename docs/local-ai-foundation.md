# Local AI — SDRCC 0.80.7 Reception Analytics

Local AI is optional. No model download, runtime, database or AI background task is required to use SDRCC. New installations offer a disabled-by-default checkbox. Existing installations update normally using System → Advanced Maintenance → SDRCC Update; the new Intelligence tab offers a separate explicit install action. Existing feature selections remain unchanged.

## Intelligence

Open the Intelligence tab (before Reception Analytics, after Mission Analytics when satellites are installed). All Local AI installation, removal and settings are managed there; Advanced Maintenance retains the ordinary SDRCC update controls.

- Install Local AI: downloads the verified CPU build of llama.cpp and Qwen3-4B Q4_K_M (~2.5 GB model).
- Enable / Disable / Remove Local AI: removal affects only AI assets and settings.
- AI Settings: CPU threads (1–4, limited by available CPUs), maximum answer length (128–512 tokens). Default: 2 threads where available, 384 tokens, 4096 context, thinking off. Address space limit: 5–8 GiB (default 7 GiB); this is virtual address space, not reserved physical RAM. Native engine diagnostics are available in the SDRCC service journal.
- Ask SDRCC: local single-turn questions in your language. Read-only Reception Analytics evidence is available for 24h, 7d and 30d windows. Auto recognizes common English/Dutch reception questions and period phrases; choose a period explicitly or select No reception data. Verified source values are displayed separately from the AI answer.

## Hardware and safety

16 GB RAM recommended. At least 7 GiB detected total and 6 GiB available RAM, two CPU threads, and 5 GiB free disk space for initial installation. The runtime refuses new requests under high load. The AI engine starts for a question and exits afterwards; CPU-only, low scheduling priority, bounded address space and CPU time. The first release does not provide a continuous AI service or hard CPU quota. Actual performance and compatible Linux builds must be verified on the target hardware. ARM64 AI is experimental and does not change SDRCC's supported platform requirements.

No cloud inference, arbitrary commands, receiver control, automatic restart, live AIS/ADS-B, ATIS or mission execution. Only bounded station-wide Reception Analytics historical summaries are available. Keep the dashboard on a trusted private network. Reception always has priority. The model is not redownloaded on an ordinary SDRCC update.

Model/runtime are stored under `data/local_ai/`; configuration uses the existing optional features file. The full SDRCC uninstaller removes project data; optional removal in Intelligence removes just AI assets and settings.

## Read-only SDRCC intelligence (Reception Analytics implemented; later phases planned)

Reuse the station's existing sources. No duplicate database or additional RF receiver.

1. **Reception Analytics first.** Source: `data/analytics/reception.sqlite3`, table `samples` in `core/reception_analytics.py`. It samples nominally once per minute and retains 90 days. Implemented fixed, parameterized queries over 24h/7d/30d periods for mean and peak fresh AIS targets, ADS-B targets, rates and range. Count only valid active observations; exclude null and legacy unvalidated AIS totals. Report actual sample count, time range, coverage and source. A mean of simultaneous targets is not a count of unique vessels. A station-wide average is not a Vlaardingen-specific average.
2. **Live reception and ATIS.** Read the existing `core/traffic_map.py` snapshot and `data/analytics/atis_statistics.sqlite3` (table `atis_events` in `core/atis_statistics.py`). Reuse existing freshness/identity validation. Filter current positions by explicit radius or defined area; never invent historical geographic counts from aggregate samples. Add ATIS totals and matching status only where recorded. Respect selected/installed features and distinguish stopped, stale, unavailable and zero.
3. **Mission history, emergency and local memory.** Reuse `core/mission_history.py` and read-only emergency history/snapshots. Add a separate optional AI memory database only after defining its schema, retention, size limits, delete/export and consent. Do not change existing collector retention or store full live feeds by default.

### Data access contract

- Reception reads have a 60,000-row cap, 1.5-second SQLite progress deadline and 300 ms lock timeout. No new history database is created. Coverage is sample count divided by nominal expected count (capped at 100%); it is not an uptime measurement. Missing, null, inactive and legacy unvalidated observations are not interpreted as zero.
- Open existing SQLite databases with URI `mode=ro` and `PRAGMA query_only=ON`; do not call helpers that perform schema creation/migration or resets. No database created by the AI when the source is missing. Use fixed queries, parameter binding, restricted periods, row limits and execution timeouts; no SQL, shell commands, arbitrary paths or arbitrary URLs generated by the model.
- A deterministic data adapter computes numerical results. Pass a bounded structured evidence payload to Qwen with source and timestamps; treat source text as data, not instructions. The answer must distinguish observed values, estimates and unavailable data. Display evidence independently of the model response.
- AI remains optional, local-only and on-demand. It cannot start/stop services, change receiver allocation, reset analytics, edit files or execute missions. Mission Engine remains the sole execution authority.
- Test read-only opening, missing databases, disabled modules, null/zero semantics, legacy schema, bounded query execution, time windows, stale observations and no changes to existing data. Run existing release/manifest/3D map checks before releasing on develop. Test on the actual station with AI enabled and disabled before promotion to main.

## Station Health and Maritime Intelligence (0.80.9)

Intelligence subviews provide explicit read-only snapshots via Refresh and an optional local AI assessment. Opening a subview reads current observations if AI is enabled. No polling daemon, no additional receiver ownership, no service changes. Station Health checks configured USB identity, service state, decoder output, available RAM, free disk, load, CPU temperature where available, reception history freshness, and classified visible log messages over the last hour (150 entries per unit, 64 KiB SDRCC log). Stopped services may be intentional; a kernel USB identity check is not a transfer test, and a database read is not a full integrity check. Log counts represent matching messages, not unique incidents.

Maritime Intelligence uses local AIS-Catcher reports no older than 300 seconds with validated identity and position, excluding fixed stations and non-vessels. Choose 10/25/50/100 km from configured Home Position. Vessel profiles are SDRCC display hints, not verified classifications. A limited set of ordinary vessel examples is shown; counts refer only to received reports. ATIS history is station-wide over the last 24 hours and is read without migrations; missing fields and disabled modules are reported separately. No live voice transcription, full traffic coverage, geofencing history or automatic alerts in this release.
