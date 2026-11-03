# WMC Inventar

Internes Web-Tool der WAMOCON-IT für die Verwaltung von Bürohardware: Bestand, Ausgabe, Verleih, Rückgabe, Ausmusterung, Soll-Ausstattung je Arbeitsplatz mit Raumplan und digital signierte Übergabeprotokolle nach WMC-IT-FRM-001 und -002.

**Stand:** M7 Abschluss, Version 1 fertig. Alle 320 Tests grün. Zweig: `gregor/inventar`.

## Pfade

| Pfad | Inhalt |
|---|---|
| `AGENTS.md` | Regeln für alle, die im Repo arbeiten |
| `docs/anforderungen.md` | Anforderungen mit IDs, maßgeblich |
| `docs/AUFTRAG.md` | Auftrag an Gregor |
| `docs/TESTSCHNITTSTELLE.md` | Start, Beispieldaten, Adressen und Markierungen |
| `docs/UEBERGABE.md` | Übergabe mit Stand je Anforderung und Meilenstein |
| `Dockerfile` | Docker-Image für die Anwendung |
| `docker-compose.yml` | Betrieb: `db` (PostgreSQL 16), `web` (Django), `cron` (Tageslauf) |
| `scripts/sicherung.sh` | Tägliche Sicherung: Datenbank-Dump + Dateiablage |
| `requirements.txt` | Python-Pakete für die Anwendung |
| `static/` | htmx und Schrift Archivo, lokal |

## Einrichtung

### Mit Docker (empfohlen)

```bash
# 1. Umgebungsvariablen setzen
export INVENTAR_SECRET_KEY="ein-langer-zufaelliger-schluessel"

# 2. Starten
docker compose up -d

# 3. Migrations und Beispieldaten
docker compose exec web python manage.py migrate --noinput
docker compose exec web python manage.py beispieldaten --neu

# 4. Im Browser öffnen
# http://127.0.0.1:8000/
# Admin: it-admin@beispiel.test / Beispiel-Passwort-2026
```

### Ohne Docker (lokale Entwicklung)

```bash
# 1. Virtuelle Umgebung
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Migrations
INVENTAR_DEBUG=1 .venv/bin/python manage.py migrate

# 3. Beispieldaten
INVENTAR_DEBUG=1 .venv/bin/python manage.py beispieldaten --neu

# 4. Server starten
INVENTAR_DEBUG=1 .venv/bin/python manage.py runserver 0.0.0.0:8000
```

### Ohne Internet (Offline-Bau)

```bash
# Wheelhouse auf dem Zielsystem ablegen, dann:
docker build --build-arg BASIS=wmc-inventar-basis:1 --build-arg WHEELHOUSE=wheelhouse .
```

## Betrieb

### Umgebungsvariablen

| Variable | Zweck | Standard |
|---|---|---|
| `INVENTAR_DEBUG` | `1` für Entwicklung (SQLite), `0` für Produktion (PostgreSQL) | `1` |
| `INVENTAR_SECRET_KEY` | Django-Secret-Key | – |
| `DATABASE_URL` | PostgreSQL-Verbindung (bei `INVENTAR_DEBUG=0`) | – |
| `BASIS_URL` | Basis-URL für Mails und QR-Codes | `http://127.0.0.1:8000` |
| `MAIL_ABLAGE` | Pfad der Mailablage | `var/mails` |
| `DATEIABLAGE` | Pfad der Dateiablage | `var/dateien` |
| `KENNZAHLEN_TOKEN` | Bearer-Token für `/api/kennzahlen` (F-105) | – |
| `SIEGEL_P12` | Pfad zum Siegel-Zertifikat (F-138) | – |

### Dienste (docker-compose)

| Dienst | Aufgabe | Port |
|---|---|---|
| `db` | PostgreSQL 16, Datenbestand | 5432 (intern) |
| `web` | Django + WhiteNoise, HTTP | 8000 |
| `cron` | Stündlicher `tageslauf` (Mails, Deaktivierungen, Zählerstände) | – |

### Tageslauf

Der `cron`-Dienst ruft `manage.py tageslauf` stündlich auf. Er erledigt:

- **F-91:** Leihe endet morgen → Mail an die Person
- **F-92:** Leihe überfällig → Mail an Person und IT
- **F-94:** Garantie endet in 30 Tagen → Sammelmail an die IT (nur Montag)
- **F-95:** Unterschriften seit mehr als 3 Tagen offen → Sammelmail
- **F-140:** Erinnerung an die Gegenzeichnung am dritten Tag
- **F-53:** Deaktivierung von Konten am Tag nach dem Austritt
- **F-101:** Zählerstand für das Delta

### Kennzahlen-API (F-105)

```bash
curl -H "Authorization: Bearer <KENNZAHLEN_TOKEN>" http://127.0.0.1:8000/api/kennzahlen
```

## Sicherung (N-06)

### Tägliche Sicherung

```bash
# Manuell
scripts/sicherung.sh [Zielverzeichnis]

# Über cron (empfohlen)
0 3 * * * /path/zu/inventar/scripts/sicherung.sh /srv/inventar/sicherung
```

Das Skript erzeugt unter `<Ziel>/<Stempel>/`:

| Datei/Ordner | Inhalt |
|---|---|
| `inventar.sql.gz` | PostgreSQL-Dump (komprimiert) |
| `dateien/` | Kopie der Dateiablage (DATEIABLAGE) |
| `mails/` | Kopie der Mailablage (MAIL_ABLAGE) |

### Rücksicherung

#### PostgreSQL

```bash
# 1. Datenbank anlegen
createdb inventar

# 2. Dump einspielen
gunzip -c /srv/inventar/sicherung/<Stempel>/inventar.sql.gz | psql -d inventar

# 3. Migrations nachziehen (falls nötig)
python manage.py migrate
```

#### SQLite (Entwicklung)

```bash
# 1. Dump einspielen
sqlite3 var/inventar.sqlite3 < inventar.sql

# 2. Dateien zurückkopieren
cp -a /srv/inventar/sicherung/<Stempel>/dateien/ var/dateien/
cp -a /srv/inventar/sicherung/<Stempel>/mails/ var/mails/
```

#### Docker

```bash
# 1. Backup einspielen
docker compose exec -T db pg_restore -d inventar -c < /pfad/zum/inventar.sql

# 2. Dateien zurückkopieren
docker compose cp /pfad/zum/dateien web:/srv/inventar/var/dateien
docker compose cp /pfad/zum/mails web:/srv/inventar/var/mails
```

## Tests

```bash
# Alle Tests (320)
INVENTAR_DEBUG=1 .venv/bin/python manage.py test

# System-Check
INVENTAR_DEBUG=1 .venv/bin/python manage.py check

# Beispieldaten anlegen
INVENTAR_DEBUG=1 .venv/bin/python manage.py beispieldaten --neu

# Siegel-Tests
INVENTAR_DEBUG=1 .venv/bin/python manage.py testsiegel

# Tageslauf mit festem Stichtag
INVENTAR_DEBUG=1 .venv/bin/python manage.py tageslauf --stichtag 2026-11-02
```

## Lizenzen

- htmx unter Zero-Clause BSD (`static/vendor/LICENSE-htmx.txt`)
- Archivo unter SIL Open Font License 1.1 (`static/fonts/OFL.txt`)
