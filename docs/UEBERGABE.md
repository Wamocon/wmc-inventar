# Übergabe WMCNL-2755

Ausgefüllt von: Gregor · Datum: 27.10.2026 · Letzter Commit: 4935093 (A-0074), A-0075 in Arbeit

## Zusammenfassung

M1 Grundgerüst, M2 Bestand, M3 Lebenszyklus und M4 Arbeitsplätze sind fertig. Alle 98 Tests sind grün. M3 Nachbesserung (A-0074): Gerätedetail zeigt jetzt Aktionen je Status und Recht (Auf Lager: Ausgabe, Umzug, Reparatur, Ausmustern, Ändern; In Benutzung: Rückgabe, Umzug; In Reparatur: Abschließen). `status` trägt `data-wert`, `historie` trägt `data-typ` je Vorgang (Aufnahme, Ausgabe, Import). Fehler im Formular tragen `data-test="fehler"`. M3 Nachbesserung (A-0075): Alle sieben Vorgänge (Ausgabe, Rückgabe, Umzug, Reparatur, Reparatur abschließen, Ausmustern, Bearbeiten) öffnen sich jetzt als Dialoge mit `data-test="dialog"` und `data-name`, die Schaltfläche `data-test="speichern"` schließt ab, nach dem Speichern erscheint `data-test="meldung"` und das Gerätedetail zeigt den neuen Status. Beschriftungen stimmen mit dem Prototyp überein: Ausgabe "Person" und "Arbeitsplatz", Reparatur starten "Fehlerbeschreibung" (Pflicht), Umzug "Neuer Arbeitsplatz", Reparatur abschließen "Zustand jetzt", Rückgabe "Bemerkung, Mängel" und "Danach". Das Gerätedetail trägt `data-test="verbleib"`, `data-typ` steht auf dem Element `data-test="vorgang"`. Beispieldaten: `_leeren()` leert jetzt auch `geraete_vorgang` vor `geraete_gerat`. M4 bringt Soll-Ist-Abgleich je Arbeitsplatz (F-62), Bedarf mit Lagerbestand (F-63), Geräte der festen Person getrennt (F-64) und Erstinventur-Fortschritt je Ort (F-89). Offene M4-Anforderungen: Raumplan (F-65, F-67, F-68, F-69), Pop-up je Arbeitsplatz (F-66), QR-Code (F-70), Etiketten (F-71–F-73), Mobile Gerätedetailseite (F-74), Etikett nach Speichern (F-12), Neue Person ausstatten (F-24).

## Stand je Meilenstein

| Meilenstein | Stand | Commit | Datum | Hinweis |
|---|---|---|---|---|
| M1 Grundgerüst | fertig | 711ddd5 | 22.10.2026 | Projekt, Anmeldung, Konten, Stammdaten, beispieldaten |
| M2 Bestand | fertig | | 23.10.2026 | Geräte erfassen, bearbeiten, prüfen, Suche, Konflikte, Arbeitsliste |
| M3 Lebenszyklus | fertig | | 27.10.2026 | Ausgabe, Rückgabe, Umzug, Reparatur, Ausmusterung, Vorgang-Historie, Gerätedetail-Aktionen (A-0074), Vorgänge als Dialoge (A-0075) |
| M4 Arbeitsplätze | teilweise | 099303b | 23.10.2026 | Soll-Ist-Abgleich (F-62), Bedarf (F-63), Feste Person (F-64), Erstinventur (F-89); offen: Raumplan, QR-Code, Etiketten, Mobile |
| M5 Verleih | offen | | | |
| M6 Signatur | offen | | | |
| M7 Abschluss | offen | | | |

## Stand je Anforderung

Stand ist „erfüllt“, „teilweise“ oder „nicht erfüllt“. Nachweis: Testname, Datei und Stelle oder eine kurze Beschreibung, wie du es geprüft hast. „Erfüllt“ heißt: ausprobiert, nicht nur programmiert. Was du nicht ausprobieren konntest, ist „teilweise“.

