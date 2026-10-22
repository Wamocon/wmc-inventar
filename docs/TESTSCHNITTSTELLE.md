# Testschnittstelle

Dieses Dokument legt fest, wie die Anwendung gestartet, mit Daten gefüllt und von außen angesprochen wird. Gregor baut die Anwendung so, Theo schreibt seine Tests dagegen, und beide können parallel arbeiten. Was hier steht, gilt zusätzlich zu `docs/anforderungen.md`; bei Widerspruch gilt die Anforderung, und wer ihn findet, fragt nach.

Die Daten im Prototyp (Geräte, Personen, Nummern, Leihen, Daten) sind Anschauung. Tests verlassen sich nur auf Abschnitt 2 und auf die Testdatei in `docs/vorlagen/`.

## 1 Start und Umgebung

Die Anwendung ist ein Django-Projekt im Wurzelverzeichnis des Repos (`manage.py`). Relative Pfade gelten ab diesem Verzeichnis, egal aus welchem Verzeichnis ein Befehl startet. Konfiguration nur über Umgebungsvariablen:

| Variable | Bedeutung | Ohne Angabe |
|---|---|---|
| `INVENTAR_DEBUG` | `1` schaltet den Entwicklungsmodus ein | aus |
| `INVENTAR_SECRET_KEY` | Django-Schlüssel | im Entwicklungsmodus ein fester Testwert, sonst Startabbruch |
| `DATABASE_URL` | z. B. `postgres://inventar:…@db:5432/inventar` | SQLite in `var/inventar.sqlite3` |
| `BASIS_URL` | Adresse für Links in Mails und QR-Codes, ohne Schrägstrich am Ende | `http://127.0.0.1:8000` |
| `MAIL_ABLAGE` | Verzeichnis: jede Mail wird als Datei dort abgelegt statt versendet (Abschnitt 1.3) | Versand über die SMTP-Einstellungen (F-90) |
| `DATEIABLAGE` | Protokolle, Fotos, Anhänge, Grundrisse | `var/dateien` |
| `SIEGEL_P12`, `SIEGEL_PASSWORT` | Zertifikat und Passwort für das Siegel (F-138) | im Entwicklungsmodus `var/testsiegel.p12` mit Passwort `testsiegel` |
| `KENNZAHLEN_TOKEN` | Token für `/api/kennzahlen` (F-105) | Schnittstelle aus, Antwort 404 |
| `BEISPIEL_PASSWORT` | Passwort aller Konten aus `beispieldaten` | `Beispiel-Passwort-2026` |

Befehle:

| Befehl | Wirkung |
|---|---|
| `python manage.py migrate` | Datenbank anlegen oder aktualisieren |
| `python manage.py beispieldaten` | Daten aus Abschnitt 2 anlegen. Bricht ab, wenn die Datenbank schon Konten hat. Mit `--neu` werden vorher Datenbankinhalt, `DATEIABLAGE`, `MAIL_ABLAGE` und `var/jetzt.txt` geleert. Läuft nur im Entwicklungsmodus. |
| `python manage.py testsiegel` | selbst signiertes Siegelzertifikat: `var/testsiegel.p12` (Passwort `testsiegel`) und das Zertifikat allein als `var/testsiegel.crt` (PEM), damit Tests das Siegel gegen dieses Zertifikat prüfen können. Nur Entwicklungsmodus. |
| `python manage.py tageslauf [--stichtag JJJJ-MM-TT]` | alle täglichen Aufgaben für den Tag: Erinnerungen und Sammelmail (F-91 bis F-95, F-140), Zählerstand für das Delta (F-101). Ohne Stichtag gilt heute. Der Cron-Container ruft genau diesen Befehl auf. |
| `python manage.py runserver 127.0.0.1:8000 --noreload` | Entwicklungsserver als ein Prozess |

Beim Stichtag rechnet der Tageslauf so, als wäre dieser Tag heute. Damit lassen sich Erinnerungen ohne Warten testen. Ein Tageslauf für denselben Stichtag verschickt nichts doppelt.

### 1.1 Lauf für Tests

So startet Theo die Anwendung. Arbeitsverzeichnis ist der Arbeitsbaum mit Gregors Stand; Python ist das aus Theos Klon, weil der Arbeitsbaum kein eigenes `.venv` hat:

```
PY=../wmc-inventar-tests/.venv/bin/python
export INVENTAR_DEBUG=1 MAIL_ABLAGE=var/mails KENNZAHLEN_TOKEN=test-kennzahlen
rm -rf var
$PY manage.py migrate
$PY manage.py testsiegel
$PY manage.py beispieldaten
$PY manage.py runserver 127.0.0.1:8000 --noreload > var/server.log 2>&1 &
echo $! > var/server.pid
# Tests …
kill "$(cat var/server.pid)"
```

`rm -rf var` vor jedem neuen Stand, weil sich Migrationen zwischen zwei Ständen ändern können. Während der Server läuft, darf eine Suite `beispieldaten --neu` aufrufen.

### 1.2 Uhr im Entwicklungsmodus

Fristen lassen sich nicht in Echtzeit abwarten (Sperre 15 Minuten, Einmalcode 10 Minuten, Links 1 Stunde, 72 Stunden und 14 Tage, Sitzungsende 8 Stunden). Im Entwicklungsmodus gilt deshalb:

- Liegt die Datei `var/jetzt.txt` vor, ist ihr Inhalt die aktuelle Zeit der Anwendung, Format `JJJJ-MM-TTTHH:MM` in Europe/Berlin, z. B. `2026-11-02T09:30`. Ohne Datei gilt die echte Zeit.
- Die Datei wird bei jeder Anfrage neu gelesen; ein Neustart ist nicht nötig.
- Alle zeitabhängigen Prüfungen und Vorbelegungen nutzen diese Zeit: Sperre nach Fehlversuchen, Gültigkeit von Links und Einmalcodes, Sitzungsende, Rückgabefristen, „überfällig“, Datumsvorbelegung in Formularen, Zeitstempel von Vorgängen und Signaturen.
- Zähler für Fehlversuche, Sperren, Einmalcodes und Links liegen in der Datenbank, nicht im Speicher des Prozesses.
- Ohne Entwicklungsmodus wird die Datei ignoriert.

### 1.3 Mailablage

Mit `MAIL_ABLAGE` schreibt die Anwendung jede Mail als eigene Datei in dieses Verzeichnis, statt sie zu versenden:

- Dateiname `JJJJMMTT-HHMMSS-NNNN.eml` mit der Zeit der Anwendung (Abschnitt 1.2) und einer laufenden Nummer. Die alphabetische Reihenfolge ist die Versandreihenfolge.
- Inhalt ist die vollständige Nachricht im Format RFC 5322, wie sie über SMTP ginge, mit allen Anhängen (z. B. dem Protokoll-PDF, F-139).
- Jede Mail hat einen Textteil. Links darin sind absolut und beginnen mit `BASIS_URL`.
- Eine Mail mit Einmalcode enthält im Textteil eine eigene Zeile `Einmalcode: 123456`.
- Eine Mail an mehrere Empfänger ist eine Datei.

## 2 Beispieldaten

`beispieldaten` legt nur Stammdaten und Einstellungen an, keine Geräte. Tests erzeugen ihre Geräte selbst (Erfassen oder Import). Mit `--demo` darf zusätzlich ein Demobestand entstehen; Tests verlassen sich nicht darauf.

Alle Konten haben das Passwort aus `BEISPIEL_PASSWORT`. Die Namen sind erfunden.

| E-Mail | Rolle | Person | Abteilung | Arbeitsplatz |
|---|---|---|---|---|
| `it-admin@beispiel.test` | Admin | Tobias Klein | IT | WMC-WP-09 |
| `gf@beispiel.test` | Leser | Martin Albers | Geschäftsführung | WMC-WP-13 |
| `anna.becker@beispiel.test` | Mitarbeiter | Anna Becker | Testmanagement | WMC-WP-01 |
| `felix.hoffmann@beispiel.test` | Mitarbeiter | Felix Hoffmann | Testmanagement | WMC-WP-02 |

