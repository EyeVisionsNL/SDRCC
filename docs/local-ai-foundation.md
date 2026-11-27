# Local AI — SDRCC 0.80.2 foundation

Local AI is optional. No model download, runtime, database or AI background task is required to use SDRCC. New installations offer a disabled-by-default checkbox. Existing installations update normally using System → Advanced Maintenance → SDRCC Update; the new Intelligence tab offers a separate explicit install action. Existing feature selections remain unchanged.

## Intelligence

Open the Intelligence tab (between Reception Analytics and Logs), or use Open Intelligence under Advanced Maintenance.

- Install Local AI: downloads the verified CPU build of llama.cpp and Qwen3-4B Q4_K_M (~2.5 GB model).
- Enable / Disable / Remove Local AI: removal affects only AI assets and settings.
- AI Settings: CPU threads (1–4, limited by available CPUs), maximum answer length (128–512 tokens). Default: 2 threads where available, 384 tokens, 4096 context, thinking off. Address space limit: 5–8 GiB (default 7 GiB); this is virtual address space, not reserved physical RAM. Native engine diagnostics are available in the SDRCC service journal.
- Ask SDRCC: local single-turn questions in your language. No reception data is available to the model in this foundation release.

## Hardware and safety

16 GB RAM recommended. At least 7 GiB detected total and 6 GiB available RAM, two CPU threads, and 5 GiB free disk space for initial installation. The runtime refuses new requests under high load. The AI engine starts for a question and exits afterwards; CPU-only, low scheduling priority, bounded address space and CPU time. The first release does not provide a continuous AI service or hard CPU quota. Actual performance and compatible Linux builds must be verified on the target hardware. ARM64 AI is experimental and does not change SDRCC's supported platform requirements.

No cloud inference, arbitrary commands, receiver control, automatic restart, or access to live AIS, ADS-B, ATIS, historical data or mission execution in this release. Keep the dashboard on a trusted private network. Reception always has priority. The model is not redownloaded on an ordinary SDRCC update.

Model/runtime are stored under `data/local_ai/`; configuration uses the existing optional features file. The full SDRCC uninstaller removes project data; optional removal in Intelligence removes just AI assets and settings.
