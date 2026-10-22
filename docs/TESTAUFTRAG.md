# Testauftrag: WMC Inventar, Version 1

| | |
|---|---|
| Jira | Epic WMCNL-2755; Rolle Tester: WMCNL-2788 |
| Auftraggeber | Erwin Moretz, IT |
| Ausführung | Theo, KI-Mitarbeiter Test |
| Entwicklung | Gregor, KI-Mitarbeiter, auf `gregor/inventar` (`docs/AUFTRAG.md`) |
| Zweig | `theo/inventar` |

## Ziel

Gregor baut Version 1 des WMC Inventars. Du schreibst parallel dazu eine Testsuite mit Robot Framework, die jedes Abnahmekriterium aus `docs/anforderungen.md` prüft, und führst sie gegen jeden Stand aus, den Gregor in den Git-Bus pusht. Fehler meldest du Gregor, bevor ein Mensch abnimmt.

## Grundlage

| Pfad | Wofür |
|---|---|
| `docs/anforderungen.md` | Kapitel 5: 93 Anforderungen mit Abnahmekriterium, Kapitel 7: N-01 bis N-11, Kapitel 4: Statusmodell |
| `docs/TESTSCHNITTSTELLE.md` | Start, Befehle, Beispieldaten mit Testkonten, Adressen, `data-test`-Markierungen, feste Texte |
| `mockup/wmc-inventar-prototyp.html` | Abläufe, Beschriftungen und Texte, wie sie aussehen sollen; seine Daten sind Anschauung |
| `docs/vorlagen/` | Testdatei für den Import mit festen Erwartungswerten (`README.md`), Grundriss, Text der Protokolle (`FRM-001.md`, `FRM-002.md`) |
| `docs/UEBERGABE.md` | Spalte M: in welchem Meilenstein Gregor eine Anforderung fertig baut; dort trägt er auch ein, welche Meilensteine gepusht sind |
| `requirements-test.txt` | Robot Framework, Browser Library, RequestsLibrary, pypdf, zxing-cpp; dazu alles aus `requirements.txt`, also auch pyHanko zum Prüfen der Siegel und pypdfium2 zum Rendern von PDF-Seiten |

## Aufbau

```
tests/robot/
  ressourcen/gemeinsam.resource   Start, Anmeldung je Rolle, Daten zurücksetzen, Mails lesen
  bibliotheken/*.py              eigene Schlüsselwörter, z. B. Mailablage, PDF-Text, Siegelprüfung
  01_anmeldung.robot             Kapitel 5.1
  02_aufnahme.robot              Kapitel 5.2
  …                              je Kapitel 5.x eine Suite, bis 15_protokolle.robot
  20_nichtfunktional.robot       N-01 bis N-11, soweit automatisierbar
  ergebnisse/                    report.html, log.html, output.xml des letzten Laufs
docs/TESTBERICHT.md              dein Bericht
```

Jeder Testfall:

- Name beginnt mit der ID: `F-21 Ausgabe an Person erzeugt Protokoll nach FRM-001`.
- `[Tags]` mit ID, Meilenstein und Priorität, z. B. `F-21  M3  prio-M`.
- `[Documentation]` zitiert das Abnahmekriterium und sagt in einem Satz, was der Test davon prüft.
- Ist unabhängig von anderen Testfällen: Jede Suite setzt die Datenbank zurück (`beispieldaten --neu`) und legt die Geräte an, die sie braucht.

Oberfläche prüfst du mit der Browser Library, HTTP-Verhalten (Status 403, Weiterleitungen, Export, Kopfzeilen) mit der RequestsLibrary. Mails liest du aus `MAIL_ABLAGE` (Format in Abschnitt 1.3 der Testschnittstelle), Einmalcodes und Links holst du dir dort. PDFs prüfst du mit pypdf (Text, Seitenzahl) und pyHanko (Siegel gültig gegen `var/testsiegel.crt`, nach Änderung ungültig). QR-Codes auf Etiketten liest du, indem du die PDF-Seite mit pypdfium2 als Bild renderst und mit zxing-cpp dekodierst. Erinnerungen prüfst du mit `tageslauf --stichtag`, Fristen wie Sperre, Einmalcode und Linkablauf über die Uhr `var/jetzt.txt` (Abschnitt 1.2).

## Vorgehen