Weitere Personen ohne Konto, je mit festem Arbeitsplatz: Jonas Weber (Entwicklung, WP-03), Elena Petrova (Entwicklung, WP-04), David Neumann (Testautomatisierung, WP-05), Murat Yılmaz (Testautomatisierung, WP-06), Sophie Wagner (Vertrieb, WP-07), Marie Richter (Buchhaltung, WP-08), Kai Brandt (IT, WP-10), Leonie Schmitt (Academy, WP-11), Lena Wolf (Academy, WP-12). Dazu Paul Schröder (Vertrieb) ohne Arbeitsplatz. E-Mail-Adressen nach dem Muster `vorname.nachname@beispiel.test`, Umlaute umgeschrieben (`murat.yilmaz@beispiel.test`).

Anrede nach Vorname (Herr oder Frau). Eintritt aller Personen am 01.01.2024, außer Felix Hoffmann am 15.09.2025. Eine Anschrift für den Briefkopf hat nur Anna Becker: Beispielweg 3, 65760 Eschborn. Kürzel einer Person sind die Anfangsbuchstaben von Vor- und Nachname (Tobias Klein: `TK`).

Einstellungen (F-122): Firmenname `WAMOCON GmbH`, Absenderzeile `WAMOCON GmbH · Mergenthalerallee 77 · 65760 Eschborn`, Telefon der IT `+49 6196 0000000`, E-Mail der IT `it-admin@beispiel.test`, kein Logo, Absender der Mails `inventar@beispiel.test`. Alle Mailarten an. Checklisten wie in `docs/vorlagen/FRM-001.md` und `FRM-002.md`, Protokolltexte der Abschnitte 4 bis 6 mit den Platzhaltern von dort, Version 1.

Kategorien: die Vorbelegung aus Kapitel 3.2 der Anforderungen. Datenträger haben Notebook, Desktop-PC, Smartphone, Tablet, Smartwatch, Kamera und Video, NAS und Drucker. Ohne Pflicht zur Seriennummer sind Tastatur, Maus, Headset, Notebook-Ständer, Powerbank, USB-Hub und Sonstiges (O-11, O-18).

Ausstattungsprofile:

| Profil | Positionen |
|---|---|
| Standard | 2 × Monitor, Dockingstation, Tastatur, Maus, Headset |
| Entwicklung | 2 × Monitor, Dockingstation, Tastatur, Maus, Headset, Webcam |
| Studio | 2 × Monitor, Dockingstation, Tastatur, Maus, Headset, Webcam |

Standort Eschborn, Etage 1. OG, ein Raumplan mit dem Grundriss `docs/vorlagen/grundriss_eschborn_1og.svg`. Positionen in Prozent von Breite und Höhe des Grundrisses, gemessen am Mittelpunkt:

| Kennung | Raum | Feste Person | Profil | x % | y % |
|---|---|---|---|---|---|
| WMC-WP-01 | Großraumbüro | Anna Becker | Standard | 50,1 | 55,6 |
| WMC-WP-02 | Großraumbüro | Felix Hoffmann | Standard | 64,1 | 55,6 |
| WMC-WP-03 | Großraumbüro | Jonas Weber | Entwicklung | 50,1 | 61,3 |
| WMC-WP-04 | Großraumbüro | Elena Petrova | Entwicklung | 64,1 | 61,3 |
| WMC-WP-05 | Großraumbüro | David Neumann | Entwicklung | 50,1 | 69,3 |
| WMC-WP-06 | Großraumbüro | Murat Yılmaz | Standard | 64,1 | 69,3 |
| WMC-WP-07 | Großraumbüro | Sophie Wagner | Standard | 50,1 | 75,1 |
| WMC-WP-08 | Großraumbüro | Marie Richter | Standard | 64,1 | 75,1 |
| WMC-WP-09 | Großraumbüro | Tobias Klein | Standard | 50,1 | 83,1 |
| WMC-WP-10 | Großraumbüro | Kai Brandt | Standard | 64,1 | 83,1 |
| WMC-WP-11 | Großraumbüro | Leonie Schmitt | Standard | 50,1 | 88,9 |
| WMC-WP-12 | Großraumbüro | Lena Wolf | Standard | 64,1 | 88,9 |
| WMC-WP-13 | Büro Geschäftsführung | Martin Albers | Standard | 10,4 | 62,7 |
| WMC-WP-14 | Büro Geschäftsführung | keine (Notiz: Gäste) | Standard | 24,3 | 62,7 |
| WMC-WP-15 | Studio | keine (Notiz: Studio-Arbeitsplatz) | Studio | 10,7 | 77,3 |

