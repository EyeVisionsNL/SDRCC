# v0.44.1 – ADS-B Plugin Execution

Deze release schakelt ADS-B-uitvoering in via hetzelfde bewezen delegatiepatroon als AIS.

## Uitvoeringspad

Plugin Manager → bestaand Execution Plan → dashboard `handle_service_action()` → `readsb.service`

## Grenzen

- acties: `start`, `stop`, `restart`;
- bestaande dashboard-servicecontrole blijft operationele autoriteit;
- geen nieuwe systemd-wrapper;
- geen nieuwe receiver- of lifecycleautoriteit;
- AIS blijft ongewijzigd enabled;
- Weather blijft fail-closed;
- Execution Journal blijft observer-only.

## API

`POST /api/plugin-manager/adsb/action`

Body:

```json
{"action":"restart"}
```
