# v0.43.0b1 – Validator Compatibility

Deze release wijzigt uitsluitend de validator van de Execution Plan Consumers.

## Probleem

De v0.43.0a-validator controleerde de letterlijke functienaam
`consume_service_action` in `dashboard/app.py`. Daardoor werd een geldige
architectuurmigratie naar `delegate_service_action` afgewezen, ook wanneer
authority boundaries en runtimecontracten intact bleven.

## Oplossing

De validator:

- gebruikt AST-call-detectie in plaats van een losse tekstzoekopdracht;
- accepteert zowel `consume_service_action` als `delegate_service_action`;
- kiest runtime automatisch het aanwezige contract;
- bewaakt dezelfde verboden imports en operationele calls;
- blijft weather-planconsumptie, API-aanwezigheid en read-only gedrag testen.

## Niet gewijzigd

- geen operationele SDRCC-code;
- geen servicebesturing;
- geen Mission Engine-gedrag;
- geen Receiver Manager-gedrag;
- geen API-contract;
- geen UI.