Orte vom Typ „Raum“ (F-68), Kennung, Name, Raum und Position x / y in %:

| Kennung | Name | Raum | x % | y % |
|---|---|---|---|---|
| STUDIO-TECHNIK | Studiotechnik | Studio | 24,1 | 87,3 |
| ACADEMY-TECHNIK | Academy-Technik | Academy-Raum | 77,4 | 36,9 |
| SERVER-TECHNIK | Serverschrank | Serverraum | 24,6 | 30,3 |
| EINGANG | Eingangsbereich | Großraumbüro | 44,6 | 44,7 |

Lagerort: Kennung `LAGER-EG`, Name „IT-Lager“.

Räume im Plan: Großraumbüro (1.01), Büro Geschäftsführung (1.02), Studio (1.03) sowie Küche, Serverraum, Pausenraum, Academy-Raum und Lernraum ohne Arbeitsplätze.

## 3 Adressen

Ohne Anmeldung leitet jede Seite auf `/anmelden/?next=…` um, außer Anmeldung, Passwort vergessen, Passwort setzen, Gegenzeichnung und `/api/kennzahlen` (eigene Prüfung über das Token). Fehlt die Berechtigung, antwortet die Anwendung mit Status 403 und der Seite „Keine Berechtigung“ (F-112). Eine unbekannte Inventar-, Leih- oder Protokollnummer ergibt 404.

| Seite | Pfad |
|---|---|
| Anmeldung | `/anmelden/` |
| Abmelden | `/abmelden/` (POST) |
| Passwort vergessen | `/passwort-vergessen/` |
| Passwort setzen (Einladung, Zurücksetzen) | `/passwort-setzen/<token>/`, der Link kommt per Mail |
| Passwort ändern | `/konto/passwort/` |
| Übersicht | `/`; Mitarbeiter werden nach `/meine-geraete/` weitergeleitet |
| Geräte | `/geraete/`, Filter als Parameter (unten) |
| Export jeder Liste | dieselbe Adresse mit zusätzlich `format=xlsx` oder `format=csv` (F-103) |
| Gerät erfassen | `/geraete/neu/` |
| Gerätedetail | `/geraete/<Inventarnummer>/` |
| QR-Ziel | `/g/<Inventarnummer>`: Admin und Leser werden auf das Gerätedetail weitergeleitet, Mitarbeiter sehen dort direkt die Kurzansicht (F-113) |
| Arbeitsplätze | `/arbeitsplaetze/` (Raumplan), `/arbeitsplaetze/liste/`, `/arbeitsplaetze/<Kennung>/` |
| Raumplan bearbeiten | `/arbeitsplaetze/plan/<id>/bearbeiten/` |
| Verleih | `/verleih/` |
| Personen | `/personen/`, `/personen/<id>/`, Offboarding `/personen/<id>/offboarding/` |
| Import | `/import/` |
| Etiketten | `/etiketten/` |
| Einstellungen | `/einstellungen/` |
| Meine Geräte | `/meine-geraete/` mit den Abschnitten eigene Geräte, eigene Protokolle und „Meine Leihen“ (F-110, F-111); Leihgerät anfragen `/meine-geraete/leihe/neu/` |
| Protokoll | `/protokolle/<Nummer>/`, PDF `/protokolle/<Nummer>/pdf/` |
| Gegenzeichnung | `/signieren/<token>/`, der Link kommt per Mail |
| Kennzahlen (F-105, Kann) | `/api/kennzahlen` mit Kopfzeile `Authorization: Bearer <KENNZAHLEN_TOKEN>`; ohne oder mit falschem Token 401, ohne gesetztes `KENNZAHLEN_TOKEN` 404. Antwort JSON, siehe Abschnitt 4 |

Wer was aufrufen darf (Kapitel 2), mit der erwarteten Antwort; 403 kommt mit der Seite „Keine Berechtigung“:

| Adresse | Admin | Leser | Mitarbeiter |
|---|---|---|---|
| `/` | 200 | 200 | Weiterleitung nach `/meine-geraete/` |
| `/geraete/`, `/geraete/<Nr>/`, Export | 200 | 200, ohne Aktionen | 403, auch für eigene Geräte |
| `/geraete/neu/`, `/import/`, `/etiketten/`, `/einstellungen/`, `/arbeitsplaetze/plan/<id>/bearbeiten/` | 200 | 403 | 403 |
| `/g/<Nr>` | Weiterleitung auf das Gerätedetail | Weiterleitung auf das Gerätedetail | 200, Kurzansicht |
| `/arbeitsplaetze/…`, `/personen/…` | 200 | 200, ohne Aktionen | 403 |
| `/verleih/` | 200 | 403 | 403 |
| `/meine-geraete/`, `/meine-geraete/leihe/neu/` | 200, wenn das Konto eine Person hat | 200, wenn das Konto eine Person hat | 200 |
| `/protokolle/<Nr>/`, `/protokolle/<Nr>/pdf/` | 200 | 200 | 200 für eigene Protokolle, sonst 403 |

`nav-meine-geraete` steht bei jeder Rolle, deren Konto eine Person hat. Alle Konten aus Abschnitt 2 haben eine.

Filter der Geräteliste, kombinierbar:

| Parameter | Werte |
|---|---|
| `status` | `auf-lager`, `in-benutzung`, `verliehen`, `in-reparatur` |
| `archiv` | `1`: nur ausgemusterte Geräte (F-58); ohne den Parameter erscheinen sie nicht |
| `kategorie` | Name der Kategorie, z. B. `Notebook` |
| `ort` | Kennung, z. B. `WMC-WP-01`, `LAGER-EG`, `STUDIO-TECHNIK` |
| `person` | ID der Person |
| `unvollstaendig` | `1`: Arbeitsliste „Daten unvollständig“ (F-88) |
| `q` | Suchtext wie in der globalen Suche (F-44) |

Nummern:

- Inventarnummern `WMC-00001`, fortlaufend (O-03).
- Protokollnummern `UP-JJJJ-NNNN`, fortlaufend je Jahr, z. B. `UP-2026-0001`.
- Leihnummern `L-NNNN`, fortlaufend, z. B. `L-0001`.

## 4 Markierungen für Tests

Bedienelemente, die Tests ansprechen, tragen ein Attribut `data-test`. Weitere Attribute stehen dabei. Formularfelder werden über ihre sichtbare Beschriftung angesprochen, nicht über `data-test`. Die Beschriftungen von Feldern und Schaltflächen sind die aus dem Prototyp (im Quelltext jeweils das `<label>` bzw. der Text der Schaltfläche) und gelten wörtlich.

