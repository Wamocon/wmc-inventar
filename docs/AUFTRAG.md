# Auftrag: WMC Inventar, Version 1

| | |
|---|---|
| Jira | Epic WMCNL-2755, Meilensteine WMCNL-2756 bis WMCNL-2762 |
| Auftraggeber | Erwin Moretz, IT |
| Ausführung | Gregor, KI-Mitarbeiter Entwicklung |
| Tests | Theo, KI-Mitarbeiter Test, parallel auf `theo/inventar` (`docs/TESTAUFTRAG.md`) |
| Prüfung | Claude; danach Abnahme durch Erwin |
| Zweig | `gregor/inventar` |

## Ziel

Die IT von WAMOCON verwaltet ihre Bürohardware in einem eigenen Web-Tool statt in der Excel-Liste `WMC_Hardwarebestand.xlsx`. Du baust Version 1 vollständig: alle Anforderungen aus `docs/anforderungen.md`, Kapitel 5 und 7, in der Reihenfolge der Meilensteine M1 bis M7 aus Kapitel 9.

## Was im Repo schon liegt

| Pfad | Inhalt |
|---|---|
| `docs/anforderungen.md` | Was gebaut wird: 93 Anforderungen F-xx mit Abnahmekriterium, N-01 bis N-11, Statusmodell, Datenmodell. Maßgeblich. |
| `docs/TESTSCHNITTSTELLE.md` | Umgebungsvariablen, Befehle, Beispieldaten, Adressen, `data-test`-Markierungen, feste Texte. Verbindlich, Theos Tests bauen darauf. |
| `mockup/wmc-inventar-prototyp.html` | Klickbarer Prototyp mit allen Bildschirmen, Texten und Abläufen in einer Datei. Du liest ihn im Quelltext: Bildschirme sind Funktionen `view…`, Dialoge `dlg…`, Beschriftungen stehen in `<label>` und auf den Schaltflächen. Kein Produktivcode; seine Daten sind Anschauung. Er lädt Schriften von Google und einen QR-Generator von cdnjs, die Anwendung nicht. |
| `docs/design/` | Bilder der Kernbildschirme aus dem Mockup, darunter das erzeugte Ausgabeprotokoll |
| `docs/vorlagen/FRM-001.md`, `FRM-002.md` | Aufbau, Satzbild und Wortlaut der Protokolle als Text. Maßgeblich für die PDFs und die Checklisten. |
| `docs/vorlagen/bestandsliste_anonymisiert.xlsx` | Testfassung der Bestandsliste mit echten Lücken; erwartete Eckwerte in `docs/vorlagen/README.md` |
| `docs/vorlagen/grundriss_eschborn_1og.svg` | Grundriss für den Raumplan |
| `static/vendor/htmx.min.js`, `static/fonts/` | htmx 2 und die Schrift Archivo, lokal |
| `requirements.txt` | alle Pakete, die du hast; installiert in `.venv` |
| `docs/UEBERGABE.md` | Vorlage für deine Übergabe |

## Was du lieferst

| Pfad | Inhalt |
|---|---|
| `manage.py`, Projektpaket und Apps | die Anwendung (Django 5.2, serverseitige Templates, htmx) |
| Tests im Django-Testrunner | mindestens ein Test je Anforderung mit Abnahmekriterium (N-10) |
| Management-Befehle | `beispieldaten`, `testsiegel`, `tageslauf` wie in `docs/TESTSCHNITTSTELLE.md` |
| `Dockerfile`, `docker-compose.yml` | Dienste `web`, `db` (PostgreSQL), `cron` (ruft `tageslauf` auf), Volumes für Datenbank und Dateien (N-01) |
| `scripts/sicherung.sh` | täglicher Datenbank-Dump und Kopie der Dateiablage (N-06) |
| `.env.example` | alle Variablen, ohne echte Werte |
| `README.md` | ersetzt die jetzige: Einrichtung, Betrieb, Sicherung, Rücksicherung (N-11) |
| `docs/UEBERGABE.md` | ausgefüllt |

## Vorgehen

