# SDRCC Migration Plan v0.35

**Project:** SDR Control Center (SDRCC)  
**Documentversie:** v0.35.1h  
**Status:** Uitvoeringsplan  
**Doel:** De huidige receiver- en missielogica gecontroleerd migreren naar de vastgelegde receiver-first architectuur.

---

## 1. Doel

Dit plan beschrijft hoe SDRCC stap voor stap migreert van de huidige werkende architectuur naar een model waarin:

- Receiver Manager eigenaar blijft van inventaris en reserveringen;
- Receiver Runtime eigenaar wordt van actieve receiverjobs en pluginprocessen;
- Mission Scheduler uitsluitend plant;
- Mission Engine missies uitvoert en beoordeelt;
- plugins SDR-specifieke processen uitvoeren;
- Mission Operations uitsluitend data samenstelt voor de frontend.

De migratie moet plaatsvinden zonder bestaande functionaliteit te breken.

---

## 2. Uitgangspunten

De migratie volgt deze vaste regels:

1. Eerst analyseren, daarna bouwen.
2. Eén logisch onderwerp per release.
3. Bestaande APIs blijven tijdens migratie compatibel.
4. Geen dubbele state machines.
5. Geen parallelle receiverautoriteiten.
6. Receiver Manager blijft voorlopig gezaghebbend.
7. Receiver Runtime begint read-only.
8. Iedere fase heeft installatie, validatie en rollback.
9. Eerst idle testen, daarna een echte METEOR-missie.
10. Pas na succesvolle praktijkvalidatie committen.

---

## 3. Huidige situatie

De huidige SDRCC-architectuur bevat onder andere:

```text
Mission Queue
    ↓
Automation Controller
    ↓
Mission Scheduler
    ↓
Mission Engine
    ↓
Receiver Manager
    ↓
SatDump / readsb / AIS-catcher
```

Receiver- en runtimeverantwoordelijkheden zijn nog niet volledig gescheiden.

De huidige situatie kent onder meer:

- receiverconfiguratie in `station.yaml`;
- satellietconfiguratie in `satellites.yaml`;
- actieve missiestatus in Mission Engine;
- receiverreserveringen in Receiver Manager;
- externe services voor AIS en ADS-B;
- SatDump-processen voor METEOR;
- samengestelde dashboardstatus via bestaande APIs.

---

## 4. Doelarchitectuur

De gewenste stroom is:

```text
Mission Scheduler
    ↓
Mission Engine
    ↓
Receiver Manager
    ↓
Receiver Runtime
    ↓
Plugin
    ↓
Externe software
```

De ownershipverdeling wordt:

| Onderdeel | Eigenaar |
|---|---|
| Receiverinventaris | Receiver Manager |
| Receiverreserveringen | Receiver Manager |
| Actieve receiverjob | Receiver Runtime |
| Pluginproces | Receiver Runtime / plugin |
| Missiestatus | Mission Engine |
| Planning en queue | Mission Scheduler |
| Resultaten en historie | Mission History |
| Samengestelde UI-response | Mission Operations |

---

## 5. Migratiefasen

### Fase 0 — Architectuurdocumentatie

Status: afgerond.

Documenten:

```text
docs/architecture/SDRCC-Architecture-v2.md
docs/architecture/Ownership-Matrix.md
docs/architecture/Data-Flow.md
docs/architecture/Migration-Plan-v0.35.md
```

Doel:

- verantwoordelijkheden vastleggen;
- gegevensstromen beschrijven;
- migratievolgorde bepalen;
- toekomstige dubbele logica voorkomen.

---

### Fase 1 — Receiver Runtime Foundation

Versie: v0.35.2

Receiver Runtime wordt toegevoegd als zelfstandige backendmodule.

In deze fase is Receiver Runtime uitsluitend observerend.

De module mag:

- receiverinventaris lezen;
- reserveringen lezen;
- actieve missiestatus lezen;
- externe servicestatus lezen;
- een genormaliseerde read-only runtimeweergave produceren.

De module mag nog niet:

- receivers reserveren;
- services starten of stoppen;
- SatDump starten;
- actieve jobs wijzigen;
- Mission Engine-state aanpassen;
- Receiver Manager-state overschrijven.

