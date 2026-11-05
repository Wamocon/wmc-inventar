# WMC Inventar

Internes Web-Tool der WAMOCON-IT für die Verwaltung von Bürohardware: Bestand, Ausgabe, Verleih, Rückgabe, Ausmusterung, Soll-Ausstattung je Arbeitsplatz mit Raumplan und digital signierte Übergabeprotokolle nach WMC-IT-FRM-001 und -002.

## Pfade

| Pfad | Inhalt |
|---|---|
| `AGENTS.md` | Regeln für alle, die im Repo arbeiten |
| `docs/anforderungen.md` | Anforderungen mit IDs, maßgeblich |
| `docs/AUFTRAG.md` | Auftrag an Gregor |
| `docs/TESTSCHNITTSTELLE.md` | Start, Beispieldaten, Adressen und Markierungen |
| `docs/UEBERGABE.md` | Übergabe mit Stand je Anforderung und Meilenstein |
| `Dockerfile` | Docker-Image für die Anwendung |
| `docker-compose.yml` | Betrieb: `proxy` (HTTPS), `web` (gunicorn), `db` (PostgreSQL 16), `cron` (Tageslauf), `sicherung` |
| `deploy/nginx.conf` | Reverse Proxy mit internem Zertifikat |
| `scripts/sicherung.sh` | Tägliche Sicherung: Datenbank-Dump + Dateiablage |
| `requirements.txt` | Python-Pakete für die Anwendung |
| `static/` | htmx und Schrift Archivo, lokal |

## Einrichtung

### Betrieb mit Docker

Voraussetzung: internes TLS-Zertifikat, Firmenzertifikat für das Siegel (PKCS#12), SMTP-Zugang, ein Verzeichnis, das UrBackup erfasst.

```bash
# 1. Werte eintragen
cp .env.example .env

# 2. Starten; web migriert beim Start
docker compose up -d --build

# 3. Einmalig: Kategorien, erster Lagerort und Admin-Konto
docker compose exec -e ADMIN_EMAIL=it@firma.example -e ADMIN_PASSWORT='...' -e ADMIN_VORNAME=Vorname -e ADMIN_NACHNAME=Nachname web python manage.py startdaten
```

Danach unter `BASIS_URL` anmelden und in den Einstellungen Firmendaten, Logo und die verbindlichen Texte der Protokolle eintragen. Beispieldaten laufen nur im Entwicklungsmodus (`INVENTAR_DEBUG=1`).

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

Die vollständige Liste mit Pflichtwerten steht in `.env.example`.

| Variable | Zweck | Standard |
|---|---|---|
| `INVENTAR_DEBUG` | `1` für Entwicklung, sonst aus | aus |
| `INVENTAR_SECRET_KEY` | Django-Schlüssel, ohne Entwicklungsmodus Pflicht | – |
| `BASIS_URL` | Adresse für Mails und QR-Codes, ihr Host ist erlaubt | `http://127.0.0.1:8000` |
| `INVENTAR_HOSTS` | weitere erlaubte Hostnamen, kommagetrennt | – |
| `INVENTAR_PROXY` | `1` hinter dem eigenen Proxy: IP-Adresse aus `X-Forwarded-For` | aus |
| `DATABASE_URL` | PostgreSQL-Verbindung, ohne Angabe SQLite | – |
| `MAIL_ABSENDER`, `SMTP_*` | Mailversand | – |
| `MAIL_ABLAGE` | nur für Tests: Mails als Datei statt Versand | – |
| `DATEIABLAGE` | Pfad der Dateiablage | `var/dateien` |
| `SIEGEL_P12`, `SIEGEL_PASSWORT` | Siegel-Zertifikat (F-138). Ohne Siegel schließt kein Protokoll ab | im Entwicklungsmodus das Testsiegel |
| `KENNZAHLEN_TOKEN` | Bearer-Token für `/api/kennzahlen` (F-105) | – |

### Dienste (docker-compose)

| Dienst | Aufgabe | Port |
|---|---|---|
| `proxy` | nginx, HTTPS mit internem Zertifikat, setzt `X-Forwarded-For` | 443, 80 leitet um |
| `web` | gunicorn, Django, WhiteNoise | intern 8000 |
| `db` | PostgreSQL 16 | intern 5432 |
| `cron` | stündlicher `tageslauf` | – |
| `sicherung` | täglicher Dump und Kopie der Dateiablage nach `SICHERUNG_ZIEL` | – |

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

Der Dienst `sicherung` ruft `scripts/sicherung.sh /sicherung` einmal am Tag auf, `SICHERUNG_ZIEL` ist das Verzeichnis, das UrBackup erfasst. Stände älter als 30 Tage (`SICHERUNG_TAGE`) räumt das Skript weg.

Das Skript erzeugt unter `<Ziel>/<Stempel>/`:

| Datei/Ordner | Inhalt |
|---|---|
| `inventar.sql.gz` | PostgreSQL-Dump, komprimiert (ohne `DATABASE_URL`: `inventar.sqlite3`) |
| `dateien/` | Kopie der Dateiablage |

Scheitert ein Teil, endet es mit einem Fehler, und der Ordner behält die Endung `.unvollstaendig`.

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
cp /srv/inventar/sicherung/<Stempel>/inventar.sqlite3 var/inventar.sqlite3
rm -rf var/dateien && cp -a /srv/inventar/sicherung/<Stempel>/dateien var/dateien
```

#### Docker

```bash
# 1. Nur die Datenbank starten, damit beim Einspielen niemand schreibt
docker compose up -d db

# 2. Dump einspielen; er löscht vorhandene Tabellen und legt sie neu an
gunzip -c /pfad/zum/<Stempel>/inventar.sql.gz | docker compose exec -T db psql -q -U inventar -d inventar

# 3. Alle Dienste starten und die Dateien zurückkopieren
docker compose up -d
docker compose cp -a /pfad/zum/<Stempel>/dateien/. web:/srv/inventar/var/dateien
```

Das Image bringt `pg_dump` 17 mit, die Datenbank ist PostgreSQL 16. Deshalb meldet Schritt 2 einmal `unrecognized configuration parameter "transaction_timeout"`. Das ist harmlos; andere Fehler sind es nicht.

Am 05.11.2026 auf der DGX so gelaufen: Totalverlust mit `docker compose down -v`, Rücksicherung, Eckwerte gleich, ein signiertes Protokoll danach gegengezeichnet und versiegelt.

`SICHERUNG_ZIEL` muss für den Nutzer der Anwendung (UID 1000) schreibbar sein. Vor dem Go-live einmal testen (N-06).

## Tests

```bash
# Alle Tests (legt das Testsiegel selbst an, wenn es fehlt)
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