| Bereich | `data-test` | Zusatz |
|---|---|---|
| Rahmen | `hauptnavigation`, darin `nav-uebersicht`, `nav-geraete`, `nav-arbeitsplaetze`, `nav-verleih`, `nav-personen`, `nav-import`, `nav-etiketten`, `nav-einstellungen`, `nav-meine-geraete`; `suche`, `suchtreffer`, `abmelden` | Einträge, die eine Rolle nicht sehen darf, fehlen im HTML |
| Rückmeldungen | `meldung` (Erfolg), `fehler` (Fehler im Formular oder Vorgang), `keine-berechtigung` | |
| Listen | `liste`, je Zeile `zeile`; `anzahl`; `export-xlsx`, `export-csv`; `auswahl` (Kästchen je Zeile), `etiketten-drucken` | Zeile mit `data-id` = Inventarnummer, Kennung, Personen-ID, Leih- oder Protokollnummer; in der Leihliste zusätzlich `data-stand` (Abschnitt 5) |
| Gerätedetail | `inventarnummer`, `status`, `zustand`, `verbleib`, `historie`, darin `vorgang`; `qr` | `status` mit `data-wert` (Abschnitt 5); `vorgang` mit `data-typ`, z. B. `Aufnahme`, `Ausgabe`, `Import`; `qr` mit `data-qr` = Inhalt des QR-Codes (F-70) |
| Kurzansicht | `kurzansicht`, darin `kategorie`, `modell`, `inventarnummer`, `zuordnung` | `zuordnung` mit Text „Ihnen zugeordnet“ oder „nicht Ihnen zugeordnet“ (F-113) |
| Aktionen | `aktion-korrigieren` (neue Fassung eines gesperrten Protokolls, F-135), `aktion-bearbeiten`, `aktion-ausgabe`, `aktion-rueckgabe`, `aktion-verleih`, `aktion-umzug`, `aktion-reparatur`, `aktion-reparatur-abschliessen`, `aktion-ausmustern`, `aktion-etikett`, `aktion-loeschen`, `aktion-vorlage`, `aktion-im-raumplan`, `aktion-notiz` | Aktionen ohne Recht fehlen im HTML |
| Dialoge | `dialog` | `data-name`: `ausgabe`, `verleih`, `rueckgabe`, `umzug`, `reparatur`, `reparatur-abschliessen`, `ausmustern`, `bearbeiten`, `anhang`, `notiz`, `scan-hochladen`, `genehmigen`, `ablehnen`, `verlaengern`, `austritt`, `gegenzeichnen`; Schaltflächen darin `speichern`, `bestaetigen`, `abbrechen`, `signieren`, `code-senden` |
| Übersicht | `kennzahl`, darin `ist`, `gesamt`, `delta`; `arbeitsliste`, darin `zeile`; `inventarwert` | siehe unten |
| Arbeitsplätze | `raumplan`, `platz`, `raumort`, `platz-popup`, `ohne-position`; `bedarfsliste`, darin `zeile` | `platz` mit `data-id` = Kennung, `data-soll-ist` = `vollstaendig`, `unvollstaendig` oder `mehr` und `data-x`, `data-y` = Position in % mit Punkt als Dezimalzeichen (`50.1`); `raumort` mit `data-id` = Kennung; `ohne-position` listet Plätze ohne Position (F-67); Zeile der Bedarfsliste mit `data-id` = Kategorie, darin `fehlt` und `lager` (F-63) |
| Erstinventur | `inventur-fortschritt`, darin `ist`, `gesamt` | steht über der Geräteliste, sobald nach `ort` gefiltert wird: geprüfte / alle Geräte dieses Orts (F-89) |
| Import | `import-schritt`, `import-vorschau`, darin `zeile`; `vorschau-csv` | `import-schritt` mit `data-nr`; Zeile mit `data-zeile` = Excel-Zeile und `data-ergebnis` = `neu`, `ergaenzt`, `konflikt` oder `uebersprungen` |
| Checklisten | `checkpunkt`, je Punkt eine Zeile | `data-liste` = `zugaenge` oder `offboarding`, `data-nr` = Position ab 1; darin je Option ein Optionsfeld mit `value` = `ausgegeben`, `nicht-zutreffend`, `erledigt` oder `in-klaerung`, beschriftet über die Spaltenköpfe (Texte in Abschnitt 5), dazu das Feld „Bemerkung“ |
| Hinweise | `hinweis` | im Gerätedetail und in der Importvorschau; `data-art` = `geraetename-doppelt`, `seriennummer-doppelt`, `altbestand`, `ungeprueft` |
| Protokolle | `protokoll` | `data-id` = Protokollnummer, `data-stand` (Abschnitt 5) |
| Meine Geräte | `meine-geraete`, `meine-protokolle`, `meine-leihen`, je darin `zeile` | wie Listen |

Übersicht im Einzelnen:

- `kennzahl` hat `data-id`. Mit `gesamt` (IST/Gesamt, F-100): `in-benutzung`, `arbeitsplaetze-vollstaendig`, `verliehen`, `geprueft`. Nur mit `ist`: `ueberfaellig`, `anfragen-offen`, `garantie-30-tage`, `unterschriften-offen`. `delta` fehlt, solange es keinen Zählerstand vom Vortag gibt.
- `arbeitsliste` hat `data-id`: `ueberfaellig`, `anfragen`, `arbeitsplaetze-unvollstaendig`, `garantie`, `unterschriften-offen`, `daten-unvollstaendig`, `offene-punkte` (Prüfpunkte „in Klärung“, F-133), `austritte` (Austritte mit offenen Geräten). Eine leere Arbeitsliste steht mit ihrem Hinweistext da, ohne `zeile`.
- `inventarwert` ist die Summe nach F-104, nur für Admin und Leser.
- `/api/kennzahlen` liefert dieselben Werte als JSON: `{"stand": "2026-11-02T09:30", "kennzahlen": {"in-benutzung": {"ist": 125, "gesamt": 142, "delta": 2}, "ueberfaellig": {"ist": 1, "delta": null}, …}}`. Schlüssel sind die `data-id` der Kennzahlen; `gesamt` nur, wo die Übersicht es zeigt; `delta` ist eine Zahl oder `null`.