Voorbeeldmodel:

```text
receiver_id
configured_role
reservation
observed_service
observed_process
observed_mission
runtime_state
updated_at
authority
```

De waarde van `authority` is in deze fase altijd:

```text
receiver_manager
```

---

### Fase 2 — Read-only API en vergelijking

Versie: v0.35.3

Een nieuwe interne of publieke read-only response toont Receiver Runtime-data.

Doelen:

- vergelijken met bestaande Receiver Manager-responses;
- verschillen detecteren;
- ontbrekende velden identificeren;
- aantonen dat Runtime dezelfde werkelijkheid observeert.

De bestaande APIs worden niet vervangen.

Validatie:

- SDR1 en SDR2 zijn zichtbaar;
- rollen komen overeen met configuratie;
- reserveringen komen overeen met Receiver Manager;
- AIS- en ADS-B-servicestatus klopt;
- actieve METEOR-missie wordt correct waargenomen;
- idle receivers worden correct als idle getoond.

---

### Fase 3 — Plugincontract

Versie: v0.36.x

Definieer een klein plugincontract.

Minimale interface:

```text
prepare(context)
start()
status()
telemetry()
stop()
cleanup()
result()
```

De eerste pluginadapter wordt voor METEOR/SatDump gebouwd.

AIS en ADS-B blijven in deze fase nog als bestaande systemd-services draaien.

Regels:

- plugins reserveren geen receiver;
- plugins kiezen geen alternatieve receiver;
- plugins schrijven geen Mission Engine-state;
- plugins leveren technische status en resultaat terug;
- Receiver Runtime beheert de lifecycle.

---

### Fase 4 — Receiver Runtime voert METEOR-job uit

Versie: v0.37.x

Mission Engine vraagt Receiver Runtime een voorbereide METEOR-job uit te voeren.

Nieuwe stroom:

```text
Mission Engine
    ↓
Receiver Manager reserveert receiver
    ↓
Receiver Runtime start METEOR-plugin
    ↓
Plugin start SatDump
    ↓
Receiver Runtime bewaakt proces
    ↓
Mission Engine ontvangt resultaat
```

Mission Engine blijft eigenaar van:

- missiefasen;
- uiteindelijke succesbeoordeling;
- Mission History;
- archivering;
- foutclassificatie.

---

### Fase 5 — Runtime wordt eigenaar van active_job

Versie: v0.38.x

Pas na bewezen stabiele pluginuitvoering verhuist `active_job` naar Receiver Runtime.

Receiver Manager blijft eigenaar van reserveringen.

Compatibiliteit:

- bestaande endpoints blijven relevante velden leveren;
- oude consumers krijgen een afgeleide runtimeweergave;
- er komt geen tweede actieve-jobadministratie;
- de overgang gebeurt in één gecontroleerde release.

---

### Fase 6 — AIS- en ADS-B-pluginstrategie

Versie: later te bepalen.

Pas nadat METEOR stabiel via Receiver Runtime draait, wordt beoordeeld of AIS en ADS-B:

- systemd-services blijven;
- via Runtime-adapters worden beheerd;
- of volledige plugins worden.

Er wordt niet vooraf aangenomen dat iedere service hetzelfde lifecyclemodel nodig heeft.

---

### Fase 7 — Oude runtimecode opruimen

Oude code wordt pas verwijderd wanneer:

- de vervangende route in productie is getest;
- echte missies succesvol zijn;
- rollback beschikbaar is;
- geen frontend of API de oude velden nog nodig heeft;
- logging en History correct blijven.

Opruimen gebeurt in afzonderlijke releases.

---

## 6. Releasevolgorde

De geplande volgorde is:

```text
v0.35.1h  Migration Plan
v0.35.2   Receiver Runtime Foundation read-only
v0.35.3   Runtime observation API en vergelijking
v0.35.4   Dashboarddiagnostiek voor Runtime
v0.36.x   Plugincontract en SatDump-adapter
v0.37.x   METEOR-uitvoering via Receiver Runtime
v0.38.x   Receiver Runtime eigenaar van active_job
```

