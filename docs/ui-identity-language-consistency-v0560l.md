# SDRCC v0.56.0l — UI Identity & Language Consistency

This release changes presentation only for receiver identity and translates active operator-facing Event Bus / Timeline text to English.

Receiver Registry identity remains unchanged: `receiver01` / `receiver02` are canonical IDs, `SDR1` / `SDR2` are operator display names, `RX01` / `RX02` are stored receiver numbers, and `sdr1` / `sdr2` remain compatibility aliases.

Mission Analytics normalizes historical receiver labels to SDR1/SDR2 for display without rewriting Mission History. Existing stored Event Bus records are not rewritten; only newly produced operator events are English.
