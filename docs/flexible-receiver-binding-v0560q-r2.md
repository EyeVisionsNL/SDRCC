# FlexGround SDR 0.56.0q-r3 — compacte hardwarebindings

Dit pakket vervangt het eerdere r2-pakket. Eén install.sh ondersteunt een nieuwe Ubuntu-installatie (pc, mini-pc of Raspberry Pi met Ubuntu) en een bestaande 0.56.0p/0.56.0q-installatie. Het bevat Python-broncode; externe radioprogramma's worden op de doelmachine geïnstalleerd/gebouwd via de bestaande provisioning.

## Installeren

Pak het pakket uit naast de bestaande SDRCC-map, bijvoorbeeld in Downloads:

```bash
cd ~/Downloads
tar -xzf flexground-sdr-v0.56.0q-r3-compact-receiver-bindings.tar.gz
cd flexground-sdr-v0.56.0q-r3-compact-receiver-bindings
./install.sh
```

Bestaande installatie: stop eerst een actieve missie of HF/Radio Receiver-sessie via het dashboard. Een openstaande reservering blokkeert de update. De installer controleert bronbestandhashes, maakt een backup en vervangt uitsluitend gewijzigde bronbestanden. Alle bestaande config-bestanden blijven behouden, waaronder station.yaml, receivers.yaml, iss_voice.yaml en traffic_voice.yaml. De runtime kan later uitsluitend de hardwarebinding in receivers.yaml veranderen wanneer de werkelijke dongles worden vervangen.

Nieuwe installatie: de installer installeert afhankelijkheden en vraagt de stationlocatie, ongeacht het aantal dongles. Er zijn geen persoonlijke serienummers in de standaard receivers.yaml. Zonder dongles blijven beide slots UNBOUND. De webserver wordt met een begrensde retry gecontroleerd; een vaste wachttijd van twee seconden is verwijderd.

De update verwacht standaard ~/SDRCC. Een andere locatie kan met `SDRCC_ROOT=/pad/naar/SDRCC ./install.sh`. Bewaar het uitgepakte pakket buiten die doelmap.

## Ontvangers aansluiten en wisselen

- `receiver01`/`receiver02` en de aliassen `sdr1`/`sdr2` blijven de logische identiteit. Rollen, frequenties en gain-instellingen horen daarbij.
- PRESENT = aangesloten; MISSING = eerder gekoppelde dongle ontbreekt; UNBOUND = nog niet gekoppeld; UNKNOWN = fysieke aanwezigheid niet betrouwbaar vast te stellen.
- De Linux USB-descriptors worden gelezen zonder rtl_test, openen, retunen of claimen van de dongle. De RTL2832/RTL2838-ID's van de gebruikte NESDR/RTL-SDR Blog worden herkend; andere RTL-producten met herkenbare chipset/productnaam eveneens. Niet-herkende apparatuur wordt niet stilzwijgend gekoppeld.
- Geen aangesloten dongles of een detectiefout wist nooit bestaande bindingen.
- Evenveel nieuwe dongles als ontbrekende/lege slots: automatisch koppelen, met behoud van nog aanwezige ontvangers. Nieuwe serienummers worden stabiel gesorteerd, onafhankelijk van USB-index.
- Eén dongle bij twee lege slots, extra dongles of een andere onduidelijke combinatie: kies in Receiver Inventory → Change bindings welke dongle bij welk slot hoort.
- Kies **No binding (UNBOUND)** om een slot bewust zonder dongle te gebruiken. Die keuze blijft bewaard en wordt niet door automatische detectie ongedaan gemaakt. Kies later een aanwezige dongle om het slot opnieuw te binden.
- Ontbrekende of dubbele USB-serienummers vereisen unieke dongleserienummers voordat koppelen mogelijk is. Een USB-index wordt nooit als vervangende identiteit opgeslagen.
- Bij loskoppelen vraagt Receiver Manager de bestaande executor om te stoppen. Alleen die bestaande afhandeling geeft de reservering vrij. Onbekende/niet-vrijgegeven eigenaren blijven geblokkeerd met een melding.
- Eerder actieve ontvangstdiensten worden gestopt en hun herstelintentie wordt door Receiver Manager bewaard. Na terugkeer of vervanging worden uitsluitend die diensten hervat. Een handmatige Stop annuleert het herstel.
- Een gestopte missie wordt niet halverwege hervat. De bestaande missiestop zet de scheduler op MANUAL. Controleer de missie en zet daarna zelf AUTO weer aan als gewenst.
- HF/Radio Receiver-audio wordt via de bestaande controller beëindigd; start een nieuwe luistersessie na vervanging.
- AIS/readsb-serienummers worden via de bestaande geprivilegieerde transactiehelper gesynchroniseerd. Een fout laat de transactie zichtbaar geblokkeerd en wordt idempotent opnieuw geprobeerd; er wordt niet verdergegaan met een gedeeltelijk toegepaste koppeling.

De hardware-observatie loopt in het dashboardproces, ook zonder open browserpagina. Inventory en de GET-API's wijzigen geen bindings. Automatische wissels wachten op vrijgegeven reserveringen; ze trekken nooit een receiver onder een actieve eigenaar vandaan.

## Architectuur- en duplicatiecontrole

