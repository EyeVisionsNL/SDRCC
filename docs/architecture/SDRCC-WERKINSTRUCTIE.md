# SDRCC vaste werkinstructie

**Status:** bindend voor alle volgende SDRCC-sessies  
**Project:** SDRCC – Flexible Ground Station  
**Repository:** `/home/eyevisions/SDRCC`  
**Branch:** `develop`

## 1. Hoofdregel

Werk aan SDRCC zoals aan een bestaande productiecodebase. Niet opnieuw brainstormen wanneer een richting al is afgesproken. Een akkoord van de gebruiker betekent: de eerstvolgende concrete stap uitvoeren.

## 2. Vaste ontwikkelcyclus

1. Controleer de actuele projectstatus en beschikbare analysebestanden.
2. Analyseer alleen wat nodig is voor de afgesproken stap.
3. Vraag gericht om ontbrekende informatie wanneer die echt nodig is.
4. Bouw de afgesproken wijziging als compleet pakket.
5. Lever installatie-, controle- en rollbackinstructies.
6. Test eerst idle en daarna, wanneer relevant, met simulator of echte missie.
7. Werk GitHub pas bij nadat de gebruiker bevestigt dat de versie werkt.
8. Ga daarna direct door naar de volgende kleine release.

Geen herhaalde aankondigingen als “ik ga dit doen”. Na akkoord volgt uitvoering of één concrete informatievraag.

## 3. Bestandsworkflow

- Bestanden die de gebruiker moet uploaden worden in `/home/eyevisions` gemaakt.
- Pakketten die ChatGPT teruglevert worden vanuit `~/Downloads` geïnstalleerd.
- Gebruik `/tmp` niet voor overdracht.
- Lever complete bestanden of een compleet installatiepakket; geen losse vervang-snippets.
- Elk pakket bevat waar toepasselijk:
  - payload;
  - installscript;
  - rollbackscript;
  - release-notes;
  - syntax- en servicetests.

## 4. Analysegedrag

- Eerst bestaande architectuur, modules, API's, CSS, JavaScript en templates controleren.
- Bestaande logica en endpoints hergebruiken.
- Geen parallelle state machines, dubbele API's of dubbele eigenaars van state maken.
- Geen aannames doen over lokale bestanden die niet in een analysepakket zitten.
- Wanneer informatie ontbreekt: precies benoemen welk bestand, log of commando nodig is.
- Wanneer voldoende informatie aanwezig is: niet om een nieuw analysepakket vragen.

## 5. Architectuurregels

### Centrale richting

SDRCC wordt receiver-first en mission-centric opgebouwd.

- Fysieke receiver is de stabiele basis.
- Elke receiver krijgt uiteindelijk een eigen Receiver Runtime.
- Missies gebruiken tijdelijk een receiver/runtime.
- Mission Operations is de centrale orkestratielaag voor operationele acties.
- Dashboard toont status en verstuurt opdrachten, maar bevat geen businesslogica.
- History is de centrale bron voor resultaten, diagnostics, analytics en images.

### Eigenaarschap

- **Receiver Manager:** fysieke receivers, beschikbaarheid, reserveren en vrijgeven.
- **Receiver Runtime:** receivergebonden actieve job, plugin, telemetrie en runtime-state.
- **Mission Scheduler:** planning, queue, countdown en scheduler-modus.
- **Mission Engine:** uitvoering van de missie-pipeline.
- **Mission Operations:** centrale operationele start/stop/pause/resume/abort-regie.
- **Plugin:** signaal- of missiespecifieke uitvoering.
- **Dashboard:** presentatie en bediening via API's.

Iedere state heeft één eigenaar. Andere modules lezen deze state of vragen de eigenaar om een actie.

## 6. Plugin-lifecycle

Nieuwe missie- en signaalplugins gebruiken één gestandaardiseerde lifecycle:

```text
prepare()
start()
pause()
resume()
stop()
cleanup()
status()
```

METEOR wordt de eerste volledige referentieplugin. Later kunnen ISS, NOAA, AIS, ADS-B en andere plugins dezelfde lifecycle gebruiken.

## 7. Releasebeleid

- Eén logisch onderwerp per release.
- Kleine, stabiele versies.
- Backwards compatible migreren waar mogelijk.
- Geen grote rewrite wanneer gecontroleerde migratie mogelijk is.
- Geen nieuwe feature combineren met ongevraagde layoutwijzigingen.
- Bestaande schermen en bediening behouden tenzij expliciet anders gevraagd.
- Versie pas committen nadat tests geslaagd zijn en de gebruiker akkoord geeft.

## 8. Testvolgorde

1. `git status` controleren en bestaande wijzigingen benoemen.
2. Backup maken van alle te wijzigen bestanden.
3. Installeren.
4. Python-syntaxcontrole.
5. JavaScript-syntaxcontrole waar relevant.
6. Service herstarten.
7. API's controleren.
8. Idle gedrag controleren.
9. Simulator/regressietest gebruiken indien beschikbaar.
10. Echte missie pas uitvoeren wanneer idle/simulator stabiel zijn.
11. Bij fout: niet committen; analyseren en rollback beschikbaar houden.

## 9. Hardware- en projectcontext

- Ubuntu 26.04 LTS.
- Python 3.14 met venv in `/home/eyevisions/SDRCC/venv`.
- Flask-dashboard op poort 8080.
- Systemd-service: `sdrcc.service`.
- Twee NESDR Smart v5 receivers op deze computer:
  - SDR1 serial `05419737`;
  - SDR2 serial `24006572`.
- Receiverrollen zijn flexibel en mogen niet opnieuw hard worden vastgezet.
- Receiver Manager blijft autoriteit totdat Receiver Runtime gecontroleerd verantwoordelijkheden overneemt.

## 10. Huidige architectuurmigratie

De afgesproken volgorde is:

1. Architectuurdocumentatie en ownership vastleggen.
2. Mission Operations als centrale operationele ingang versterken.
3. Receiver Runtime per SDR introduceren zonder bestaande werking te breken.
4. Globale `active_job` gecontroleerd vervangen door receivergebonden actieve jobs.
5. Plugin-framework invoeren met METEOR als referentie.
6. History, diagnostics, analytics en images op hetzelfde missiemodel laten steunen.

## 11. Communicatieregel voor ChatGPT

Na “prima”, “mee eens”, “let's go” of een gelijkwaardig akkoord:

- voer de afgesproken stap uit;
- of stel precies één concrete vraag wanneer uitvoering werkelijk geblokkeerd is.

Niet doen:

- dezelfde roadmap opnieuw uitleggen;
- zeggen dat later een bestand wordt gemaakt zonder het te maken;
- stoppen zonder een concrete blokkade te noemen;
- vragen om informatie die al in de chat of analysepakketten aanwezig is;
- de gebruiker opnieuw laten bevestigen wat al besloten is.

## 12. Herstart van een nieuwe chat

Bij een nieuwe SDRCC-chat:

1. Lees dit document eerst.
2. Gebruik de actuele projectstatus en laatst gevalideerde versie.
3. Vraag alleen om de minimale ontbrekende broncode of logs.
4. Hervat bij de eerstvolgende open stap; begin niet opnieuw bij de visie of roadmap.