Versienummers na v0.35.3 kunnen worden aangepast als tussentijdse bugfixes nodig zijn.

---

## 7. Validatie per fase

Iedere implementatiefase doorloopt minimaal:

### 7.1 Statische controle

```text
python syntaxcontrole
importcontrole
configuratiecontrole
git diff --check
```

### 7.2 Idle test

Controleer:

- SDRCC start;
- dashboard opent;
- Receiver Manager blijft correct;
- Receiver Runtime observeert beide receivers;
- AIS en ADS-B blijven werken;
- geen reserveringen worden gewijzigd;
- geen extra processen worden gestart.

### 7.3 Service test

Controleer:

- AIS starten en stoppen;
- ADS-B starten en stoppen;
- rollen toepassen;
- serviceherstel na reboot;
- Runtime weerspiegelt de echte status.

### 7.4 Missietest

Controleer tijdens een echte METEOR-passage:

- juiste satelliet;
- juiste frequentie;
- juiste receiver;
- reservering zichtbaar;
- Runtime observeert de actieve job;
- opname en decode blijven ongewijzigd werken;
- Mission History wordt correct gevuld.

### 7.5 Herstarttest

Tijdens idle:

- herstart `sdrcc.service`;
- controleer beide receivers;
- controleer AIS en ADS-B;
- controleer scheduler;
- controleer dat Runtime geen fictieve actieve job toont.

---

## 8. Rollbackstrategie

Iedere release bevat:

```text
install.sh
rollback.sh
RELEASE-NOTES.md
```

De installer:

- maakt backups buiten de bronbestanden;
- controleert alleen de doelbestanden;
- voert syntaxcontrole uit;
- herstart uitsluitend benodigde services;
- commit niets automatisch.

De rollback:

- herstelt exacte vorige bestanden;
- voert opnieuw syntaxcontrole uit;
- herstart benodigde services;
- verwijdert geen gebruikersdata.

---

## 9. Compatibiliteitsregels

Tijdens de migratie gelden deze regels:

- bestaande frontendvelden blijven beschikbaar;
- bestaande serviceknoppen blijven werken;
- bestaande Mission Queue blijft leidend;
- Mission Scheduler blijft enige planner;
- Mission Engine blijft enige missie-state-machine;
- Receiver Manager blijft enige reserveringsautoriteit;
- Receiver Runtime is pas autoriteit wanneer dit expliciet in een latere fase wordt geactiveerd;
- plugins communiceren niet rechtstreeks met het dashboard.

---

## 10. Stopcriteria

Een fase wordt gestopt of teruggedraaid wanneer:

- AIS of ADS-B niet meer start;
- een receiver onterecht gereserveerd blijft;
- Scheduler en Mission Engine verschillende missies tonen;
- Runtime een andere actieve job meldt dan de bestaande autoriteit;
- SatDump-uitvoering verandert zonder dat dit onderdeel van de fase is;
- Mission History onvolledig raakt;
- rebootherstel verslechtert;
- nieuwe dubbele state ontstaat.

Bij een stopcriterium wordt niet verder gebouwd voordat oorzaak en ownership duidelijk zijn.

---

## 11. Definition of Done voor v0.35.2

Receiver Runtime Foundation is gereed wanneer:

- een nieuwe runtime-module bestaat;
- beide receivers read-only worden weergegeven;
- de module geen processen of services kan wijzigen;
- de bestaande Receiver Manager ongewijzigd autoriteit blijft;
- er geen nieuwe state machine is toegevoegd;
- bestaande APIs en UI blijven werken;
- idle tests slagen;
- AIS en ADS-B blijven werken;
- een echte METEOR-missie ongewijzigd kan worden uitgevoerd;
- installatie en rollback zijn getest.

---

## 12. Eerstvolgende stap

Na commit van dit migratieplan start:

```text
v0.35.2 — Receiver Runtime Foundation (read-only)
```

De eerste implementatie bevat uitsluitend:

- een klein runtime-datamodel;
- adapters die bestaande state lezen;
- een read-only snapshotfunctie;
- unit- of smokechecks;
- geen UI-wijziging;
- geen ownershipwijziging;
- geen procesbesturing.