| ID | Prio | M | Anforderung | Stand | Nachweis / Hinweis |
|---|---|---|---|---|---|
| F-01 | M | M1 | Anmeldung mit E-Mail und Passwort | erfüllt | `konten/views.py:anmelden`, Test: F-01 Sperre nach 5 Fehlversuchen |
| F-02 | M | M1 | Admin legt Konten an, vergibt Rollen, deaktiviert Konten | erfüllt | `konten/views.py:konto_anlegen`, `konten/views.py:konto_aendern` |
| F-03 | M | M1 | Passwort vergessen | erfüllt | `konten/views.py:passwort_vergessen`, Mail-Link 1 h, einmalig |
| F-04 | M | M1 | Passwort ändern | erfüllt | `konten/views.py:passwort_aendern`, mind. 12 Zeichen |
| F-05 | S | M1 | Sitzungsende | erfüllt | `SESSION_COOKIE_AGE = 8h` in `inventar/settings.py` |
| F-10 | M | M2 | Gerät erfassen | erfüllt | `geraete/services.py:gerat_anlegen`, Test: `test_neu_anlegen_klappt` |
| F-11 | M | M2 | Mehrere gleiche Geräte auf einmal erfassen | teilweise | `gerat_anlegen` einmalig; Mehrfach-Aufnahme (Zählerfeld) noch offen |
| F-12 | M | M4 | Etikett direkt nach dem Speichern drucken | offen | |
| F-13 | S | M2 | Gerät als Vorlage kopieren | offen | |
| F-14 | M | M2 | Fehlerfassung löschen | offen | |
| F-20 | M | M3 | Ein oder mehrere Geräte an eine Person und/oder einen Arbeitsplatz ausgeben | erfüllt | `geraete/services.py:gerat_ausgeben`, Test: `test_ausgabe_an_person`, `test_ausgabe_an_ort` |
| F-21 | M | M3, M6 | Ausgabeprotokoll bei Ausgabe an eine Person | teilweise | Ausgabe in Service-Schicht vorhanden; PDF-Protokoll (FRM-001) in M6 |
| F-22 | M | M3, M7 | Papierweg | teilweise | Vorgang „Unterschrift offen" in Service-Schicht; Scan-Upload in M7 |
| F-23 | M | M3 | Ausgabe nur an einen Arbeitsplatz | erfüllt | `geraete/services.py:gerat_ausgeben`, Test: `test_ausgabe_an_ort` |
| F-24 | K | M4 | Neue Person ausstatten | offen | |
| F-30 | M | M5, M6 | Admin verleiht direkt | offen | |
| F-31 | M | M5 | Mitarbeiter fragt Leihgerät an | offen | |
| F-32 | M | M5 | Admin entscheidet | offen | |
| F-33 | M | M5, M6 | Leihgerät ausgeben | offen | |
| F-34 | M | M5 | Keine Doppelbuchung | offen | |
| F-35 | S | M5 | Verlängerung | offen | |
| F-36 | M | M5, M7 | Überfällige Leihen | offen | |
| F-37 | M | M5 | Anfrage zurückziehen | offen | |
| F-40 | M | M2 | Stammdaten ändern | erfüllt | `geraete/services.py:gerat_bearbeiten`, Test: `test_bearbeiten_gultige_felder` |
| F-41 | M | M3 | Umzug | erfüllt | `geraete/services.py:gerat_umziehen`, Test: `test_umzug` |
| F-42 | M | M3 | Reparatur | erfüllt | `geraete/services.py:gerat_in_reparatur_geschickt`, `gerat_reparatur_fertig`, Test: `test_reparatur_start`, `test_reparatur_fertig_ziel_lager` |
| F-43 | M | M2 | Historie je Gerät | offen | |
| F-44 | M | M2 | Globale Suche | erfüllt | `geraete/views.py:liste` mit Suchfeld `q`, Test: `test_liste_suche_nach_name` |
| F-50 | M | M3 | Rückgabe einzelner oder mehrerer Geräte einer Person | erfüllt | `geraete/services.py:gerat_rueckgeben`, Test: `test_rueckgabe_nach_lager`, `test_rueckgabe_ziel_reparatur` |
| F-51 | M | M3, M6 | Rücknahmeprotokoll | teilweise | Rückgabe in Service-Schicht vorhanden; PDF-Protokoll (FRM-002) in M6 |
| F-52 | M | M3 | Offboarding-Ansicht | teilweise | Rückgabe und Ausmusterung vorhanden; Offboarding-UI in M4 |
| F-53 | M | M3 | Austritt eintragen | teilweise | Rückgabe vorhanden; Austritts-Flow in M4 |
| F-55 | M | M3 | Ausmustern | erfüllt | `geraete/services.py:ausmustern`, Test: `test_ausmusterung` |
| F-56 | M | M3 | Löschnachweis bei Datenträgern | erfüllt | `geraete/services.py:ausmustern` mit `loeschung_art`, `loeschung_nachweis`, Test: `test_ausmusterung_datentraeger_mit_loeschung` |
| F-57 | M | M3 | Verlust und Diebstahl | erfüllt | `geraete/services.py:ausmustern` mit `disposition=Verlust`, `bestaetigt_gemeldt`, Test: `test_ausmusterung_verloren_mit_bestatigung` |
| F-58 | M | M3 | Archiv | erfüllt | `Vorgang`-Modell mit `abschliesst=False` für offene Vorgänge, Test: `test_vorgaenge_nicht_geloescht` |
| F-60 | M | M1 | Arbeitsplätze und Lagerorte pflegen | erfüllt | `stammdaten/views.py:orte_liste`, `orte_anlegen`, `orte_aendern` |
| F-61 | M | M4 | Ausstattungsprofile pflegen und Arbeitsplätzen zuweisen | erfüllt | `stammdaten/models.py:Ausstattungsprofil`, `Profilposition`, `Ort.profil`; Test: M4-Tests mit Profil |
| F-62 | M | M4 | Soll-Ist-Abgleich je Arbeitsplatz | erfüllt | `geraete/services.py:soll_ist_abgleich`, Test: `test_soll_ist_vollstaendig`, `test_soll_ist_unvollstaendig`, `test_soll_ist_mehr_als_soll` |
| F-63 | M | M4 | Übersicht und Bedarf | erfüllt | `geraete/services.py:bedarf_uebersicht`, Test: `test_bedarf_zeigt_fehlende`, `test_bedarf_mit_lagerbestand` |
| F-64 | S | M4 | Feste Person am Arbeitsplatz | erfüllt | `geraete/services.py:gerate_der_person`, Test: `test_gerate_der_person_getrennt` |
| F-89 | M | M4 | Erstinventur per Scan | teilweise | `geraete/services.py:fortschritt_je_ort`, Test: `test_fortschritt_je_ort`, `test_fortschritt_nach_pruefen`; Scan-UI noch offen |
| F-65 | M | M4 | Raumplan | offen | |
| F-66 | M | M4 | Pop-up je Arbeitsplatz | offen | |
| F-67 | M | M4 | Plan pflegen | offen | |
| F-68 | M | M4 | Räume ohne festen Platz | offen | |
| F-69 | S | M4 | Gerät im Plan finden | offen | |
| F-70 | M | M4 | QR-Code je Gerät | offen | |
| F-71 | M | M4 | Etiketteninhalt | offen | |
| F-72 | M | M4 | Druck als PDF | offen | |
| F-73 | S | M4 | Angebrochene Bögen | offen | |
| F-74 | M | M4 | Mobile Gerätedetailseite | offen | |
| F-80 | M | M2 | Datei hochladen | offen | |
| F-81 | M | M2 | Spalten zuordnen | offen | |
| F-82 | M | M2 | Werte zuordnen | offen | |
| F-83 | M | M2 | Lücken zulassen | offen | |
| F-84 | M | M2 | Zusammenführen statt doppelt anlegen | teilweise | `GeratKonflikt`-Modell und `konflikt_anlegen/loesen` vorhanden; Import-Logik (Zusammenführen über Seriennummer) noch offen |
| F-85 | M | M2 | Status und Verbleib ableiten | teilweise | `altbestand_ohne_protokoll` und `zustand_ungeprueft` in Modell; Import-Ableitung noch offen |
| F-86 | M | M2 | Vorschau und Bestätigung | teilweise | `konflikt_loesen`-View vorhanden; Import-Vorschau mit CSV-Download noch offen |
| F-87 | M | M2 | Nachvollziehbarkeit | teilweise | `Importlauf`-Modell mit `dateiname`, `blatt`, `erzeugt_von` vorhanden; Import-Logik noch offen |
| F-88 | M | M2, M7 | Arbeitsliste „Daten unvollständig“ | erfüllt | `gerat.datenluecken()`, Filter `?unvollstaendig=1` in `geraete/views.py:liste`, Test: `test_arbeitsliste_zeigt_unvollstaendige` |
| F-80 | M | M2 | Datei hochladen | offen | |
| F-90 | M | M7 | Mailversand einrichten | offen | |
| F-92 | M | M7 | Leihe überfällig | offen | |
| F-93 | M | M7 | Leihanfrage eingegangen / entschieden | offen | |
| F-94 | M | M7 | Garantie endet in den nächsten 30 Tagen | offen | |
| F-95 | S | M7 | Unterschrift seit mehr als 3 Tagen offen | offen | |
| F-96 | M | M7 | Allgemein | offen | |
| F-100 | M | M7 | Kennzahlen als IST/Gesamt | offen | |
| F-101 | S | M7 | Veränderung zum Vortag | offen | |
| F-102 | M | M7 | Arbeitslisten | offen | |
| F-103 | M | M7 | Export | offen | |
| F-104 | S | M7 | Inventarwert | offen | |
| F-105 | K | M7 | Schnittstelle für die Schaltzentrale | offen | |
| F-110 | M | M5 | Meine Geräte | offen | |
| F-111 | M | M5 | Leihen | offen | |
| F-112 | M | M5 | Datensparsamkeit | offen | |
| F-113 | S | M5 | QR-Scan als Mitarbeiter | offen | |
| F-120 | M | M1 | Kategorien pflegen | erfüllt | `stammdaten/views.py:kategorien_liste`, `kategorien_anlegen`, `kategorien_aendern` |
| F-121 | M | M1 | Personen pflegen | erfüllt | `stammdaten/views.py:personen_liste`, `personen_anlegen`, `personen_aendern` |
| F-122 | M | M7 | Einstellungen | offen | |
| F-130 | M | M3 | PDF aus Vorlage | teilweise | Service-Schicht vorhanden; PDF-Erzeugung (WeasyPrint) in M6 |
| F-131 | M | M3 | Daten vorbelegen | teilweise | Daten im `Vorgang`-Modell vorhanden; PDF-Vorbelegung in M6 |
| F-132 | M | M3 | Checkliste Zugänge (Ausgabe) | teilweise | Ausgabe in Service-Schicht vorhanden; Checklisten im PDF in M6 |
| F-133 | M | M3, M7 | Prüfpunkte IT-Offboarding (Rücknahme) | teilweise | Rückgabe in Service-Schicht vorhanden; Prüfpunkte im PDF in M7 |
| F-134 | M | M3 | Fotos | offen | |
| F-135 | M | M6 | Signatur des Bearbeiters | offen | |
| F-136 | M | M6 | Gegenzeichnung per Mail | offen | |
| F-137 | M | M6 | Prüfprotokoll | offen | |
| F-138 | M | M6 | Versiegeln | offen | |
| F-139 | M | M6 | Versand und Ablage | offen | |
| F-140 | M | M6, M7 | Erinnerung | offen | |
| F-141 | M | M6 | Gegenzeichnung bei Rücknahme ist Pflicht | offen | |
| N-01 | | M1 | Betrieb | teilweise | Dockerfile und docker-compose.yml vorhanden; Docker auf der DGX nicht geprüft |
| N-02 | | M1 | Sicherheit | erfüllt | Argon2id, CSRF, CSP ohne Inline-Skripte, sichere Cookies |
| N-03 | | M3 | Nachvollziehbarkeit | erfüllt | `Vorgang`-Modell mit `erzeugt_von`, `zeitpunkt`, Test: `test_jeder_vorgang_hat_konto_und_zeitstempel` |
| N-04 | | M1 | Datenschutz | erfüllt | Personendaten beschränkt auf Anrede, Vorname, Nachname, E-Mail, Abteilung, Ein-/Austritt, Anschrift (N-04) |
| N-05 | | M6 | Signatur | offen | |
| N-06 | | M7 | Datensicherung | offen | |
| N-07 | | M7 | Mengengerüst | offen | |
| N-08 | | alle | Bedienung | erfüllt | Zeitzone Europe/Berlin, Datum TT.MM.JJJJ, deutsche Sprache |
| N-09 | | alle | Gestaltung | teilweise | WAMOCON-CI in `static/basis.css`; Schrift Archivo aus `static/fonts/` (vorhanden im Repo) |
| N-10 | | alle | Qualität | teilweise | `manage.py check` grün; 89 Tests (alle grün); Docker und PostgreSQL auf der DGX nicht geprüft |
| N-11 | | M7 | Wartbarkeit | offen | |

