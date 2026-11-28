"""Persistent, bounded recovery observer. No model, service or USB actions."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import logging
import re
import sqlite3
import threading
import time

SOURCE = "data/state/recovery_history.sqlite3"
LOG_BYTES = 512 * 1024
INTERVAL = 30
RETENTION = 90 * 86400
WINDOWS = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
LOG = logging.getLogger(__name__)
LOCK = threading.Lock()
_started = False
LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
AUTO = re.compile(r"^RECEIVER AUTO RECOVERY: (RX\d+|SDR\d+) (.*)$", re.I)
MANUAL = re.compile(r"^RECEIVER RECOVERY(?:( blocked| failed))?: (RX\d+|SDR\d+) - ", re.I)
ATTEMPT = re.compile(r"^(readsb|ais-catcher)\.service; attempt ([12])/2$")
VERIFIED = re.compile(r"^(readsb|ais-catcher)\.service running; runtime verified$")
UPDATE = re.compile(r"^Managed SDRCC update requested: ([\w.-]{1,32}) -> ([\w.-]{1,32}) via ")
TERMINAL = {"verified", "failed", "attention", "manual_completed", "manual_failed", "manual_blocked"}


def classify(message):
    """Return fixed fields only; never persist raw logs, serials or exception text."""
    match = AUTO.match(message)
    if match:
        receiver, detail = match.groups()
        receiver = receiver.upper()
        if m := ATTEMPT.fullmatch(detail):
            return receiver, m[1], "attempt", int(m[2]), ""
        if m := VERIFIED.fullmatch(detail):
            return receiver, m[1], "verified", 0, ""
        if detail.startswith("USB reset OK:"):
            return receiver, "", "usb_reset", 0, ""
        if detail.startswith("USB reset failed:"):
            return receiver, "", "usb_failed", 0, ""
        if detail.startswith("FAILED;"):
            return receiver, "", "failed", 0, ""
        if detail == "service active; runtime verification requires attention":
            return receiver, "", "attention", 0, ""
        return receiver, "", "auto_error", 0, ""
    if match := MANUAL.match(message):
        return match[2].upper(), "", "manual_" + (match[1].strip() if match[1] else "completed"), 0, ""
    if match := UPDATE.match(message):
        return "", "", "update", 0, match[1] + " -> " + match[2]
    if message.startswith("AUTO: missie afgerond;"):
        return "", "", "mission_end", 0, ""
    if message.startswith("Traffic Voice stop:"):
        return "", "", "voice_stop", 0, ""
    return None


def read_events(root, now):
    path = root / "logs/sdrcc.log"
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - LOG_BYTES))
        raw = handle.read(LOG_BYTES)
    if size > LOG_BYTES:
        raw = raw.partition(b"\n")[2]
    # The last line may still be in flight; leave it for the next scan.
    raw = raw[:raw.rfind(b"\n")+1]
    rows = []
    for line in raw.decode("utf-8", "replace").splitlines():
        match = LINE.match(line)
        if not match:
            continue
        try:
            stamp = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, OverflowError):
            continue
        if not now - RETENTION <= stamp <= now:
            continue
        item = classify(match[2])
        if item:
            key = hashlib.sha256(line.encode("utf-8")).hexdigest()
            rows.append((key, stamp, *item))
    return rows, size > LOG_BYTES


def connect(root):
    path = root / SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=.5)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS events(
            id TEXT PRIMARY KEY, ts REAL NOT NULL, receiver TEXT NOT NULL, service TEXT NOT NULL,
            kind TEXT NOT NULL, attempt INTEGER NOT NULL, context TEXT NOT NULL,
            memory_done INTEGER NOT NULL DEFAULT 0)""")
        db.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
        db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.commit()
        return db
    except Exception:
        db.close()
        raise


