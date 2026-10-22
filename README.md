# WMC Inventar

Internes Web-Tool der WAMOCON-IT für die Verwaltung von Bürohardware: Bestand, Ausgabe, Verleih, Rückgabe, Ausmusterung, Soll-Ausstattung je Arbeitsplatz mit Raumplan und digital signierte Übergabeprotokolle nach WMC-IT-FRM-001 und -002.

**Stand:** Auftrag vergeben. Gregor (KI-Mitarbeiter Entwicklung) baut Version 1 auf `gregor/inventar`, Theo (KI-Mitarbeiter Test) schreibt parallel die Robot-Framework-Tests auf `theo/inventar`. Jira: Epic WMCNL-2755.

| Pfad | Inhalt |
|---|---|
| `AGENTS.md` | Regeln für alle, die im Repo arbeiten |
| `docs/anforderungen.md` | Anforderungen mit IDs, maßgeblich |
| `docs/AUFTRAG.md` | Auftrag an Gregor |
| `docs/TESTAUFTRAG.md` | Auftrag an Theo |
| `docs/TESTSCHNITTSTELLE.md` | Start, Beispieldaten, Adressen und Markierungen, auf die sich Anwendung und Tests verlassen |
| `docs/UEBERGABE.md`, `docs/TESTBERICHT.md` | Vorlagen für Übergabe und Testbericht |
| `docs/design/` | Bilder aus dem Mockup |
| `docs/vorlagen/` | Text der Protokollvorlagen, anonymisierte Bestandsliste für Importtests, Grundriss Eschborn |
| `mockup/wmc-inventar-prototyp.html` | klickbarer Prototyp, im Browser öffnen |
| `static/` | htmx und Schrift Archivo, lokal |
| `requirements.txt`, `requirements-test.txt` | Python-Pakete für Anwendung und Tests |

Die echte Bestandsliste, Protokolle mit Personendaten, das Firmenzertifikat für das Siegel und alle Zugangsdaten liegen nie in diesem Repo.

Lizenzen der mitgelieferten Dateien: htmx unter Zero-Clause BSD (`static/vendor/LICENSE-htmx.txt`), Archivo unter SIL Open Font License 1.1 (`static/fonts/OFL.txt`).
