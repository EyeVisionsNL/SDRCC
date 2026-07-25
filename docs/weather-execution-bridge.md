# v0.45.0 – Weather Execution Bridge

Weather execution wordt via de Plugin Manager ingeschakeld zonder een nieuw missiepad te introduceren.

- Start zet de bestaande Mission Scheduler op AUTO, uitsluitend wanneer een geldige eerstvolgende passage bestaat.
- Start begint nooit direct met opnemen.
- De bestaande autopilot, Mission Engine, Receiver Manager en SatDump-keten blijven autoriteit.
- Stop hergebruikt de bestaande Stop Mission-keten bij een actieve missie; anders wordt de Scheduler op MANUAL gezet.
- AIS en ADS-B blijven via bestaande service-control gedelegeerd.
