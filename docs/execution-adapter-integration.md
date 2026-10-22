# SDRCC v0.42.0b – Execution Adapter Discovery & Integration

## Doel

De bestaande, read-only Execution Adapter Factory wordt zichtbaar gemaakt via
de centrale Plugin Manager. Dit is discovery en introspectie; geen uitvoering.

## Integratie

De Plugin Manager combineert vanaf deze release:

- Plugin Registry metadata;
- Plugin Runtime observatie;
- Plugin Health validatie;
- Execution Factory adapter-discovery.

Ieder gecombineerd pluginrecord krijgt een extra veld:

```json
{
  "plugin_id": "weather",
  "metadata": {},
  "runtime": {},
  "health": {},
  "execution": {
    "adapter_type": "satdump",
    "executable": false,
    "foundation_only": true,
    "metadata_valid": true
  }
}
```

De top-level Plugin Manager-snapshot krijgt aanvullend:

- `execution_source`;
- `execution_authority`;
- `execution`;
- `source_status.execution`;
- `summary.execution_adapters_valid`;
- `summary.execution_foundation_only`.

## API

Het bestaande endpoint `/api/plugin-manager` geeft deze velden automatisch
terug. Er wordt geen nieuw endpoint toegevoegd en geen bestaand veld verwijderd
of hernoemd.

## Autoriteitsgrenzen

Deze release:

- start of stopt geen services;
- reserveert of activeert geen receivers;
- maakt of wijzigt geen missies;
- start geen SatDump of subprocess;
- schrijft niet naar Plugin Runtime of Plugin Health;
- verandert geen dashboard-layout;
- vervangt geen bestaande executionroute.

Execution Factory blijft discoverybron. Receiver Manager, Mission Engine en
bestaande proceslagen behouden hun autoriteit.
