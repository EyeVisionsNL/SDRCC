# Execution Journal Runtime Observation — v0.43.0c3

Deze stap koppelt het observer-only Execution Journal aan bestaande Mission Engine-beslissingen.

Waargenomen events:

- `ACCEPTED`: Mission Engine heeft een job aangemaakt.
- `STARTED`: bestaande overgang naar `LOCK RECEIVER`.
- `FINISHED`: missie eindigt met `SUCCESS`.
- `FAILED`: ieder ander afgerond resultaat, behalve annulering.
- `CANCELLED`: actieve missie wordt via reset/cancel beëindigd.

De Mission Engine blijft de enige lifecycle-authoriteit. Journal-fouten zijn fail-open en mogen een missie nooit blokkeren. Er is geen service-, receiver- of procesbesturing aan het Journal toegevoegd.
