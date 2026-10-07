# Padel-Watcher

Prüft alle 10 Minuten die Playtomic-Verfügbarkeit aller Berliner Clubs und schickt per Telegram eine Nachricht, wenn ein Slot neu frei wird. Indoor und Outdoor kommen als getrennte Nachrichten. Jeder Slot nennt die ÖPNV-Fahrzeit ab Büro.

Suchfenster: Mo–Fr, Start 18:00–23:00 Uhr, nächste 14 Tage.

Beispiel:

```
Padelplatz INDOOR frei (1):
Do 15.10. 20:30 bis 21:30 (60 min, 36 EUR)
   mitte – charlotte (Charlottenburg) | 22 min ÖPNV | 4 Double Court
Buchen: playtomic.com/clubs/mitte-charlotte
```

## Einrichtung (ca. 15 Min.)

### 1. Telegram-Bot anlegen

1. In Telegram `@BotFather` öffnen, `/newbot` senden, Namen vergeben.
2. Den angezeigten **Token** notieren (Format `123456:ABC...`).
3. Den neuen Bot öffnen und ihm eine beliebige Nachricht schicken.
4. Im Browser aufrufen: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Unter `"chat":{"id": ...}` steht die **Chat-ID**.

### 2. GitHub-Repository anlegen

1. Neues Repository auf github.com, Sichtbarkeit **Public** (Begründung unten).
2. Alle Dateien dieses Ordners hochladen, inkl. `.github/workflows/padel.yml`.
   Falls der Web-Upload den Punkt-Ordner nicht übernimmt: „Add file > Create new file“, Dateiname `.github/workflows/padel.yml`, Inhalt einfügen.
3. Settings > Secrets and variables > Actions > „New repository secret“:
   - `TELEGRAM_BOT_TOKEN` = Token
   - `TELEGRAM_CHAT_ID` = Chat-ID
4. Settings > Actions > General > Workflow permissions: **Read and write permissions** (nötig zum Speichern von `state.json`).
5. Reiter Actions > „padel-watcher“ > „Run workflow“. Der erste Lauf schickt den aktuellen Stand („Startstand“), danach nur neue Slots.

## Anpassen (`config.json`)

| Feld | Wirkung |
|---|---|
| `weekdays` | 0 = Mo … 6 = So |
| `earliest_start` / `latest_start` | Startzeit-Fenster, lokale Zeit |
| `days_ahead` | Vorschau in Tagen |
| `max_travel_min` | nur Clubs bis zu dieser Fahrzeit, z. B. `35` (Standard 999 = alle) |
| `clubs[].active` | einzelnen Club an/aus |

## Clubs (Stand 07.10.2026)

Fahrzeit: ÖPNV Tür zu Tür ab Budapester Str. 35, Ankunft Mo 18:00, kürzeste von 4 Verbindungen. Quelle: VBB-Routing (v6.bvg.transport.rest). Plätze: Playtomic-Clubseite, Feld „features“.

| Club | Adresse | ÖPNV | Indoor | Outdoor |
|---|---|---|---|---|
| mitte – charlotte | Sophie-Charlotten-Str. 14 | 22 min | 5 | 0 |
| BeachMitte | Caroline-Michaelis-Str. 8 | 27 min | 0 | 5 |
| Padel Mitte (Wedding) | Müllerstr. 185 | 28 min | 0 | 4 |
| NIXE Padel (Wannsee) | Königstr. 4b | 31 min | 3 | 0 |
| Birgit (Kreuzberg) | Schleusenufer 3 | 34 min | 0 | 3 |
| Padel Lankwitz | Leonorenstr. 37 | 34 min | 0 | 4 |
| Füchse Berlin | Freiheitsweg 18 | 36 min | 0 | 4 |
| Kickerworld (Spandau) | Kl. Eiswerderstr. 1 | 37 min | 0 | 5 |
| TIO TIO Rooftop | Marktstr. 6 | 37 min | 0 | 5 |
| Padel Neukölln | Oderstr. 182 | 38 min | 0 | 6 |
| PadelBros (Wittenau) | Wittestr. 46 | 38 min | 8 | 0 |
| Padel Berlin Ostkreuz | Wiesenweg 1-4 | 42 min | 1 | 2 |
| PBC Center (Mariendorf) | Großbeerenstr. 2-10 | 42 min | 6 | 0 |
| PDLX Berlin (Lichterfelde) | Malteserstr. 139 | 42 min | 4 | 0 |
| Padel Tree @ Playground | Adlergestell 105 | 43 min | 0 | 4 |
| Padel Arena Berlin | Haberstr. 18 | 45 min | 0 | 14 |
| Padelhaus (Rummelsburg) | Köpenicker Chaussee 11-14 | 51 min | 7 | 2 |
| Padel Factory (Biesdorf) | Am Gewerbepark 5 | 60 min | 12 | 0 |
| Padel Marzahn | Gehrenseestr. 42a | 48 min | 9 | 0 |
| Rainbow Padel | Niederbarnimallee 116, Bernau | 76 min | 0 | 4 |

Padel Marzahn (Eröffnung laut Playtomic 2027) und Rainbow Padel (Bernau, außerhalb Berlins) sind deaktiviert. Nicht abgedeckt: 4PADEL Berlin, Königshorster Str. 11-15 (nicht auf Playtomic gelistet).

## Hinweise

- **Public statt Private:** Private Repos haben 2.000 Actions-Minuten/Monat frei, jeder Lauf zählt mindestens 1 Minute; alle 10 Min. ergibt ca. 4.300 Läufe/Monat. Public-Repos haben keine Minutengrenze. Zugangsdaten liegen nur in den Secrets, im Repo stehen Club-IDs und der Slot-Stand. Bei privatem Repo den Cron auf `*/30 * * * *` setzen.
- **Verzögerung:** GitHub startet geplante Läufe oft 5–15 Min. später als angegeben.
- **Inaktivität:** GitHub deaktiviert geplante Workflows in Public-Repos nach 60 Tagen ohne Repo-Aktivität. Commits von `state.json` zählen, solange sich der Slot-Stand ändert.
- **Playtomic:** Der Watcher nutzt den Endpunkt der Playtomic-Website (`playtomic.com/api/clubs/availability`), Fallback `api.playtomic.io`. Keine offizielle Schnittstelle; ändert Playtomic sie, meldet der Bot das einmal per Telegram. Automatisierte Abfragen sind in den Playtomic-Nutzungsbedingungen nicht ausdrücklich freigegeben. Last je Lauf: ca. 200 Abrufe (18 Clubs × 10–11 Termine), 4 parallel. Wer die Last senken will, setzt `max_travel_min`.
- **Platztyp:** Das Skript liest Indoor/Outdoor einmal täglich von der Clubseite. Klappt das nicht, steht der Slot unter „TYP UNBEKANNT“.
- **Zeitzone:** Playtomic liefert UTC; das Skript rechnet auf Berliner Zeit um, inkl. Zeitumstellung.