1. Lies `docs/anforderungen.md`, `docs/TESTSCHNITTSTELLE.md` und `docs/vorlagen/` vollständig, dazu den Prototyp im Quelltext.
2. Lege den Zweig an: `git switch -c gregor/inventar`.
3. Arbeite die Meilensteine der Reihe nach ab. Den nächsten beginnst du erst, wenn die Tests des aktuellen grün sind.
4. Nach jedem Meilenstein: committen, `python manage.py test` grün, in `docs/UEBERGABE.md` unter „Stand je Meilenstein“ eine Zeile eintragen und den Zweig in den Git-Bus pushen (`git push origin gregor/inventar`). Theo testet jeden gepushten Stand. Melden musst du erst am Ende.
5. Am Ende: `README.md` schreiben, `docs/UEBERGABE.md` vollständig ausfüllen, pushen, melden.

| Meilenstein | Umfang | Woran du denken musst |
|---|---|---|
| M1 Grundgerüst | Projekt, Einstellungen über Umgebungsvariablen, Anmeldung mit Sperre, Konten und Rollen, Kategorien, Personen, Orte, Befehl `beispieldaten`, Docker Compose | Rechteprüfung serverseitig von Anfang an. Argon2id für Passwörter. Sicherheitsheader inkl. Content-Security-Policy ohne Inline-Skripte. |
| M2 Bestand | Erfassen, Liste, Detail, Historie, Suche, Import mit Zusammenführung, Arbeitsliste „Daten unvollständig“ | Den Import gegen die anonymisierte Testdatei prüfen; die Eckwerte aus `docs/vorlagen/README.md` müssen herauskommen. |
| M3 Lebenszyklus | Ausgabe, Rückgabe, Umzug, Reparatur, Ausmusterung, Protokoll-PDF nach WMC-IT-FRM-001 und -002 mit Checklisten und Fotos, Papierweg | Alle Übergänge aus Kapitel 4 in der Service-Schicht, jeder mit Test, auch die verbotenen. PDFs nach `docs/vorlagen/FRM-001.md` und `FRM-002.md`, Wortlaut der Checklisten von dort. Bis M6 endet jedes Protokoll im Papierweg (F-22): Stand „Unterschrift offen: Scan fehlt“, abgeschlossen mit dem Scan. Das Gerät ist ab dem Speichern der Ausgabe „In Benutzung“, weil der Bearbeiter auf Papier unterschreibt. |
| M4 Arbeitsplätze | Profile, Soll-Ist-Abgleich, Bedarfsliste, Raumplan mit Pop-up, Plan bearbeiten, QR-Etiketten, Erstinventur am Smartphone | Raumplan wie im Prototyp, aber mit hochgeladenem Grundriss und Positionen in Prozent (F-67). Ab 360 px Breite bedienbar. |
| M5 Verleih | Anfrage, Freigabe, Doppelbuchung, Ausgabe, Verlängerung, Self-Service | Mitarbeiter sehen nur Eigenes (F-112), auch beim direkten Aufruf fremder Adressen. |
| M6 Signatur | Signatur des Bearbeiters, Gegenzeichnung per Mail mit Einmalcode, Prüfprotokoll, Siegel, Versand | Einmalcode 6-stellig, 10 Minuten, 5 Versuche; Link 14 Tage. Siegel mit pyHanko und `SIEGEL_P12`. Rücknahme nur mit Gegenzeichnung abschließbar (F-141). |
| M7 Abschluss | Erinnerungen über `tageslauf`, Übersicht mit Kennzahlen und Delta, Export, Sicherung, Kennzahlen-Schnittstelle | Kennzahlen als IST/Gesamt (F-100). Jede Mailart abschaltbar, keine Mails an deaktivierte Konten (F-96). |

Welche Anforderung zu welchem Meilenstein gehört, steht in `docs/UEBERGABE.md` in Spalte M. Steht dort „M3, M6“, baust du im ersten Meilenstein den Teil ohne Signatur, Mail oder Tageslauf und im zweiten den Rest; eingetragen wird der Stand nach dem zweiten.

## Regeln

