# SDRCC v0.56.0h — Traffic Voice Excel Channel Lists

`config/traffic_voice.yaml` remains the only runtime configuration authority.

The Traffic Voice page can export both channel banks to one `.xlsx` workbook and load a validated workbook back.

Columns on `Channels`: `Mode`, `Channel Bank`, `ID`, `Name`, `Channel MHz`, `Frequency MHz`, `Scan`.

Import is fail-closed. The complete workbook is normalized and passed through the existing Traffic Voice configuration validator before the YAML file is written. Gain, squelch, receiver policy, selected mode, services and Receiver Manager authority are not changed.
