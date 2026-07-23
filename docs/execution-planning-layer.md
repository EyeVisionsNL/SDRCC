# SDRCC v0.42.0c – Execution Planning Layer

## Doel

Deze release voegt een uniforme, read-only beschrijving toe van hoe een plugin
in een latere release gedelegeerd zou kunnen worden.

Een execution plan voert niets uit.

## Plancontract

Elk plan bevat onder andere:

- plugin- en adaptertype;
- launch- en targettype;
- statische targets;
- receiver role en receiver type;
- benodigde autoriteiten en voorwaarden;
- delegation targets;
- validatiestatus;
- expliciete `executable: false`;
- expliciete `planning_only: true` op catalogusniveau.

## Huidige plannen

- Weather: mission → SatDump pipeline.
- AIS: persistent service → `ais-catcher.service`.
- ADS-B: persistent service → `readsb.service`.
- ISS Voice en MeshCore: geen backend → Null plan.

## Autoriteitsgrenzen

Deze release:

- start en stopt geen services;
- start geen SatDump;
- reserveert, lockt of wijzigt geen receiver;
- maakt of wijzigt geen missie;
- schrijft geen Runtime- of Health-state;
- vervangt geen bestaand executionpad.

Receiver Manager, Mission Engine, Process Manager en bestaande service-control
blijven de enige operationele autoriteiten.
