# v0.43.0b2 – Execution Plan Delegation

## Scope

Deze release delegeert uitsluitend de keuze van het systemd-servicetarget vanuit
het dashboard naar het bestaande read-only Execution Plan.

## Nieuwe keten

`SERVICE_ACTIONS.plugin_id` → `delegate_service_action()` → Execution Plan
target → bestaande `run_systemctl()`.

## Authority-grenzen

- Plugin Registry blijft metadata-authoriteit.
- Execution Adapter en Execution Plan blijven read-only.
- Execution Plan Consumer kiest alleen één geldig servicetarget.
- `dashboard/app.py::run_systemctl()` blijft de bestaande operationele uitvoerder.
- Receiver Manager en Mission Engine worden niet gewijzigd.
- De consumer importeert geen subprocess-, receiver- of mission-lifecyclecode.

## Fail-closed gedrag

Een dashboardactie wordt vóór `service_state()` en `run_systemctl()` geweigerd
wanneer:

- de plugin onbekend is;
- het plan ongeldig is;
- het plan niet exact één servicetarget bevat;
- de actie niet `start`, `stop` of `restart` is.

## Compatibiliteit

Het bestaande API-veld `execution_plan_consumption` blijft aanwezig. Het nieuwe
veld `execution_plan_delegation` bevat hetzelfde delegatierecord.

De validator ondersteunt het oude validatiepad en controleert bij delegatie
aanvullend dat `SERVICE_ACTIONS` alleen `plugin_id` bevat en geen hardcoded
service.
