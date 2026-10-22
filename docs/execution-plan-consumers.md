# SDRCC v0.43.0a – Execution Plan Consumers

## Doel

Deze release introduceert de eerste consumers van Execution Plans zonder
operationele delegatie te activeren.

## Consumers

### Mission Engine

Bij het aanmaken van een weather-missie wordt een read-only weather-plan
opgevraagd en als diagnostische metadata aan de Mission Job toegevoegd.

De bestaande missieopbouw, receiver-locking en SatDump-startlogica blijven
ongewijzigd.

### Dashboard service-acties

Voor AIS- en ADS-B-serviceacties wordt vóór de bestaande `systemctl`-route een
service-plan opgevraagd. De service target wordt vergeleken met het plan.

De uitkomst wordt gelogd en aan de API-response toegevoegd. De bestaande
serviceactie blijft leidend en wordt niet door de consumer uitgevoerd.

## Observability

`GET /api/execution-plan-consumers` toont recente planconsumpties in geheugen.

## Autoriteitsgrenzen

De consumer:

- start en stopt geen services;
- start geen SatDump;
- lockt of reserveert geen receiver;
- maakt geen lifecyclebeslissingen;
- wijzigt geen plan;
- vervangt geen bestaande operationele route.

`behavior_changed` blijft daarom expliciet `false`.
