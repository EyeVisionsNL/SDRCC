# Live HF Amateur Monitor — v0.56.0b

## Resultaat

v0.56.0b maakt de eerder visuele HF-pagina uitvoerbaar. De operator kiest op
de pagina een receiver, amateurband, demodulatiemodus en frequentie. Start en
Stop blijven buiten System en lopen als één begrensde transactie.

De backend opent precies één NESDR SMArt v5 via `librtlsdr`. Onder 25 MHz wordt
Q-branch direct sampling geselecteerd; 10 meter gebruikt de normale tuner.
Dezelfde IQ-stroom levert:

- gemeten spectrumdata;
- een gemeten waterfall;
- LSB-, USB-, CW- of AM-demodulatie;
- mono 16 kHz PCM-audio voor de browser.

Er worden geen spectrum- of signaalwaarden gesimuleerd.

## Eigenaarschap

| Onderdeel | Autoriteit |
|---|---|
| Receiver-identiteit en serienummer | Receiver Registry |
| Reservering, handover en exact herstel | Receiver Manager |
| AIS/ADS-B-serviceactie | Bestaande dashboard-systemctl-adapter |
| RTL-SDR en DSP tijdens de HF-sessie | `core.hf_monitor_backend` |
| Lifecyclevolgorde en duurzame sessie | `core.hf_monitor_controller` |
| Presentatie en browseraudio | HF-pagina en begrensde Flask-endpoints |

De backend heeft geen service- of receiverautoriteit. De controller krijgt de
bestaande servicecallbacks vanuit het dashboard geïnjecteerd en roept geen
`systemctl` of shellproces rechtstreeks aan.

## Starttransactie

1. De selectie wordt tegen de ingestelde bandgrenzen gevalideerd.
2. Een duurzame HF-sessie wordt vastgelegd voordat een service wordt gestopt.
3. Receiver Manager observeert welke conflicterende services werkelijk actief
   zijn en stopt alleen die services.
4. De backend opent het gekozen serienummer en bevestigt pas Start nadat de
   eerste librtlsdr-read actief is.
5. Receiver Manager markeert de reservering actief.

Iedere fout stopt de backend en laat Receiver Manager de vastgelegde context
terugzetten. Een watchdog bewaakt ook een reeds gestarte IQ-stroom. Verdwijnt
die onverwacht door bijvoorbeeld een USB-fout, dan voert de controller dezelfde
fail-closed Stop- en hersteltransactie uit.

## Stop en recovery

Stop sluit eerst de HF-backend zodat de USB-claim verdwenen is. Daarna start
Receiver Manager uitsluitend services die hij bij Start als actief heeft
waargenomen en zelf heeft gestopt. Een vooraf gestopte AIS- of ADS-B-service
blijft dus gestopt.

Bij een dashboardherstart wordt een achtergebleven HF-sessie niet automatisch
hervat. SDRCC sluit fail-closed af en herstelt de exacte pre-start context.

## Ontvangstvoorwaarden

De NESDR SMArt v5 ondersteunt HF via Q-branch direct sampling, maar de
ontvangstkwaliteit blijft afhankelijk van een geschikte HF-antenne, lokale
ruis en sterke signalen buiten de gekozen band. Een externe upconverter en
bandfilter kunnen de ontvangst verbeteren, maar zijn geen softwarevereiste
voor deze release.