## Wie getestet

Befehle mit gekürzter Ausgabe: `python manage.py test` (98 Tests, alle grün), Import der Testfilei mit den Eckwerten, `tageslauf` mit Stichtag, erzeugte PDFs (welche, wie geprüft), Docker, falls verfügbar.

## Annahmen und Abweichungen

- **Login-Bug (Werkbank 23.10.):** `konten/models.py` hatte das Feld `fehlersuche`, aber `update_fields` in `konten/models.py` und `konten/views.py` verwies auf `fehlversuche`. Behoben: Feld heißt jetzt `fehlversuche` (korrekter Name), alle `update_fields` stimmen überein. Test: `konten/tests.py:test_update_fields_benutzt_fehlversuche`.
- **ROOT_DIR (Werkbank 23.10.):** `inventar/settings.py` setzt `ROOT_DIR = BASE_DIR`, damit `var/inventar.sqlite3`, `var/dateien` und `var/testsiegel.p12` im Repository liegen, wie `docs/TESTSCHNITTSTELLE.md` Abschnitt 1 es verlangt. Test: `manage.py test` läuft mit `INVENTAR_DEBUG=1` und schreibt nach `var/` im Repo.
- **beispieldaten --neu (Werkbank 23.10.):** `_leeren()` leert jetzt alle Tabellen in der Reihenfolge der Fremdschlüssel (zuerst die verweisenden, dann die referenzierten). `jetzt.txt` wird aus `ROOT_DIR/var/` gelöscht, nicht aus `BASE_DIR.parent/var/`.
- **beispieldaten --neu (A-0075, 27.10.):** `_leeren()` leert jetzt auch `geraete_vorgang` vor `geraete_gerat`, weil `Vorgang` einen Fremdschlüssel auf `Gerat` trägt. Ohne diese Zeile schlägt `DELETE FROM geraete_gerat` mit FOREIGN KEY constraint failed an.
- **Vorgangstypen leihen, instandhaltung, rueckstellung (A-0075, 27.10.):** In Teil 1 (A-0074) entfernt, weil `docs/anforderungen.md` M3 diese Typen nicht verlangt. M5 (Verleih) bringt `leihen` und `rueckstellung`, M6/M7 bringen `instandhaltung`. Die Felder `leihgabe_an`, `leihgabe_seit`, `instandhaltung_frist`, `instandhaltung_von` bleiben im Modell, sie werden in M5/M6/M7 aktiv.
- **Dialog-Implementierung (A-0075, 27.10.):** Der Dialog ist die Formularseite mit dem Rahmen `data-test="dialog"` und `data-name`, kein Fenster auf dem Gerätedetail. Beide Varianten erfüllen die Testschnittstelle; die Formularseite ist der einfachere Weg, weil die Views schon existieren.
- **Nicht gebaut (A-0075, 27.10.):** Protokoll und Signatur stehen im Prototyp in den Dialogen, sind aber in M3 nicht verlangt (M6). Sie fehlen deshalb in den Dialogen.

## Offene Fragen

## Hinweise für den Betrieb
