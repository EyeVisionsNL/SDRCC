"""Versioned, read-only application help. No model, network, or station data required."""
import re
import unicodedata

SOURCE = "SDRCC Application Knowledge"
# Stable menu labels follow dashboard/templates/index.html. Update these entries
# in the same release as the corresponding UI or workflow; never use operator
# notes or raw logs as application instructions.
# label, desktop path, aliases, Dutch explanation, English explanation, optional feature
ENTRIES = (
    ("Ask AI", "Intelligence → Ask AI", ("ask ai", "ask sdrcc", "ai vragen", "vraag stellen"),
     "Stel vragen in je eigen taal. Kies bij Reception history eventueel een periode. Ontvangstgegevens zijn historische stationsbrede samples, geen unieke aantallen.",
     "Ask in your own language. Optionally select a Reception history period. Reception data is historical station-wide samples, not unique counts.", None),
    ("Station Health", "Intelligence → Station Health", ("station health", "station gezondheid", "stationstatus"),
     "Refresh toont een momentopname van de stationstatus. Analyze with AI geeft advies; er wordt niets automatisch gerepareerd.",
     "Refresh shows a station health snapshot. Analyze with AI provides advice, not automatic repairs.", None),
    ("Anomaly Detection", "Intelligence → Anomaly Detection", ("anomaly detection", "anomaly monitor", "afwijkingen", "technische alarmen"),
     "Bekijk technische afwijkingen. Met Monitor every minute en Save schakel je de periodieke controle in. MQTT technical alerts is optioneel.",
     "Review technical anomalies. Use Monitor every minute and Save to enable periodic checks. MQTT technical alerts is optional.", None),
    ("Station Memory", "Intelligence → Station Memory", ("station memory", "station geheugen", "notebook", "notitie", "notities"),
     "Gebruik Search memory, Import recent logs of het notitieformulier en Save note. Opgeslagen notities zijn gemelde waarnemingen, geen bewezen diagnoses.",
     "Use Search memory, Import recent logs or the note form and Save note. Stored notes are reported observations, not proven diagnoses.", None),
    ("Daily Briefing", "Intelligence → Daily Briefing", ("daily briefing", "dagoverzicht", "dagrapport", "dagelijkse briefing"),
     "Selecteer Last 24 hours of een beschikbare UTC-archiefdatum, kies Refresh en eventueel Analyze with AI.",
     "Select Last 24 hours or an available UTC archive date, choose Refresh and optionally Analyze with AI.", None),
    ("Maritime Intelligence", "Intelligence → Maritime Intelligence", ("maritime intelligence", "marine intelligence", "maritieme intelligence", "maritieme analyse"),
     "Kies een radius rond Home Position en Refresh. Bekijk recente gevalideerde AIS-waarnemingen; ATIS-cijfers zijn stationsbreed over 24 uur.",
     "Choose a radius around Home Position and Refresh. Review recent validated AIS observations; ATIS figures cover the entire station over 24 hours.", None),
    ("Aviation Intelligence", "Intelligence → Aviation Intelligence", ("aviation intelligence", "luchtvaart intelligence", "luchtvaart analyse"),
     "Kies een radius rond Home Position en Refresh. Bekijk recente ontvangen vliegtuiggegevens en hoogteverdeling; dit is niet al het luchtverkeer.",
     "Choose a radius around Home Position and Refresh. Review recent received aircraft observations and altitude distribution, not all air traffic.", None),
    ("Reception Performance", "Intelligence → Reception Performance", ("reception performance", "ontvangstprestaties", "ontvangst prestaties"),
     "Vergelijk de laatste 24 uur met de voorafgaande zeven dagen. Verschillen bewijzen niet automatisch een antenneprobleem.",
     "Compare the last 24 hours with the preceding seven days. Differences do not automatically prove an antenna problem.", None),
    ("RF Optimization", "Intelligence → RF Optimization", ("rf optimization", "rf optimisation", "rf optimalisatie", "rf optimizer", "rf optimalization", "record rf change", "record change now", "rf experiment"),
     "Open Record RF change. Kies AIS of ADS-B, het type wijziging (bijvoorbeeld antenna, LNA of gain), het meetvenster (24 uur of 7 dagen), titel en details. Kies Record change now direct na de fysieke wijziging. Vergelijk de metingen na afloop en gebruik Save result. SDRCC wijzigt zelf geen RF-instellingen.",
     "Open Record RF change. Select AIS or ADS-B, change type (such as antenna, LNA or gain), measurement window (24 hours or 7 days), title and details. Choose Record change now immediately after the physical change. Compare measurements after the window and use Save result. SDRCC does not change RF settings itself.", None),
    ("Mission Analyst", "Intelligence → Mission Analyst", ("mission analyst", "mission analysis", "missie analyse", "missieanalist"),
     "Selecteer de periode bij Mission history, kies Refresh en eventueel Analyze with AI. De analyse gebruikt bewaarde missieresultaten.",
     "Select the Mission history period, choose Refresh and optionally Analyze with AI. The analysis uses retained mission results.", None),
    ("Mission Advisor", "Intelligence → Mission Advisor", ("mission advisor", "missie advies", "missieadviseur"),
     "Kies Next 24 hours of Next 48 hours. Bekijk voorspelde passages en historische informatie. Dit is advies, geen reservering of automatische missieplanning.",
     "Choose Next 24 hours or Next 48 hours. Review predicted passes and historical information. This is advice, not a reservation or automatic mission scheduling.", None),
    ("AI Settings", "Intelligence → Ask AI → AI Settings", ("ai settings", "ai instellingen", "cpu threads", "answer length", "address space limit"),
     "Pas CPU threads, Answer length of Address space limit aan en kies Save settings. De adresruimtelimiet is geen hoeveelheid fysiek RAM. Houd ontvangstprioriteit in gedachten.",
     "Adjust CPU threads, Answer length or Address space limit and choose Save settings. The address-space limit is not physical RAM. Keep reception priority in mind.", None),
    ("SDRCC Update", "System → Advanced Maintenance → SDRCC Update", ("sdrcc update", "update knop", "updateknop", "update button", "install update", "check for update", "updaten", "bijwerken", "beta updates"),
     "Kies Check for update en daarna Install update als er een versie beschikbaar is. Gebruik de Beta-optie alleen voor develop; normaal gebruik je stable/main. Los actieve receiver- of herstelblokkades eerst op.",
     "Choose Check for update and then Install update if a version is available. Use the Beta option only for develop; normally use stable/main. Resolve active receiver or recovery blockers first.", None),
    ("Home Position", "System → Advanced Maintenance → Home Position", ("home position", "thuispositie", "station locatie", "station location"),
     "Controleer de ingestelde locatie en kies Save Home Position na een wijziging. Deze positie wordt gebruikt voor lokale radii en ontvangstplanning.",
     "Review the configured location and choose Save Home Position after a change. This position is used for local radii and reception planning.", None),
    ("Receiver Inventory", "System → Receiver Inventory", ("receiver inventory", "receiver overzicht", "sdr serial", "sdr serienummer"),
     "Bekijk fysieke receivers, registry-identiteit, runtime en toegewezen rollen. Dit overzicht is alleen-lezen.",
     "Review physical receivers, registry identity, runtime and assigned roles. This overview is read-only.", None),
    ("System", "System", ("system tab", "system overview", "systeem overzicht", "system usage"),
     "Bekijk de stationstatus, receivers, services en Advanced Maintenance.",
     "Review station status, receivers, services and Advanced Maintenance.", None),
    ("Radio Control", "Radio Control", ("radio control", "receiver assignments", "receiver toewijzingen", "receiver binding", "receiver runtime diagnostics"),
     "Bekijk receiverdiagnostiek en roltoewijzingen. De Receiver Manager bewaakt de fysieke receivers en hun beschikbaarheid.",
     "Review receiver diagnostics and role assignments. Receiver Manager guards physical receivers and availability.", None),
    ("Radio View", "Radio View", ("radio view", "ais kaart", "ads-b kaart", "aircraft map", "vessel map"),
     "Bekijk de beschikbare radio- en kaartinformatie van het station.",
     "View the station's available radio and map information.", None),
    ("Traffic Voice", "Traffic Voice", ("traffic voice", "marine voice", "marine traffic voice", "marifoon", "atis"),
     "Hier luister je naar ondersteunde radioverkeerskanalen. Een gevalideerde ATIS/AIS-match wordt als Possible Speaker weergegeven, niet als zekere identificatie.",
     "Listen to supported traffic radio channels. A validated ATIS/AIS match is shown as Possible Speaker, not a certain identification.", "traffic_voice"),
    ("Radio Receiver", "Radio Receiver", ("radio receiver", "waterfall", "waterval", "spectrum"),
     "Gebruik de ontvangerpagina voor direct afstemmen, spectrum, waterfall en audio wanneer de receiver beschikbaar is.",
     "Use the receiver page for direct tuning, spectrum, waterfall and audio when a receiver is available.", "radio_receiver"),
    ("Mission Control", "Mission Control", ("mission control", "scheduler auto", "scheduler manual", "missie bediening"),
     "Bekijk de missiebediening en scheduler-modus. Receiver Manager en Mission Engine bewaken de uitvoering.",
     "Review mission controls and scheduler mode. Receiver Manager and Mission Engine guard execution.", "satellite"),
    ("Mission Planner", "Mission Planner", ("mission planner", "missieplanner", "missie planning"),
     "Bekijk en plan ondersteunde satellietmissies. Een voorspelde passage is geen garantie op ontvangst.",
     "Review and plan supported satellite missions. A predicted pass does not guarantee reception.", "satellite"),
    ("Mission Operations", "Mission Operations", ("mission operations", "missie operaties", "mission reception"),
     "Bekijk operationele missiestatus en ontvangen resultaten.",
     "Review operational mission status and received results.", "satellite"),
    ("Mission History", "Mission History", ("mission history", "missie geschiedenis", "missiehistorie"),
     "Zoek bewaarde missies en bekijk hun resultaten.",
     "Search retained missions and review their results.", "satellite"),
    ("Mission Analytics", "Mission Analytics", ("mission analytics", "missie statistieken"),
     "Bekijk analyses van bewaarde missies, waaronder beschikbare ontvangstmetingen.",
     "Review retained mission analytics, including available reception measurements.", "satellite"),
    ("Reception Analytics", "Reception Analytics", ("reception analytics", "ontvangst statistieken", "ontvangststatistieken"),
     "Bekijk historische AIS- en ADS-B-ontvangstgegevens. Samples zijn geen unieke schepen of vliegtuigen.",
     "Review historical AIS and ADS-B reception data. Samples are not unique vessels or aircraft.", None),
    ("Logs", "Logs", ("logs", "logboek", "logfiles", "log files", "service journal"),
     "Bekijk technische loguitvoer van SDRCC en receivers. Een foutmelding kan historisch zijn; controleer de actuele stationstatus.",
     "Review technical logs from SDRCC and receivers. An error may be historical; check current station status.", None),
)
DUTCH = re.compile(r"\b(?:waar|vind|vinden|zit|staat|hoe|wat|welke|kan|kun|moet|ik|mijn|de|het|een|voor|uitleg|betekent|werkt|doet|knop|inloggen|instellen|openen|gebruiken)\b")
HELP = re.compile(r"\b(?:waar|hoe|wat is|wat doet|wat betekent|waarvoor|welke knop|uitleg|how|where|what is|what does|what means|explain|help|meaning|purpose|button|knop|menu|tabblad|navigation|navigatie|use|gebruiken|openen|find)\b")
# Avoid replacing observational, quantitative, diagnostic or mixed requests.
OBSERVATION = re.compile(r"\b(?:hoeveel|how many|how much|today|yesterday|vandaag|gisteren|nu|currently|current|last|past|afgelopen|laatste|compare|vergelijk|analyseer|analyze|statistieken|statistics|messages|berichten|waarom|why|storing|fault|error|fout|trend|bereik|range|snr|verbeterd|improved|24h|7d|30d)\b")
ACTION = re.compile(r"^\s*(?:start|stop|enable|disable|delete|remove|install|verwijder|zet|schakel|herstart|restart)\b")


def normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def matches(question):
    q = normalize(question)
    hits = []
    for row in ENTRIES:
        aliases = (row[0], *row[2])
        if any(re.search(r"(?<!\w)" + re.escape(normalize(alias)) + r"(?!\w)", q) for alias in aliases):
            hits.append(row)
    # A specific child (e.g. SDRCC Update) takes precedence over a broad System
    # match; otherwise don't silently pick one of multiple topics.
    return hits


def available_text(row, dutch, feature_flags):
    label, path, aliases, nl, en, feature = row
    if feature and not feature_flags.get(feature, True):
        return (path + "\n\n" +
                ("Deze optionele functie is niet ingeschakeld in deze installatie." if dutch
                 else "This optional feature is not enabled in this installation."))
    return path + "\n\n" + (nl if dutch else en)


def direct_answer(question, feature_flags):
    q = normalize(question)
    dutch = bool(DUTCH.search(q))
    hits = matches(q)
    if ACTION.search(q) or OBSERVATION.search(q):
        return None
    if len(hits) == 1 and (HELP.search(q) or q in {normalize(a) for a in (hits[0][0], *hits[0][2])}):
        return available_text(hits[0], dutch, feature_flags)
    if re.fullmatch(r"(?:wat kan sdrcc(?: ai)?|wat kan ik met sdrcc|welke functies heeft sdrcc|what can sdrcc(?: ai)? do|what features does sdrcc have)(?: allemaal)?", q):
        labels = [row[0] for row in ENTRIES if not row[5] or feature_flags.get(row[5], True)]
        lead = "SDRCC biedt deze functies. Vraag waar je een functie vindt of hoe die werkt:" if dutch else "SDRCC offers these features. Ask where to find a feature or how it works:"
        return lead + "\n\n" + ", ".join(labels)
    return None


def context(question, feature_flags):
    """Bounded trusted help for non-history questions the model must phrase."""
    q = normalize(question)
    if ACTION.search(q) or OBSERVATION.search(q) or not HELP.search(q):
        return None
    hits = matches(q)
    if not hits:
        return None
    return {
        "kind": "application_knowledge",
        "source": SOURCE,
        "entries": [available_text(row, False, feature_flags) for row in hits[:4]],
    }
