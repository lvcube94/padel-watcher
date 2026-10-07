#!/usr/bin/env python3
"""Padel-Watcher: meldet per Telegram neu frei gewordene Playtomic-Slots.

Ablauf je Lauf:
1. Platztypen (indoor/outdoor) je Club von der Playtomic-Clubseite lesen
   (einmal pro Tag, Zwischenspeicher in state.json).
2. Fuer jeden aktiven Club und jedes passende Datum die Verfuegbarkeit abfragen.
3. Slots auf lokale Startzeit im Fenster filtern (API liefert UTC).
4. Mit dem Stand des letzten Laufs vergleichen; nur neue Slots melden,
   getrennt nach Indoor und Outdoor, mit OePNV-Fahrzeit ab Buero.
5. state.json schreiben.

Nur Python-Standardbibliothek, keine Installation noetig.
Umgebungsvariablen: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Optional: DRY_RUN=1 (nichts senden, Nachricht nur ausgeben).
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "state.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WEEKDAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WORKERS = 4
COURT_CACHE_HOURS = 24
TG_LIMIT = 3900

RESOURCE_RE = re.compile(
    r'\{"resourceId":"([0-9a-f-]{36})","name":"([^"]*)","sport":"([A-Z_]+)",'
    r'"features":\[([^\]]*)\]\}')


# ---------------------------------------------------------------- HTTP
def http_get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def fetch_availability(tenant_id, day):
    """Liste [{resource_id, start_date, slots:[{start_time,duration,price}]}], start_time in UTC.
    Erst der Endpunkt der Playtomic-Website, dann die oeffentliche API als Fallback."""
    d = day.isoformat()
    urls = [
        "https://playtomic.com/api/clubs/availability?" + urllib.parse.urlencode(
            {"tenant_id": tenant_id, "date": d, "sport_id": "PADEL"}),
        "https://api.playtomic.io/v1/availability?" + urllib.parse.urlencode(
            {"tenant_id": tenant_id, "sport_id": "PADEL",
             "local_start_min": f"{d}T00:00:00", "local_start_max": f"{d}T23:59:59"}),
    ]
    last_err = None
    for url in urls:
        try:
            data = json.loads(http_get(url))
            if isinstance(data, list):
                return data
            last_err = f"unerwartete Antwort von {url[:45]}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{url[:45]}: {e}"
    raise RuntimeError(last_err)


def parse_courts(html):
    """Liest Courts aus der Clubseite: {resource_id: [name, 'indoor'|'outdoor'|'unbekannt']}."""
    text = html.replace('\\"', '"')
    courts = {}
    for rid, name, sport, feats in RESOURCE_RE.findall(text):
        if sport != "PADEL":
            continue
        name = re.sub(r"\\+u0026", "&", name).replace("•", " ").replace("\\", "")
        name = re.sub(r"\s+", " ", name).strip()
        typ = "indoor" if '"indoor"' in feats else "outdoor" if '"outdoor"' in feats else "unbekannt"
        courts[rid] = [name, typ]
    return courts


def fetch_courts(slug):
    return parse_courts(http_get(f"https://playtomic.com/clubs/{slug}", accept="text/html"))


# ---------------------------------------------------------------- Logik
def active_clubs(cfg):
    return [c for c in cfg["clubs"]
            if c.get("active") and c.get("travel_min", 0) <= cfg.get("max_travel_min", 999)]


def target_dates(cfg, today):
    return [today + timedelta(days=i) for i in range(cfg["days_ahead"] + 1)
            if (today + timedelta(days=i)).weekday() in cfg["weekdays"]]


def refresh_courts(cfg, cache, fetch=fetch_courts, now_utc=None):
    """Aktualisiert den Court-Zwischenspeicher je Club, wenn aelter als COURT_CACHE_HOURS."""
    now_utc = now_utc or datetime.now(timezone.utc)
    for club in active_clubs(cfg):
        entry = cache.get(club["slug"])
        if entry and now_utc - datetime.fromisoformat(entry["fetched"]) < timedelta(hours=COURT_CACHE_HOURS):
            continue
        try:
            courts = fetch(club["slug"])
            if courts:
                cache[club["slug"]] = {"fetched": now_utc.isoformat(timespec="seconds"),
                                       "courts": courts}
        except Exception as e:  # noqa: BLE001
            print(f"WARN Courts {club['slug']}: {e}", file=sys.stderr)
    return cache


def collect_slots(cfg, court_cache, fetch=fetch_availability, now=None):
    """Gibt (slots_dict, failed_club_slugs) zurueck."""
    tz = ZoneInfo(cfg["timezone"])
    now = now or datetime.now(tz)
    earliest = datetime.strptime(cfg["earliest_start"], "%H:%M").time()
    latest = datetime.strptime(cfg["latest_start"], "%H:%M").time()

    jobs = [(club, day) for club in active_clubs(cfg)
            for day in target_dates(cfg, now.date())]

    def run(job):
        club, day = job
        try:
            return club, day, fetch(club["tenant_id"], day), None
        except Exception as e:  # noqa: BLE001
            return club, day, None, e

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(run, jobs))

    slots, failed = {}, set()
    for club, day, data, err in results:
        if err is not None:
            print(f"WARN {club['slug']} {day}: {err}", file=sys.stderr)
            failed.add(club["slug"])
            continue
        courts = court_cache.get(club["slug"], {}).get("courts", {})
        for res in data:
            rid = res.get("resource_id", "")
            court_name, court_type = courts.get(rid, [f"Court {rid[:6]}", "unbekannt"])
            for s in res.get("slots", []):
                start = datetime.fromisoformat(f"{res['start_date']}T{s['start_time']}") \
                    .replace(tzinfo=timezone.utc).astimezone(tz)
                if start.weekday() not in cfg["weekdays"]:
                    continue
                if not (earliest <= start.time() <= latest) or start <= now:
                    continue
                key = f"{club['slug']}|{rid}|{start.isoformat()}"
                entry = slots.setdefault(key, {
                    "club": club["name"], "slug": club["slug"],
                    "travel": club.get("travel_min"), "court": court_name,
                    "type": court_type, "start": start.isoformat(),
                    "durations": [], "prices": []})
                if s["duration"] not in entry["durations"]:
                    entry["durations"].append(s["duration"])
                    entry["prices"].append(s.get("price", ""))
    return slots, failed


def diff_new(current, previous_keys):
    return {k: v for k, v in current.items() if k not in previous_keys}


def merge_state(current, previous, failed):
    """Bei Abruffehler den alten Stand des Clubs behalten, sonst kaeme beim
    naechsten erfolgreichen Lauf alles als 'neu'."""
    merged = dict(current)
    for k, v in previous.items():
        if k.split("|")[0] in failed:
            merged[k] = v
    return merged


# ---------------------------------------------------------------- Nachricht
def fmt_slot(s):
    st = datetime.fromisoformat(s["start"])
    opts = []
    for dur, price in sorted(zip(s["durations"], s["prices"])):
        end = (st + timedelta(minutes=dur)).strftime("%H:%M")
        opts.append(f"bis {end} ({dur} min{', ' + price if price else ''})")
    travel = f"{s['travel']} min ÖPNV" if s.get("travel") is not None else "Fahrzeit [ ]"
    return (f"{WEEKDAY_DE[st.weekday()]} {st:%d.%m.} {st:%H:%M} {' / '.join(opts)}\n"
            f"   {s['club']} | {travel} | {s['court']}")


def chunk(lines, limit=TG_LIMIT):
    out, cur = [], ""
    for ln in lines:
        if cur and len(cur) + len(ln) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + ln
    if cur:
        out.append(cur)
    return out


def build_messages(new_slots, header_suffix=""):
    msgs = []
    for typ, label in (("indoor", "INDOOR"), ("outdoor", "OUTDOOR"),
                       ("unbekannt", "TYP UNBEKANNT")):
        group = sorted((s for s in new_slots.values() if s["type"] == typ),
                       key=lambda s: (s["start"], s.get("travel") or 999, s["court"]))
        if not group:
            continue
        lines = [f"Padelplatz {label} frei{header_suffix} ({len(group)}):"]
        lines += [fmt_slot(s) for s in group]
        clubs = sorted({(s.get("travel") or 999, s["slug"]) for s in group})
        lines.append("Buchen: " + " ".join(f"playtomic.com/clubs/{sl}" for _, sl in clubs))
        msgs += chunk(lines)
    return msgs


def send_telegram(text):
    if os.environ.get("DRY_RUN") == "1":
        print("---- DRY RUN ----\n" + text)
        return
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    body = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()
    time.sleep(1)


# ---------------------------------------------------------------- Main
def save(state):
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    first_run = not STATE_FILE.exists()
    state = {} if first_run else json.loads(STATE_FILE.read_text(encoding="utf-8"))
    previous = state.get("slots", {})
    court_cache = refresh_courts(cfg, state.get("courts", {}))

    current, failed = collect_slots(cfg, court_cache)
    active = {c["slug"] for c in active_clubs(cfg)}

    if active and active <= failed:
        if not state.get("error_notified"):
            send_telegram("Padel-Watcher: Abfrage bei Playtomic schlaegt fehl. "
                          "Bitte GitHub-Actions-Log pruefen.")
            state["error_notified"] = True
            state["courts"] = court_cache
            save(state)
        print("Alle Abfragen fehlgeschlagen", file=sys.stderr)
        return  # Exit 0: Hinweis kam per Telegram, keine GitHub-Fehlermail alle 10 Min.

    new = diff_new(current, previous.keys())
    for msg in build_messages(new, " (Startstand)" if first_run else ""):
        send_telegram(msg)
    if first_run and not new:
        send_telegram("Padel-Watcher aktiv. Aktuell keine freien Slots im Suchfenster.")

    save({"slots": merge_state(current, previous, failed),
          "courts": court_cache,
          "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "error_notified": False})
    print(f"{len(current)} passende Slots, davon {len(new)} neu; Fehler: {sorted(failed)}")


if __name__ == "__main__":
    main()