- Halte dich an `AGENTS.md`. Die dort genannten Dateien änderst du nicht.
- Nur Pakete aus `requirements.txt`. Kein npm, keine CDN-Adressen, kein Build-Schritt für das Frontend.
- Protokoll-PDFs setzt du in Arial Narrow, wenn die Schrift auf dem System liegt, sonst in Archivo mit `font-stretch: condensed` (N-09). WeasyPrint wählt die schmale Archivo nur mit `condensed`, nicht mit einer Prozentangabe. Prüf das PDF selbst: Text vorhanden, Seitenzahlen „Seite x von y“, Fußzeile mit Formularnummer.
- Signiert wird mit Passwort (Bearbeiter) und Einmalcode (Mitarbeiter). Eine gezeichnete Unterschrift gibt es in Version 1 nicht.
- Datenbank: Im Betrieb PostgreSQL, ohne `DATABASE_URL` SQLite. Die Tests müssen mit beiden laufen; nutz keine Funktionen, die es nur in einer der beiden gibt.
- Views prüfst du mit dem Django-Testclient. Ob du auf der DGX einen Server starten darfst, regelt deine Grenze; einen Browser hast du nicht.
- Mails gehen über Djangos Mail-System, damit `MAIL_ABLAGE` greift.
- Keine echten Personendaten, keine echten Firmenlinks, keine Zugangsdaten. Testdaten nur aus `docs/TESTSCHNITTSTELLE.md` und `docs/vorlagen/`.
- Fehlt ein Werkzeug (Docker, PostgreSQL, WeasyPrint-Bibliotheken), umgehe das nicht, sondern schreib es in die Übergabe. Ohne Docker schreibst du `Dockerfile`, `docker-compose.yml` und `scripts/sicherung.sh` trotzdem; N-01 und N-06 stehen dann als „teilweise“ mit dem Hinweis, dass der Bau nicht geprüft ist. Ist Docker da, hat die Einrichtung `postgres:16` und ein lokales Basis-Image `wmc-inventar-basis:1` geladen (`python:3.12-slim` mit Pango, HarfBuzz und cron) und alle Pakete aus `requirements.txt` als Wheels nach `wheelhouse/` gelegt (nicht im Repo). Schreib das `Dockerfile` so, dass es mit `--build-arg BASIS=wmc-inventar-basis:1 --build-arg WHEELHOUSE=wheelhouse` ohne Internet baut und ohne diese Argumente im Betrieb aus dem Netz: `FROM ${BASIS}` mit Standard `python:3.12-slim`, Systempakete nur per `apt-get` nachinstallieren, wenn sie fehlen, und `pip install --no-index --find-links`, wenn `WHEELHOUSE` gesetzt ist.

## Rückfragen

Bei Widerspruch oder Lücke: erst in `docs/anforderungen.md`, `docs/TESTSCHNITTSTELLE.md` und im Prototyp nachsehen. Bleibt es unklar, schick Erwin über Hermes eine Frage mit ID, kurzem Zitat und deinem Vorschlag. Arbeite bis zur Antwort mit deinem Vorschlag weiter und trag ihn in der Übergabe unter „Annahmen“ ein. Fehlermeldungen von Theo kommen ebenfalls über Hermes; behebe sie im laufenden oder nächsten Meilenstein.

## Fertig, wenn

- [ ] Alle sieben Meilensteine sind umgesetzt und je Meilenstein in `docs/UEBERGABE.md` eingetragen.
- [ ] Jede ID aus Kapitel 5 und 7 steht in `docs/UEBERGABE.md` mit Stand (erfüllt, teilweise, nicht erfüllt) und Nachweis.
- [ ] `python manage.py test` ist grün, mit SQLite und, wenn verfügbar, mit PostgreSQL.
- [ ] `python manage.py migrate`, `beispieldaten`, `testsiegel` und `tageslauf --stichtag …` laufen in einer leeren Datenbank ohne Fehler.
- [ ] Der Import der Testdatei ergibt die Eckwerte aus `docs/vorlagen/README.md`.
- [ ] Alles ist auf `gregor/inventar` committet und im Git-Bus; `main` ist unverändert.
- [ ] Meldung an Erwin: „WMCNL-2755 fertig, Zweig gregor/inventar, letzter Commit HASH“.

## Wie geprüft wird

Theo prüft jeden gepushten Stand mit Robot Framework gegen die Abnahmekriterien; seine Tests liegen offen auf `theo/inventar` (`git fetch origin`, dann `git show origin/theo/inventar:…`). Du darfst sie lesen; laufen lassen kannst du sie ohne Browser nicht. Nach deiner Meldung prüft Claude jede ID mit eigenen Tests, am Code und an den erzeugten PDFs, dazu Zweig, Commits und geschützte Dateien. Was in der Übergabe als „erfüllt“ steht, muss sich so nachstellen lassen. Die Abnahme macht Erwin.