## 5 Feste Texte

Diese Texte stehen so in der Oberfläche, weil Anforderungen und Tests sie wörtlich verwenden.

Gerätestatus (Kapitel 4), Anzeigetext und `data-wert`:

| Status | Anzeigetext | `data-wert` |
|---|---|---|
| Auf Lager | „Auf Lager“ | `auf-lager` |
| In Benutzung | „In Benutzung“ | `in-benutzung` |
| Verliehen | „Verliehen“ | `verliehen` |
| In Reparatur | „In Reparatur“ | `in-reparatur` |
| Ausgemustert | „Ausgemustert“ | `ausgemustert` |

Zusätze neben dem Status: „reserviert“ (genehmigte Leihe, Kapitel 4) und „Altbestand ohne Protokoll“ (F-85).

Leihe (Kapitel 3.2), Anzeigetext und `data-stand`:

| Status | Anzeigetext | `data-stand` |
|---|---|---|
| angefragt | „angefragt“ | `angefragt` |
| genehmigt | „genehmigt“ | `genehmigt` |
| abgelehnt | „abgelehnt“ | `abgelehnt` |
| ausgegeben | „ausgegeben“, nach Ablauf der Frist „überfällig“ | `ausgegeben` bzw. `ueberfaellig` |
| zurückgegeben | „zurückgegeben“ | `zurueckgegeben` |
| zurückgezogen | „zurückgezogen“ | `zurueckgezogen` |

Protokoll (Kapitel 3.2), Anzeigetext und `data-stand`. Die drei offenen Stände zeigen „Unterschrift offen“ und dahinter, was fehlt (F-22, F-141):

| Status | Anzeigetext | `data-stand` |
|---|---|---|
| Entwurf | „Entwurf“ | `entwurf` |
| wartet auf Signatur Bearbeiter | „Unterschrift offen: Bearbeiter“ | `bearbeiter-offen` |
| wartet auf Gegenzeichnung | „Unterschrift offen: Gegenzeichnung“ | `gegenzeichnung-offen` |
| Papierweg, Scan fehlt | „Unterschrift offen: Scan fehlt“ | `scan-offen` |
| abgeschlossen (versiegelt oder Papier mit Scan) | „abgeschlossen“ | `abgeschlossen` |

Weitere:

- Delta (F-101): „+2“, „−1“ mit dem Minuszeichen U+2212, „±0“.
- Beträge: „1.234,56 €“, Tausenderpunkt, zwei Nachkommastellen, Euro-Zeichen nach Leerzeichen.
- Soll-Ist: „vollständig“, „unvollständig“ mit Liste nach dem Muster „fehlt: 1 × Headset“, „mehr als Soll“.
- Import: „neu“, „ergänzt“, „Konflikt“, „übersprungen“.
- Prüfpunkte: „erledigt“, „in Klärung“, „nicht zutreffend“; Zugänge: „ausgegeben“, „nicht zutreffend“. Die Texte der Punkte stehen in `docs/vorlagen/FRM-001.md` und `FRM-002.md`.
- Schaltflächen mit Text aus den Anforderungen: „Alle Geräte zurücknehmen“ (F-52), „Fehlendes vom Lager ausgeben“ und „Etiketten für den Platz“ (F-66), „Speichern und Etikett drucken“ beim Erfassen (F-12), „Testmail senden“ (F-90); die Schaltfläche der Erstinventur beginnt mit „Geprüft“ (F-89).
- Hinweis doppelter Gerätename: „Gerätename auch bei WMC-00012“ mit der Inventarnummer des anderen Geräts.
- Arbeitsliste: „Daten unvollständig“ (F-88).
- Keine Berechtigung: „Keine Berechtigung“.

Datum immer TT.MM.JJJJ, Beträge mit Euro-Zeichen und deutschem Dezimalkomma.
