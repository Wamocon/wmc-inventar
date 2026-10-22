# Hinweise für KI-Agenten

Projekt: WMC Inventar, internes Web-Tool der WAMOCON-IT für die Verwaltung von Bürohardware: Inventar, Ausgabe, Verleih, Rückgabe, Ausmusterung, Soll-Ausstattung je Arbeitsplatz und digital signierte Übergabeprotokolle. Sprache in Oberfläche, Code-Kommentaren, Texten und Commits: Deutsch.

| Rolle | Wer | Zweig | Auftrag |
|---|---|---|---|
| Entwicklung | Gregor, KI-Mitarbeiter | `gregor/inventar` | `docs/AUFTRAG.md` |
| Test | Theo, KI-Mitarbeiter | `theo/inventar` | `docs/TESTAUFTRAG.md` |
| Prüfung | Claude | | nach Gregors Meldung |
| Abnahme | Erwin Moretz, IT | | |

Lies zuerst deinen Auftrag. Maßgeblich für den Inhalt ist `docs/anforderungen.md` (Version 0.5), für die Protokolle `docs/vorlagen/FRM-001.md` und `FRM-002.md`, für das Aussehen der Prototyp `mockup/wmc-inventar-prototyp.html` und die Bilder in `docs/design/`. Die Daten im Prototyp sind Anschauung. Wie Anwendung und Tests zusammenpassen, regelt `docs/TESTSCHNITTSTELLE.md`; Gregor baut sie so, Theo testet dagegen.

## Regeln für alle

- Nie auf `main` arbeiten. Gregor committet nur auf `gregor/inventar`, Theo nur auf `theo/inventar`. Der Git-Bus lehnt Force-Push und das Löschen von Zweigen ab; Fehler korrigierst du mit einem neuen Commit.
- Nicht ändern: `AGENTS.md`, `CLAUDE.md`, `docs/anforderungen.md`, `docs/AUFTRAG.md`, `docs/TESTAUFTRAG.md`, `docs/TESTSCHNITTSTELLE.md`, `docs/design/`, `docs/vorlagen/`, `mockup/`, `static/vendor/`, `static/fonts/`, `requirements.txt`, `requirements-test.txt`. Fehlt dort etwas oder ist etwas falsch, frag nach.
- Das Repository ist öffentlich. Keine Zugangsdaten, Zertifikate, Schlüssel und keine echten Personendaten. Die echte Bestandsliste `WMC_Hardwarebestand.xlsx` und Beispiel-PDFs der Protokolle gehören nicht hinein.
- Auf der DGX gibt es kein Internet. Installiert ist, was in `requirements.txt` steht (Theo zusätzlich `requirements-test.txt`), in `.venv` im Klon. Andere Pakete gibt es nicht; brauchst du eines, frag nach. Die Anwendung lädt nichts von fremden Servern, htmx und die Schrift Archivo liegen unter `static/`.
- Fehlt ein Werkzeug (Docker, PostgreSQL, Browser), umgehe das nicht. Schreib es in die Übergabe oder den Testbericht.
- Commit-Nachrichten: „Bereich: was (IDs)“, z. B. „Ausgabe: Protokoll nach FRM-001 (F-21, F-130)“.
- Das 8-Bit-Büro im Prototyp (geheime Tastenfolge) ist ein Easter Egg und keine Anforderung. Nicht bauen, nicht testen.

## Regeln für den Code (Gregor)

- Statuswechsel eines Geräts nur über die Service-Schicht: eine Funktion je Vorgang, eine Transaktion. Views, Import und Jobs ändern den Status nie direkt.
- Vorgänge (Historie), Signaturen und Prüfprotokolle werden nur angelegt, nie geändert oder gelöscht.
- Nach der ersten Signatur ist ein Protokoll gesperrt; Korrekturen erzeugen eine neue Fassung mit neuer Nummer. Eine Rücknahme gilt erst mit der Gegenzeichnung als abgeschlossen, auf Papier mit dem Scan beider Unterschriften (F-141, F-22).
- Der Import überschreibt nie einen vorhandenen Wert. Er füllt leere Felder und meldet Abweichungen als Konflikt (F-84).
- Rechte immer serverseitig prüfen. Für jede Ansicht ein Test, dass die Rolle Mitarbeiter keine fremden Daten sieht.
- Oberfläche auf Deutsch, Datum TT.MM.JJJJ, Beträge in EUR, Zeitzone Europe/Berlin. WAMOCON-Farben wie im Prototyp. Status nie nur über Farbe anzeigen.
- Jede Anforderung mit Abnahmekriterium bekommt mindestens einen Test im Django-Testrunner.
- Die Bedienelemente aus `docs/TESTSCHNITTSTELLE.md` tragen die dort genannten `data-test`-Attribute und Texte. Formularfelder haben ein sichtbares `<label>`.

## Regeln für die Tests (Theo)

- Theo ändert nur `tests/robot/` und `docs/TESTBERICHT.md`, nie den Produktcode.
- Jeder Testfall trägt die Anforderungs-ID als Tag und beschreibt in `[Documentation]`, was er prüft.

## Befehle

Gregor, im Klon `~/WAMOCON/wmc-inventar`:

```
source .venv/bin/activate
export INVENTAR_DEBUG=1
python manage.py migrate
python manage.py beispieldaten
python manage.py test
```

Theo startet Gregors Stand wie in `docs/TESTSCHNITTSTELLE.md`, Abschnitt 1.1, und lässt die Suite aus seinem Klon `~/WAMOCON/wmc-inventar-tests` laufen:

```
.venv/bin/robot --outputdir tests/robot/ergebnisse --variable BASIS_URL:http://127.0.0.1:8000 --variable APP_PFAD:$HOME/WAMOCON/wmc-inventar-app tests/robot
```