def utc(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def group(rows):
    """An attempt 2 belongs to the preceding unfinished attempt 1, not a second incident."""
    episodes, active, contexts = [], {}, {}
    for key, stamp, receiver, service, kind, attempt, detail in rows:
        if kind in ("update", "mission_end", "voice_stop"):
            contexts[kind] = (stamp, detail)
            continue
        related = [name + (": " + value if value else "") for name, (when, value) in contexts.items()
                   if 0 <= stamp - when <= 900]
        if kind.startswith("manual_"):
            episodes.append(dict(id=key, ts=stamp, receiver=receiver, service=service,
                                 outcome=kind, attempts=0, seconds=0, context=related))
            continue
        previous = active.get(receiver)
        if previous and stamp - previous["last"] > 300:
            active.pop(receiver, None)
            previous = None
        if kind == "attempt":
            if attempt == 1 or not previous:
                previous = dict(id=key, ts=stamp, receiver=receiver, service=service,
                                outcome="unconfirmed", attempts=0, seconds=None, context=related, last=stamp)
                episodes.append(previous)
                active[receiver] = previous
            previous["attempts"] += 1
            previous["last"] = stamp
            continue
        if kind not in TERMINAL:
            if previous:
                previous["last"] = stamp
            continue
        if not previous:
            previous = dict(id=key, ts=stamp, receiver=receiver, service=service,
                            outcome="unconfirmed", attempts=0, seconds=None, context=related, last=stamp)
            episodes.append(previous)
        previous["outcome"] = kind
        previous["service"] = service or previous["service"]
        previous["seconds"] = int(stamp - previous["ts"]) if previous["attempts"] else None
        active.pop(receiver, None)
    return episodes


def collect(root, *, now=None, notify=False):
    now = time.time() if now is None else now
    rows, bounded = read_events(root, now)
    with LOCK, closing(connect(root)) as db:
        new = []
        with db:
            first = db.execute("SELECT value FROM meta WHERE key='last_scan'").fetchone() is None
            for row in rows:
                inserted = db.execute("INSERT OR IGNORE INTO events(id,ts,receiver,service,kind,attempt,context) VALUES(?,?,?,?,?,?,?)", row)
                if inserted.rowcount and row[4] in TERMINAL:
                    new.append(row)
            db.execute("DELETE FROM events WHERE ts<?", (now - RETENTION,))
            for key, value in (("last_scan", str(now)), ("bounded", str(int(bounded)))):
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
        # Memory stores classified outcomes, once, even if the operator later deletes the note.
        from core import local_ai_memory as memory
        pending = db.execute("SELECT id,ts,receiver,service,kind FROM events WHERE memory_done=0 AND kind IN ('verified','failed','attention','manual_completed','manual_failed','manual_blocked') ORDER BY ts DESC LIMIT 20").fetchall()
        for key, stamp, receiver, service, kind in pending:
            try:
                memory_key = "recovery:" + key
                with closing(memory.connect_write(root)) as notebook, notebook:
                    notebook.execute("BEGIN IMMEDIATE")
                    if not notebook.execute("SELECT 1 FROM entries WHERE event_key=?", (memory_key,)).fetchone():
                        memory.insert(notebook, (stamp, "incident", receiver + " recovery: " + kind.replace("_", " "),
                            (service or "Receiver") + " · classified recovery event.",
                            outcome_text(kind), "recovery_history", memory_key))
                with db:
                    db.execute("UPDATE events SET memory_done=1 WHERE id=?", (key,))
            except (OSError, sqlite3.Error, ValueError) as exc:
                LOG.warning("Recovery memory synchronization deferred: %s", exc)
                break
    # Do not replay historical notifications on first import or after a long gap.
    if notify and not first:
        from core import emergency_monitor
        for key, stamp, receiver, service, kind, attempt, context in new:
            if 0 <= now-stamp <= INTERVAL*3:
                emergency_monitor.publish_station_anomaly(dict(id=key, rule="receiver_recovery",
                    title=receiver+" recovery", transition=kind, timestamp=utc(stamp), detail=outcome_text(kind)))


def outcome_text(kind):
    return {
        "verified": "Decoder runtime verified; cause and lasting repair not established.",
        "failed": "Automatic recovery failed or retry budget exhausted.",
        "attention": "Service active; runtime verification requires attention.",
        "manual_completed": "Manual recovery completed; reception not verified.",
        "manual_failed": "Manual recovery failed.",
        "manual_blocked": "Manual recovery blocked; no repair inferred.",
        "unconfirmed": "No terminal outcome observed.",
    }.get(kind, "Unknown outcome.")


def snapshot(root, now=None):
    now = time.time() if now is None else now
    base = dict(status="unavailable", windows={}, recent=[], last_scan_utc=None,
                scope="Observed recovery episodes only; bounded log import, 90-day local retention. Missing events are not proof of stability. Context within 15 minutes is not causality.")
    path = root / SOURCE
    if not path.is_file():
        return base
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.3)) as db:
            meta = dict(db.execute("SELECT key,value FROM meta"))
            rows = db.execute("SELECT id,ts,receiver,service,kind,attempt,context FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts DESC,rowid DESC LIMIT 20001", (now-WINDOWS["30d"]-1200,now)).fetchall()
            history_limited = len(rows) > 20000
            rows = list(reversed(rows[:20000]))
            pending = db.execute("SELECT COUNT(*) FROM events WHERE memory_done=0 AND kind IN ('verified','failed','attention','manual_completed','manual_failed','manual_blocked')").fetchone()[0]
        episodes = group(rows)
        windows = {}
        for name, seconds in WINDOWS.items():
            subset = [e for e in episodes if e["ts"] >= now-seconds]
            auto = [e for e in subset if not e["outcome"].startswith("manual_")]
            windows[name] = dict(automatic=len(auto), verified=sum(e["outcome"]=="verified" for e in auto),
                                 failed=sum(e["outcome"] in ("failed","attention") for e in auto),
                                 unconfirmed=sum(e["outcome"]=="unconfirmed" for e in auto),
                                 manual=len(subset)-len(auto))
        recent = []
        for episode in reversed([e for e in episodes if e["ts"]>=now-WINDOWS["30d"]][-10:]):
            recent.append({k:v for k,v in episode.items() if k not in ("id","last","ts")}|{"time_utc":utc(episode["ts"])})
        scan = float(meta["last_scan"])
        return dict(base, status="observed" if 0<=now-scan<=INTERVAL*3 else "stale",
                    windows=windows, recent=recent, last_scan_utc=utc(scan),
                    bounded=meta.get("bounded")=="1" or history_limited, memory_pending=pending)
    except (OSError, sqlite3.Error, ValueError, KeyError, OverflowError):
        return base


def worker(root, permitted, mqtt_enabled):
    while True:
        try:
            if permitted():
                collect(root, notify=mqtt_enabled())
        except Exception as exc:
            LOG.warning("Recovery history observation unavailable: %s", exc)
        time.sleep(INTERVAL)


def start_worker(root, permitted, mqtt_enabled):
    global _started
    with LOCK:
        if _started:
            return
        _started = True
        threading.Thread(target=worker, args=(root, permitted, mqtt_enabled),
                         name="sdrcc-recovery-history", daemon=True).start()
