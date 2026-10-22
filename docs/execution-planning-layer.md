# SDRCC v0.42.0c – Execution Planning Layer

## Doel

Deze historische laag begon als een uniforme, read-only beschrijving van hoe
een plugin gedelegeerd kon worden. De adapters zijn inmiddels ook de gedeelde
contractgrens voor uitvoerbare plugins; autoriteit blijft bij hun bestaande
lifecycle-controller.

Een execution plan voert zelf niets uit.

## Plancontract

Elk plan bevat onder andere:

- plugin- en adaptertype;
- launch- en targettype;
- statische targets;
- receiver role en receiver type;
- benodigde autoriteiten en voorwaarden;
- delegation targets;
- validatiestatus;
- expliciete uitvoerbaarheidsmetadata;
- een adapter die alleen naar bestaande, begrensde autoriteit delegeert.

## Huidige plannen

- Weather: mission → SatDump pipeline.
- AIS: persistent service → `ais-catcher.service`.
- ADS-B: persistent service → `readsb.service`.
- Traffic Voice: page controller → bestaande Voice-service en Receiver Manager.
- HF Amateur Monitor: page controller → Receiver Manager en één gevalideerde
  `librtlsdr`-backend voor SSB/spectrum/audio.

## Autoriteitsgrenzen

De planningslaag zelf:

- start en stopt geen services;
- reserveert, lockt of wijzigt geen receiver;
- maakt of wijzigt geen missie;
- vervangt geen bestaand executionpad.

Receiver Manager, Mission Engine, Process Manager, de begrensde Traffic
Voice/HF-controllers en bestaande service-control blijven de operationele
autoriteiten.
