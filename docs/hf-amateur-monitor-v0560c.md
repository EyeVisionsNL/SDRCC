# HF spectrum measurement and live retune — v0.56.0c

## Resultaat

v0.56.0c maakt pieken in het gemeten HF-spectrum nauwkeurig bruikbaar. De
spectrumweergave heeft vaste plotmarges met MHz-verdeling en een dBFS-schaal.
De muiscursor toont voor de dichtstbijzijnde FFT-bin de exacte frequentie en
het gemeten niveau. Een klik kiest die frequentie en stemt een reeds actieve
HF-sessie meteen opnieuw af.

De frequentie kan tijdens ontvangst ook handmatig worden aangepast en met
`Tune live` worden toegepast. Receiver, amateurband en demodulatiemodus blijven
tijdens die sessie vergrendeld.

## Begrensde retune

Live retune maakt geen nieuwe receiver-reservering en start of stopt geen
AIS- of ADS-B-service. De bestaande HF-worker blijft de enige eigenaar van de
open RTL-SDR en voert de frequentiewijziging zelf uit. Na bevestiging worden:

- de centerfrequentie in de duurzame HF-sessie bijgewerkt;
- DSP-, spectrum- en waterfallstatus opnieuw opgebouwd;
- oude audiochunks verwijderd zonder een tweede IQ-stroom te openen.

Een fout tijdens retune zet de backend fail-closed in `ERROR`. De bestaande
watchdog voert dan dezelfde Stop- en exact-hersteltransactie uit als bij ieder
ander onverwacht IQ-verlies.

## Presentatiecontract

- horizontale schaal: zeven labels in MHz;
- verticale schaal: zes labels in dBFS;
- hover: crosshair plus MHz- en dBFS-meetwaarde;
- klik bij gestopte receiver: alleen frequentiekeuze;
- klik tijdens luisteren: frequentiekeuze plus directe live retune;
- Stop: spectrum- en waterfallarrays worden leeggemaakt zodat geen oude
  meting als live data zichtbaar blijft.