| Bestaand onderdeel | Rol na reparatie |
| --- | --- |
| Receiver Registry | Logische identiteit en lokale hardwarebinding; accepteert lege bindingen; atomisch schrijven |
| Receiver Manager | Enige reserverings- en hardwarewisselcoördinator; bewaart herstel/transactie-intentie in bestaand statebestand |
| Device Manager | Bestaande facade; voegt alleen waargenomen aanwezigheid toe |
| Receiver Runtime / Inventory | Alleen-lezen aggregatie en presentatie; geen mutatie bij GET |
| Mission Engine / dashboard missiestop | Bestaande missieannulering en executor-opruiming |
| HF Monitor controller | Bestaande stop/watchdog/handover, ook voor Radio Receiver |
| Receiver Authority + privileged helper | Bestaande AIS/readsb-configuratie en serviceverificatie |
| receiver_hardware | Gedeelde alleen-lezen USB-detectie voor installer/runtime; geen eigen rollen of ownership |

Receiver Inventory toont de fysieke status en bindings compact over de volle breedte binnen het bestaande tabblad. Geen extra navigatietab, tweede registry of tweede servicecontroller. De Registry blijft eigenaar van de feitelijke serienummerbinding; Receiver Manager bewaart alleen welke lege slots bewust van automatische binding zijn uitgesloten. Installatiedetectie en core/rtl.py gebruiken dezelfde fysieke detector. Bewuste presentatieherhaling blijft bestaan in Runtime en Inventory. Compatibility-aliassen blijven behouden.

## Validatie en beperkingen

35 gedragstests gebruiken de echte Registry/Manager en tijdelijke bestanden. USB-descriptors en serviceacties zijn gesimuleerd. Getest: lege slots, expliciet UNBOUND, behoud van die keuze tijdens automatische detectie, opnieuw binden, blokkade tijdens actieve ontvangst, behoud van UNBOUND-intentie na een atomische schrijffout, eerste binding, één/twee vervangers, onduidelijke aantallen, dubbele/lege serienummers, reserverings- en activatieblokkade, executor-opruiming, behoud van herstelintentie na restart, stop/sync/start, expliciete Stop, AIS-volgorde, mislukte serviceherstart, mislukte externe sync en idempotent herstel. Ook locatieconfiguratie zonder dongles, de compacte volle-breedteweergave en het aansluiten van schone serviceconfiguraties op de bestaande helper zijn getest.

De update en code-rollback zijn op een tijdelijke kopie van de aangeleverde 0.56.0p-bron uitgevoerd, met gesimuleerde systemd/HTTP-antwoorden. Alle lokale configuratiebestanden bleven byte voor byte gelijk. Python- en shellsyntax en de JavaScript-syntax zijn gecontroleerd. De bestaande Registry-validator slaagt met lege bindingen. De oudere handover-validator bevat nog een verouderde Nederlandse eventtitelverwachting en is daarom geen releasegate; de relevante nieuwe handoverpaden worden door de gedragstests afgedekt.

Een volledige Flask-dashboardstart, echte systemd-serviceacties, de externe Ubuntu-installers en fysieke USB-wissels zijn niet in deze omgeving getest. De benodigde dashboardafhankelijkheden waren hier niet beschikbaar. Gebruik de onderstaande hardwaretest voordat deze versie als volledig hardwaregevalideerd wordt beschouwd.

## Test op de opnieuw ingerichte Raspberry Pi

1. Installeer Ubuntu en dit pakket zonder dongles. Controleer dashboard HTTP 200 en SDR1/SDR2 = UNBOUND.
2. Sluit twee dongles aan. Controleer PRESENT, juiste serienummers en behouden rollen.
3. Start AIS/ADS-B en controleer ontvangst.
4. Trek één dongle uit. Het dashboard blijft draaien; het betrokken slot wordt MISSING en de betrokken ontvangst stopt.
5. Plaats een andere dongle. Controleer nieuw serienummer, externe AIS/readsb-configuratie en hervatte ontvangst.
6. Herhaal met beide dongles. Controleer ook terugplaatsen van de oorspronkelijke dongles.
7. Test een onduidelijke combinatie met een extra dongle en het bindingsformulier.
8. Test loskoppelen tijdens HF/Radio Receiver en tijdens een missie. Controleer beëindiging, vrijgegeven reservering en behoud van opnamen/historie. Zet de scheduler indien nodig terug op AUTO.
9. Herstart met dongles uitgetrokken. Bestaande bindingen blijven MISSING, niet UNBOUND.

Bij problemen:

```bash
cd ~/SDRCC
cat VERSION
curl -s http://127.0.0.1:8080/api/receiver-inventory
sudo journalctl -u sdrcc.service -n 80 --no-pager
```

## Backup en terugzetten

De update toont een backupmap onder ~/SDRCC/.rollback/v0.56.0q-r3-DATUM-TIJD. Daarin staan de vorige bronbestanden, een configuratiebackup en rollback_code.py. Het uitgeprinte rollbackcommando herstelt broncode en behoudt de huidige lokale instellingen en receiverbindingen. Het weigert tijdens reserveringen of onafgehandeld hardwareherstel. Herstel receivers.yaml niet los nadat dongles zijn vervangen: de externe serviceconfiguratie moet dezelfde binding houden.