1. Lies die Grundlage vollständig. Lege den Zweig an: `git switch -c theo/inventar`.
2. Schreib die Suiten in der Reihenfolge der Meilensteine M1 bis M7. Du wartest dafür nicht auf Gregor: Die Tests entstehen aus den Abnahmekriterien und der Testschnittstelle und dürfen rot sein, solange es die Funktion noch nicht gibt.
3. Sobald Gregor einen Stand pusht (`git fetch origin` zeigt `origin/gregor/inventar` neu), führst du die Suite dagegen aus. Gregors Stand holst du dir als zweiten Arbeitsbaum neben deinen Klon, nicht nach `/tmp`:
   ```
   cd ~/WAMOCON/wmc-inventar-tests && git fetch origin
   git worktree add --detach ../wmc-inventar-app origin/gregor/inventar      # beim ersten Mal
   git -C ../wmc-inventar-app checkout -q --detach origin/gregor/inventar   # danach
   cd ../wmc-inventar-app
   PY=../wmc-inventar-tests/.venv/bin/python
   export INVENTAR_DEBUG=1 MAIL_ABLAGE=var/mails
   rm -rf var
   $PY manage.py migrate && $PY manage.py testsiegel && $PY manage.py beispieldaten
   $PY manage.py runserver 127.0.0.1:8000 --noreload > var/server.log 2>&1 &
   echo $! > var/server.pid
   cd ../wmc-inventar-tests
   .venv/bin/robot --outputdir tests/robot/ergebnisse --variable BASIS_URL:http://127.0.0.1:8000 --variable APP_PFAD:$HOME/WAMOCON/wmc-inventar-app tests/robot
   kill "$(cat ../wmc-inventar-app/var/server.pid)"
   ```
   Befehle der Anwendung (`beispieldaten --neu`, `tageslauf`) rufst du aus der Suite mit Arbeitsverzeichnis `APP_PFAD` und demselben Python auf. Gregors Code änderst du dabei nicht.
4. Trag das Ergebnis in `docs/TESTBERICHT.md` ein, mit Gregors Commit, gegen den du getestet hast.
5. Für jeden roten Test, der eine fertige Funktion betrifft: Meldung an Gregor über Hermes. Fertig ist eine Funktion, wenn Gregor den letzten Meilenstein aus Spalte M ihrer ID gepusht hat; rote Tests zu späteren Meilensteinen stehen nur im Bericht. Inhalt: ID, Schritte zum Nachstellen, erwartet, tatsächlich, Name des Testfalls. Wie er den Fehler behebt, schreibst du nicht vor.
6. Committe Suite, Ergebnisse und Bericht auf `theo/inventar` und pushe in den Git-Bus.

## Regeln

- Du änderst nur `tests/robot/` und `docs/TESTBERICHT.md`. Produktcode, Anforderungen und Testschnittstelle bleiben, wie sie sind.
- Ein Test prüft das Abnahmekriterium, nicht Gregors Umsetzung. Steht etwas nicht in den Anforderungen oder der Testschnittstelle, testest du es nicht als Pflicht.
- Wenn die Testschnittstelle nicht reicht (eine Markierung fehlt, eine Adresse ist unklar), frag Erwin über Hermes mit ID, Zitat und Vorschlag. Arbeite bis zur Antwort mit dem Vorschlag weiter.
- Was sich nicht automatisch prüfen lässt (z. B. Farben nach CI, Lesbarkeit im PDF-Reader), führst du im Bericht als manuelle Prüfung mit Schritten auf.
- Fehlt ein Werkzeug (Browser, Node.js, Erlaubnis zum Serverstart), umgehe das nicht. Schreib es in den Bericht und gib Bescheid.
- Tests laufen ohne Internet und nur gegen `127.0.0.1`.

## Fertig, wenn

- [ ] Jede ID aus Kapitel 5 mit Abnahmekriterium hat mindestens einen Testfall mit ihrer ID als Tag.
- [ ] N-01 bis N-11 sind getestet oder als manuelle Prüfung beschrieben.
- [ ] Die Suite läuft gegen Gregors letzten Stand durch; `report.html`, `log.html` und `output.xml` liegen in `tests/robot/ergebnisse/`.
- [ ] `docs/TESTBERICHT.md` ist ausgefüllt, jeder Fehler ist Gregor gemeldet.
- [ ] Alles ist auf `theo/inventar` im Git-Bus.
- [ ] Meldung an Erwin: „WMCNL-2755 Tests, Zweig theo/inventar, letzter Commit HASH, X von Y grün gegen gregor/inventar HASH“.
