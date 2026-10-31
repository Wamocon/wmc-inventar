# Übergabe WMCNL-2755

Ausgefüllt von: Gregor · Datum: 28.10.2026 · Zweig: gregor/a-0076-arbeitsplaetze · Letzter Commit: (siehe git log)

## Zusammenfassung

M1 Grundgerüst, M2 Bestand, M3 Lebenszyklus und M4 Arbeitsplätze sind fertig. Alle 140 Tests sind grün. M3 Nachbesserung (A-0074): Gerätedetail zeigt jetzt Aktionen je Status und Recht (Auf Lager: Ausgabe, Umzug, Reparatur, Ausmustern, Ändern; In Benutzung: Rückgabe, Umzug; In Reparatur: Abschließen). `status` trägt `data-wert`, `historie` trägt `data-typ` je Vorgang (Aufnahme, Ausgabe, Import). Fehler im Formular tragen `data-test="fehler"`. M3 Nachbesserung (A-0075): Alle sieben Vorgänge (Ausgabe, Rückgabe, Umzug, Reparatur, Reparatur abschließen, Ausmustern, Bearbeiten) öffnen sich jetzt als Dialoge mit `data-test="dialog"` und `data-name`, die Schaltfläche `data-test="speichern"` schließt ab, nach dem Speichern erscheint `data-test="meldung"` und das Gerätedetail zeigt den neuen Status. Beschriftungen stimmen mit dem Prototyp überein: Ausgabe "Person" und "Arbeitsplatz", Reparatur starten "Fehlerbeschreibung" (Pflicht), Umzug "Neuer Arbeitsplatz", Reparatur abschließen "Zustand jetzt", Rückgabe "Bemerkung, Mängel" und "Danach". Das Gerätedetail trägt `data-test="verbleib"`, `data-typ` steht auf dem Element `data-test="vorgang"`. Beispieldaten: `_leeren()` leert jetzt auch `geraete_vorgang` vor `geraete_gerat`. M4 bringt Soll-Ist-Abgleich je Arbeitsplatz (F-62), Bedarf mit Lagerbestand (F-63), Geräte der festen Person getrennt (F-64) und Erstinventur-Fortschritt je Ort (F-89). M4 Nachbesserung (A-0076, Teil 1): Die Seiten der Arbeitsplätze liegen unter `/arbeitsplaetze/`, `/arbeitsplaetze/liste/` und `/arbeitsplaetze/<Kennung>/`, unter `/geraete/arbeitsplaetze/` bleibt nichts; die Detailseite und „Prüfen“ nehmen die Kennung. Der Raumplan (F-65 bis F-68) zeigt den Grundriss aus der DATEIABLAGE, 15 Plätze `platz` mit `data-id` = Kennung, `data-soll-ist` = `vollstaendig`, `unvollstaendig` oder `mehr` und `data-x`, `data-y` in Prozent mit Punkt, 4 Flächen `raumort` mit `data-id` und die Plätze ohne Position in `ohne-position`. Klick oder Enter auf einen Platz öffnet ... [truncated]
M3 Nachbesserung (A-0098): F-40: `gerat_bearbeiten` legt je geändertem Feld einen Vorgang „Änderung“ an mit `aenderung_feld`, `aenderung_alter_wert`, `aenderung_neuer_wert`; die Historie zeigt das Feld, den alten und den neuen Wert. F-43: `konten/models.py:bezeichnung` zeigt den Namen, sonst die E-Mail-Adresse; jede Zeile der Historie und „Erstellt“ zeigen das Konto. F-44: Suche nach Inventarnummer, Seriennummer, Modell, Hostname und Person; jede Trefferzeile trägt `data-test="suchtreffer"`, das Suchfeld trägt `data-test="suche"`. F-131: Der Ausgabe-Dialog bekommt „Zustand“ (Auswahl mit den vier Stufen), „Zubehör komplett“ (Ja/Nein) und „Bemerkung“; der Zustand geht in den Vorgang Ausgabe und auf das Gerät. F-02: Kontenverwaltung unter `/konten/` mit `data-test="konten-liste"` und `data-test="konto-anlegen"`, nur für Admin (403 für Mitarbeiter); Navigation `nav-konten` zeigt dorthin.

M3 Nachbesserung (A-0099): F-52: Offboarding-Ansicht unter `/personen/<id>/offboarding/` zeigt alle Geräte der Person (Inventarnummer und Modell oder Gerätename) und deren offene Leihen. Button `data-test="alle-zuruecknehmen"`; nach der Bestätigung sind alle Geräte der Person Auf Lager, jedes mit einem Vorgang „Rückgabe“. Service-Funktion `geraete/services.py:person_alle_zuruecknehmen`. F-53: Austritt eintragen unter `/personen/<id>/austritt/eintragen/` mit `data-test="austritt-eintragen"` auf der Personenseite. Sind der Person noch Geräte zugeordnet, zeigt der Dialog `data-test="warnung"` mit den Geräten. Speichern mit Austrittsdatum unter `/personen/<id>/austritt/speichern/`; setzt `person.austritt` und `person.aktiv=False`. F-14: Löschen am Gerätedetail mit `data-test="aktion-loeschen"`, nur für Admin und nur solange außer Aufnahme kein Vorgang existiert. Dialog `data-name="loeschen"` mit `data-test="bestaetigen"` und `data-test="abbrechen"`; nach der Bestätigung ist das Gerät gelöscht, die Meldung nennt „gelöscht“. View `geraete/views.py:loeschen_zeigen` (Dialog) und `geraete/views.py:loeschen` (POST).

M4 Nachbesserung (A-0107, Teil 2): Plan pflegen (F-67): Admins laden unter `/arbeitsplaetze/plan/<id>/bearbeiten/` je Etage einen Grundriss hoch, als PNG, JPG, SVG oder die erste Seite eines PDF (mit pypdfium2 zum Bild); die Datei liegt unter DATEIABLAGE in `grundrisse/`. Arbeitsplätze und Räume lassen sich auf dem Plan an ihre Stelle ziehen; gespeichert wird die Position in Prozent von Breite und Höhe des Bildes, gemessen am Mittelpunkt. Plätze ohne Position stehen in `ohne-position` neben dem Plan. Rechte: it-admin@beispiel.test 200, gf@beispiel.test und anna.becker@beispiel.test 403. `geraete/tests.py:PlanPflegeTests` (8 Tests): Upload PNG und PDF, Position speichern, Position erscheint als data-x/data-y, ohne-position, 200/403. `stammdaten/views.py:plan_bearbeiten`, `stammdaten/views.py:_grundriss_speichern`, `stammdaten/models.py:Plan.grundriss` (FileField), `stammdaten/migrations/0004_grundriss_datei.py`.

M4 Nachbesserung (A-0108, Teil 3): QR-Code und Etiketten (F-12, F-70 bis F-73, F-89): Das Gerätedetail trägt `data-test="qr"` mit `data-qr` = BASIS_URL + /g/<Inventarnummer> und einen QR-Code als SVG (segno). `/g/<Inventarnummer>` leitet Admin und Leser zum Gerätedetail weiter, Mitarbeiter erhalten 403 (F-112). Das Etikett trägt QR-Code, Inventarnummer in Klarschrift, Kategorie, Modell und „Eigentum der WAMOCON GmbH"; gedruckt als PDF mit weasyprint. Einzelnes Etikett über `data-test="aktion-etikett"` am Gerätedetail. Bogen (A4, 24 Etiketten zu 70 × 37 mm) über `data-test="auswahl"` je Zeile und `data-test="etiketten-drucken"` in der Geräteliste; die Startposition ist wählbar (`data-test="startposition"`, F-73). `/etiketten/?ort=<Kennung>` druckt die Etiketten je Ort, sortiert nach bisheriger Kennung (F-89); „Etiketten für den Platz" im Pop-up führt dorthin. „Speichern und Etikett drucken" am Erfassungsformular speichert das Gerät und liefert das PDF (F-12). Alle 187 Tests sind grün. `geraete/etiketten.py` (qr_svg, etikett_html, bogen_pdf, etiketten_fuer_ort), `geraete/views.py` (gerat_kurz, etikett_drucken, etiketten_auswahl, etiketten_ort, _qr_svg), `geraete/urls.py` und `inventar/urls.py` (neue Adressen), `templates/geraete/detail.html` (QR-Block), `templates/geraete/liste.html` (Auswahl + Etiketten drucken), `templates/geraete/neu.html` (Speichern und Etikett drucken), `templates/geraete/platz_popup.html` (Link zu /etiketten/), `geraete/tests.py` (19 neue Tests: QRCodeTests, EtikettenBogenTests, EtikettenOrtTests, SpeichernUndEtikettTests, ListEtikettenTests).

M4 Nachbesserung (A-0110, Teil 3): Etiketten: `/etiketten/` ohne Parameter ist jetzt eine Auswahlseite für den Admin (Kapitel 6 der Anforderungen: Bildschirm Etiketten nur für den Admin): dort wählt er einen Arbeitsplatz oder Lagerort und die Startposition (F-73) und druckt mit „Bogen drucken" den Bogen, sortiert nach bisheriger Kennung (F-89). `templates/geraete/etiketten.html` (`data-test="etiketten-ort-formular"`, `etiketten-ort-auswahl`, `startposition`, `etiketten-drucken`); `geraete/views.py:etiketten_ort` rendert die Auswahl und liefert mit `?ort=<Kennung>` weiter das PDF. `/etiketten/auswahl/` ist jetzt nur für Admin; Leser und Mitarbeiter erhalten auf `/etiketten/`, `/etiketten/auswahl/` und `/etiketten/?ort=…` 403 mit „Keine Berechtigung" (TESTSCHNITTSTELLE Kapitel 3). „Etiketten für den Platz" im Pop-up führt mit `startposition=1` zum Bogen. `geraete/tests.py:EtikettenOrtTests`: `test_etiketten_ort_admin_200` (?ort= → PDF), `test_etiketten_ort_admin_auswahlseite` (Auswahl mit Startposition und Bogen drucken), `test_etiketten_ort_leser_403`, `test_etiketten_ort_mitarbeiter_403`. Alle 187 Tests sind grün.

M4 Nachbesserung (A-0111, Teil 4): Mobile Gerätedetailseite und Erstinventur (F-74, F-89, F-24): Das Gerätedetail trägt `data-test="aktion-notiz"` für Admin; `aktion-notiz` öffnet den Dialog `data-test="dialog" data-name="notiz"` mit `data-test="notiz-feld"` und `data-test="speichern"`; die Notiz steht danach am Gerät (F-74). „Geprüft" (`data-test="geprueft"`) setzt „Zuletzt geprüft" (Datum + Benutzer) und erhöht inventur-fortschritt des Ortes um eins (F-16, F-89). Mobile: `@media (max-width:560px)` in `static/basis.css` macht das Detail-Grid einspaltig, die QR-Zeile stapelt vertikal und die Lebenszyklus-Zeilen einspaltig; ab 360 px kein waagerechtes Scrollen. `geraete/views.py:notiz_zeigen` (Dialog), `geraete/forms.py:GeratNotizForm`, `templates/geraete/notiz.html`, `templates/geraete/detail.html` (aktion-notiz, geprueft), `static/basis.css` (Mobile-Media-Query), `geraete/urls.py` (neue Route), `geraete/tests.py` (7 neue Tests: `NotizGeratTests` 4, `GeprueftButtonTests` 3). Alle 194 Tests sind grün.

M2 Nachbesserung (A-0112, Rest Teil 1): Historie, Mehrfacherfassung und Vorlage (F-40, F-11, F-13, N-03). F-40: `gerat_bearbeiten` in `geraete/services.py` vergleicht jetzt den alten Wert aus der Datenbank mit dem neuen Wert aus dem Formular, bevor die Instanz überschrieben wird (`_aenderungen_erkennen`). Ohne Änderung kein Vorgang. Die Historie in `templates/geraete/detail.html` zeigt je Änderung das Feld, den alten und den neuen Wert als Text (nicht nur `data-alt`/`data-neu`). F-11: Das Erfassungsformular unter `/geraete/neu/` trägt ein Textfeld `seriennummern` mit `data-test="seriennummern"`; `gerat_anlegen` in `geraete/services.py` liest die Zeilen, legt je Zeile ein Gerät mit eigener Inventarnummer und Vorgang „Aufnahme" an; ohne Seriennummer entsteht ein Gerät wie bisher. `geraete/forms.py:GeratForm` trägt das neue Feld; `templates/geraete/neu.html` rendert es. F-13: Das Gerätedetail trägt `data-test="aktion-vorlage"`; der Link führt zu `/geraete/neu/?vorlage=<Inventarnummer>`; `geraete/views.py:neu_anzeigen` liest die Vorlage und belegt die Stammdaten des Formulars, die Seriennummer bleibt leer. N-03: `/geraete/neu/` und `/geraete/speichern/` antworten für Nutzer ohne Änderungsrecht (z. B. `gf@beispiel.test`) jetzt mit 403 (`PermissionDenied`), nicht mehr mit 302. `geraete/tests.py` (11 neue Tests: `AenderungsHistorieTests` 4, `MehrfacherfassungTests` 4, `VorlageTests` 3). Alle 205 Tests sind grün.

**Nicht Teil dieser Karte (A-0099):**
- **Protokoll in einem Vorgang (F-130):** Kommt mit M6; die Rückgabe-Ansicht im Offboarding zeigt keine Protokollfunktion.
- **Deaktivieren des Kontos am Tag nach dem Austritt (F-53):** Ist ein Befehl für den Tageslauf und nicht Teil dieser Karte. `austritt_speichern` setzt `person.aktiv=False`, das Konto-Deaktivieren ist ein separater Tageslauf-Auftrag.

## Stand je Meilenstein

| Meilenstein | Stand | Commit | Datum | Hinweis |
|---|---|---|---|---|
| M1 Grundgerüst | fertig | 711ddd5 | 22.10.2026 | Projekt, Anmeldung, Konten, Stammdaten, beispieldaten |
| M2 Bestand | fertig | a3a85da | 31.10.2026 | Geräte erfassen, bearbeiten, prüfen, Suche, Konflikte, Arbeitsliste; Historie (F-40), Mehrfacherfassung (F-11), Vorlage (F-13) (A-0112) |
| M3 Lebenszyklus | fertig | | 28.10.2026 | Ausgabe, Rückgabe, Umzug, Reparatur, Ausmusterung, Vorgang-Historie, Gerätedetail-Aktionen (A-0074), Vorgänge als Dialoge (A-0075), Formulare und Fehlermeldungen (A-0097), Historie/Suche/Zustand/Konten (A-0098), Offboarding/Austritt/Löschen (A-0099) |
| M4 Arbeitsplätze | fertig | a13dc17 | 30.10.2026 | Soll-Ist-Abgleich (F-62), Bedarf (F-63), Feste Person (F-64), Erstinventur (F-89); Raumplan (F-65, F-66, F-68, F-69) mit Pop-up und `aktion-im-raumplan`; Plan pflegen (F-67) mit Upload und Position (A-0107); QR-Code, Etiketten, PDF-Druck (A-0108); Mobile (F-74), Notiz, Geprüft (A-0111) |
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
| F-11 | M | M2 | Mehrere gleiche Geräte auf einmal erfassen | erfüllt | `geraete/services.py:gerat_anlegen` liest Zeilen aus `seriennummern`; Test: `test_drei_zeilen_erzeugen_drei_geraete` |
| F-12 | M | M4 | Etikett direkt nach dem Speichern drucken | erfüllt | `geraete/views.py:neu_anlegen` mit `aktion=etikett`, Test: `test_speichern_und_etikett_drucken` |
| F-13 | S | M2 | Gerät als Vorlage kopieren | erfüllt | `geraete/views.py:neu_anzeigen` mit `?vorlage=<Nr>`; Test: `test_vorlage_belegt_stammdaten_und_seriennummer_leer` |
| F-14 | M | M2 | Fehlerfassung löschen | erfüllt | `geraete/views.py:loeschen`, `geraete/views.py:loeschen_zeigen`, Test: `test_admin_ohne_vorgang_kann_loeschen`, `test_admin_mit_vorgang_kann_nicht_loeschen`, `test_mitarbeiter_kann_nicht_loeschen` |
| F-20 | M | M3 | Ein oder mehrere Geräte an eine Person und/oder einen Arbeitsplatz ausgeben | erfüllt | `geraete/services.py:gerat_ausgeben`, Test: `test_ausgabe_an_person`, `test_ausgabe_an_ort` |
| F-21 | M | M3, M6 | Ausgabeprotokoll bei Ausgabe an eine Person | teilweise | Ausgabe in Service-Schicht vorhanden; PDF-Protokoll (FRM-001) in M6 |
| F-22 | M | M3, M7 | Papierweg | teilweise | Vorgang „Unterschrift offen" in Service-Schicht; Scan-Upload in M7 |
| F-23 | M | M3 | Ausgabe nur an einen Arbeitsplatz | erfüllt | `geraete/services.py:gerat_ausgeben`, Test: `test_ausgabe_an_ort` |
| F-24 | K | M4 | Neue Person ausstatten | erfüllt | `geraete/services.py:bedarf_uebersicht` schlägt fehlende Geräte aus dem Profil vom Lager vor (F-24, Kann); Test: `test_bedarf_zeigt_fehlende`, `test_bedarf_mit_lagerbestand`; `templates/geraete/bedarf.html` |
| F-30 | M | M5, M6 | Admin verleiht direkt | offen | |
| F-31 | M | M5 | Mitarbeiter fragt Leihgerät an | offen | |
| F-32 | M | M5 | Admin entscheidet | offen | |
| F-33 | M | M5, M6 | Leihgerät ausgeben | offen | |
| F-34 | M | M5 | Keine Doppelbuchung | offen | |
| F-35 | S | M5 | Verlängerung | offen | |
| F-36 | M | M5, M7 | Überfällige Leihen | offen | |
| F-37 | M | M5 | Anfrage zurückziehen | offen | |
| F-40 | M | M2 | Stammdaten ändern | erfüllt | `geraete/services.py:gerat_bearbeiten` mit `_aenderungen_erkennen` (Vergleich gegen DB-Stand); Test: `test_aendern_zeugt_vorgang_aenderung_mit_alt_neu` |
| F-41 | M | M3 | Umzug | erfüllt | `geraete/services.py:gerat_umziehen`, Test: `test_umzug` |
| F-42 | M | M3 | Reparatur | erfüllt | `geraete/services.py:gerat_in_reparatur_geschickt`, `gerat_reparatur_fertig` mit `ziel` (F-42), Test: `test_reparatur_start`, `test_reparatur_fertig_ziel_lager`, `test_dialog_reparatur_abschliessen_ziel_bisherige_zuordnung` |
| F-43 | M | M2 | Historie je Gerät | erfüllt | `geraete/services.py:gerat_bearbeiten` legt je geändertem Feld einen Vorgang „Änderung“ an (F-40, A-0098); `konten/models.py:bezeichnung` zeigt Name, sonst E-Mail (F-43); Test: `test_historie_aenderungen_gezeigt`, `test_historie_zeigt_konto` |
| F-44 | M | M2 | Globale Suche | erfüllt | `geraete/views.py:liste` mit Suchfeld `q`, Test: `test_liste_suche_nach_name` |
| F-50 | M | M3 | Rückgabe einzelner oder mehrerer Geräte einer Person | erfüllt | `geraete/services.py:gerat_rueckgeben`, Test: `test_rueckgabe_nach_lager`, `test_rueckgabe_ziel_reparatur` |
| F-51 | M | M3, M6 | Rücknahmeprotokoll | teilweise | Rückgabe in Service-Schicht vorhanden; PDF-Protokoll (FRM-002) in M6 |
| F-52 | M | M3 | Offboarding-Ansicht | erfüllt | `stammdaten/views.py:offboarding`, `stammdaten/views.py:offboarding_zuruecknehmen`, `geraete/services.py:person_alle_zuruecknehmen`, Test: `test_offboarding_zeig_geraete`, `test_alle_zuruecknehmen` |
| F-53 | M | M3 | Austritt eintragen | erfüllt | `stammdaten/views.py:austritt_eintragen`, `stammdaten/views.py:austritt_speichern`, Test: `test_austritt_mit_geraeten_zeigt_warnung`, `test_austritt_ohne_geraete_zeigt_keine_warnung`, `test_austritt_speichern_mit_datum` |
| F-55 | M | M3 | Ausmustern | erfüllt | `geraete/services.py:ausmustern`, Test: `test_ausmusterung` |
| F-56 | M | M3 | Löschnachweis bei Datenträgern | erfüllt | `geraete/services.py:ausmustern` mit `loeschung_art`, `loeschung_nachweis`, Test: `test_ausmusterung_datentraeger_mit_loeschung` |
| F-57 | M | M3 | Verlust und Diebstahl | erfüllt | `geraete/services.py:ausmustern` mit `disposition=Verlust`, `bestaetigt_gemeldt`, Test: `test_ausmusterung_verloren_mit_bestatigung` |
| F-58 | M | M3 | Archiv | erfüllt | `Vorgang`-Modell mit `abschliesst=False` für offene Vorgänge, Test: `test_vorgaenge_nicht_geloescht`; ausgemusterte Geräte nicht änderbar (A-0097), Test: `test_ausgemustert_zeigt_keine_aktion_bearbeiten`, `test_ausgemustert_aendern_adresse_lehnt_ab` |
| F-60 | M | M1 | Arbeitsplätze und Lagerorte pflegen | erfüllt | `stammdaten/views.py:orte_liste`, `orte_anlegen`, `orte_aendern` |
| F-61 | M | M4 | Ausstattungsprofile pflegen und Arbeitsplätzen zuweisen | erfüllt | `stammdaten/models.py:Ausstattungsprofil`, `Profilposition`, `Ort.profil`; Test: M4-Tests mit Profil |
| F-62 | M | M4 | Soll-Ist-Abgleich je Arbeitsplatz | erfüllt | `geraete/services.py:soll_ist_abgleich`, Test: `test_soll_ist_vollstaendig`, `test_soll_ist_unvollstaendig`, `test_soll_ist_mehr_als_soll` |
| F-63 | M | M4 | Übersicht und Bedarf | erfüllt | `geraete/services.py:bedarf_uebersicht`, Test: `test_bedarf_zeigt_fehlende`, `test_bedarf_mit_lagerbestand` |
| F-64 | S | M4 | Feste Person am Arbeitsplatz | erfüllt | `geraete/services.py:gerate_der_person`, Test: `test_gerate_der_person_getrennt` |
| F-89 | M | M4 | Erstinventur per Scan | teilweise | `geraete/services.py:fortschritt_je_ort`, Test: `test_fortschritt_je_ort`, `test_fortschritt_nach_pruefen`; Etiketten je Ort (F-89) über `/etiketten/?ort=<Kennung>` (A-0108, A-0110: Auswahlseite mit Startposition, nur Admin), Test: `test_etiketten_ort_admin_200`, `test_etiketten_ort_admin_auswahlseite`; Scan-UI noch offen (M5) |
| F-65 | M | M4 | Raumplan | erfüllt | `geraete/views.py:arbeitsplaetze`, `geraete/services.py:plan_auswahl`, `plaetze_des_plans`, `raumorte_des_plans`, `ohne_position`, Test: `RaumplanTests` (5 Tests), Beispieldaten: 15 Plätze, 4 Räume mit `plan_id` (A-0106) |
| F-66 | M | M4 | Pop-up je Arbeitsplatz | erfüllt | `geraete/views.py:platz_popup`, `raum_popup`, Test: `test_ort_pruefen_view` (URL), Pop-up zeigt Kennung, Raum, Person, Profil, Soll-Ist, Geräte |
| F-67 | M | M4 | Plan pflegen | erfüllt | `stammdaten/views.py:plan_bearbeiten` (Upload PNG/JPG/SVG/PDF, Position speichern), `stammdaten/models.py:Plan.grundriss`, `geraete/tests.py:PlanPflegeTests` (8 Tests), Beispieldaten: Eschborn, 1. OG mit PNG (A-0107) |
| F-68 | M | M4 | Räume ohne festen Platz | erfüllt | `geraete/views.py:raum_popup`, `raumorte_des_plans` (alle Räume des Plans, nicht nur mit Geräten), Test: `RaumplanTests.test_raumplan_admin_sieht_alle_plaetze` (4 `raumort` mit `data-id`, A-0106) |
| F-69 | S | M4 | Gerät im Plan finden | erfüllt | `templates/geraete/detail.html` mit `aktion-im-raumplan`, Raumplan hebt Platz oder Raum hervor |
| F-70 | M | M4 | QR-Code je Gerät | erfüllt | `geraete/etiketten.py:qr_svg`, `geraete/views.py:_qr_svg`, `templates/geraete/detail.html` mit `data-test="qr"` und `data-qr`, `/g/<Inventarnummer>` weiterleitet (F-70), Test: `test_detail_traegt_qr_mit_data_qr`, `test_kurzansicht_admin_weiterleitung` |
| F-71 | M | M4 | Etiketteninhalt | erfüllt | `geraete/etiketten.py:etikett_html` (QR, Inventarnummer, Kategorie, Modell, „Eigentum der WAMOCON GmbH"), Test: `test_etikett_drucken_admin_200` |
| F-72 | M | M4 | Druck als PDF | erfüllt | `geraete/etiketten.py:bogen_pdf` (weasyprint, A4, 24 × 70 × 37 mm), Test: `test_bogen_drei_geraete_admin_200`, `test_etikett_drucken_admin_200` |
| F-73 | S | M4 | Angebrochene Bögen | erfüllt | `geraete/etiketten.py:bogen_pdf` mit `startposition`, `data-test="startposition"` in `templates/geraete/liste.html`, Test: `test_bogen_startposition_3_felder_davor_frei` |
| F-74 | M | M4 | Mobile Gerätedetailseite | erfüllt | `static/basis.css` `@media (max-width:560px)` (Detail-Grid einspaltig, QR-zeile stapelt, Lebenszyklus einspaltig); `templates/geraete/detail.html` mit `aktion-notiz` und `geprueft`; `templates/geraete/notiz.html` (Dialog `data-name="notiz"`); Test: `NotizGeratTests` (4 Tests), `GeprueftButtonTests` (3 Tests) |
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
| F-131 | M | M3 | Daten vorbelegen | erfüllt | `geraete/services.py:gerat_ausgeben` mit `zustand`, `zubehoer_komplett`, `anmerkung` (F-131, A-0098); Test: `test_ausgabe_zustand_neuwertig`, `test_ausgabe_zustand_gut`, `test_ausgabe_zustand_spuren`, `test_ausgabe_zustand_eingeschraenkt` |
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
| N-10 | | alle | Qualität | erfüllt | `manage.py check` grün; 205 Tests (alle grün); `migrate` und `beispieldaten --neu` ohne Fehler |
| N-11 | | M7 | Wartbarkeit | offen | |

## Wie getestet

Befehle mit gekürzter Ausgabe: `python manage.py test` (205 Tests, alle grün), `python manage.py check` (keine Probleme), `python manage.py migrate` (keine neuen Migrationen), `python manage.py beispieldaten --neu` (21 Kategorien, 26 Geräte, 4 Konten, 1 Raumplan mit 15 Arbeitsplätzen und 4 Räumen). `testsiegel` und `tageslauf` sind noch nicht implementiert (M6/M7).

## Offene Punkte (A-0099)

- **F-130 Protokoll in einem Vorgang:** Kommt mit M6 (Signatur). Die Offboarding-Ansicht zeigt keine Protokollfunktion.
- **Deaktivieren des Kontos am Tag nach dem Austritt:** Ist ein Befehl für den Tageslauf (M7) und nicht Teil dieser Karte. `austritt_speichern` setzt `person.aktiv=False`; das Konto-Deaktivieren ist ein separater Tageslauf-Auftrag.
- **Dialog-Implementierung (F-14):** Der Löschen-Dialog ist die Bestätigungsseite `templates/geraete/loeschen.html` mit `data-test="dialog"` und `data-name="loeschen"`, `data-test="bestaetigen"` und `data-test="abbrechen"`. `data-test="aktion-loeschen"` ist der Link auf der Detailseite.
- **Offboarding und Austritt sind Admin-aktionen:** `offboarding_zuruecknehmen` und `austritt_speichern` erfordern `ist_admin`. `offboarding` und `austritt_eintragen` zeigen die Seiten für Admin und Leser.

## Annahmen und Abweichungen

- **Login-Bug (Werkbank 23.10.):** `konten/models.py` hatte das Feld `fehlersuche`, aber `update_fields` in `konten/models.py` und `konten/views.py` verwies auf `fehlversuche`. Behoben: Feld heißt jetzt `fehlversuche` (korrekter Name), alle `update_fields` stimmen überein. Test: `konten/tests.py:test_update_fields_benutzt_fehlversuche`.
- **ROOT_DIR (Werkbank 23.10.):** `inventar/settings.py` setzt `ROOT_DIR = BASE_DIR`, damit `var/inventar.sqlite3`, `var/dateien` und `var/testsiegel.p12` im Repository liegen, wie `docs/TESTSCHNITTSTELLE.md` Abschnitt 1 es verlangt. Test: `manage.py test` läuft mit `INVENTAR_DEBUG=1` und schreibt nach `var/` im Repo.
- **beispieldaten --neu (Werkbank 23.10.):** `_leeren()` leert jetzt alle Tabellen in der Reihenfolge der Fremdschlüssel (zuerst die verweisenden, dann die referenzierten). `jetzt.txt` wird aus `ROOT_DIR/var/` gelöscht, nicht aus `BASE_DIR.parent/var/`.
- **beispieldaten --neu (A-0075, 27.10.):** `_leeren()` leert jetzt auch `geraete_vorgang` vor `geraete_gerat`, weil `Vorgang` einen Fremdschlüssel auf `Gerat` trägt. Ohne diese Zeile schlägt `DELETE FROM geraete_gerat` mit FOREIGN KEY constraint failed an.
- **Vorgangstypen leihen, instandhaltung, rueckstellung (A-0075, 27.10.):** In Teil 1 (A-0074) entfernt, weil `docs/anforderungen.md` M3 diese Typen nicht verlangt. M5 (Verleih) bringt `leihen` und `rueckstellung`, M6/M7 bringen `instandhaltung`. Die Felder `leihgabe_an`, `leihgabe_seit`, `instandhaltung_frist`, `instandhaltung_von` bleiben im Modell, sie werden in M5/M6/M7 aktiv.
- **Dialog-Implementierung (A-0075, 27.10.):** Der Dialog ist die Formularseite mit dem Rahmen `data-test="dialog"` und `data-name`, kein Fenster auf dem Gerätedetail. Beide Varianten erfüllen die Testschnittstelle; die Formularseite ist der einfachere Weg, weil die Views schon existieren.
- **Nicht gebaut (A-0075, 27.10.):** Protokoll und Signatur stehen im Prototyp in den Dialogen, sind aber in M3 nicht verlangt (M6). Sie fehlen deshalb in den Dialogen.
- **Fehlermeldungen standardisiert (A-0097, 28.10.):** Alle Formularseiten zeigen jetzt bei jeder ungültigen Eingabe oben ein Element mit `data-test="fehler"`, auch bei Feldfehlern. `novalidate` an allen Formularen, damit der Browser nicht bremst. Gemeinsames Fragment `templates/fragmente/fehler.html`.
- **F-10 Seriennummer (A-0097, 28.10.):** Dieselbe Seriennummer beim selben Hersteller wird jetzt abgelehnt mit `data-test="fehler"`, nicht mehr nur als Hinweis. Beim anderen Hersteller bleibt der Hinweis. Service-Funktion `seriennummer_pruefen` mit `__iexact` und `.strip()`.
- **Rückgabe nach Prototyp (A-0097, 28.10.):** „Zubehör komplett" ist jetzt eine Auswahl (Ja/Nein, Ja voreingestellt), kein Pflichtkästchen. „Danach" ist eine Auswahl (Lager, Reparatur, fehlend). Wer „fehlt" wählt, startet die Ausmusterung mit Grund „verloren".
- **Ausmustern nach Prototyp (A-0097, 28.10.):** „Grund" beginnt mit „Bitte wählen" und ist Pflicht. „Verbleib" ist Pflicht außer bei verloren/gestohlen. Bestätigung „gemeldet" Pflicht bei verloren/gestohlen. Datenlöschung (Art + Nachweis) Pflicht bei Datenträger und nicht bei Verlust.
- **Kategorien-Templates (A-0097, 28.10.):** `kategorie_anlegen.html` und `kategorie_aendern.html` angelegt. Die Views rendern sie jetzt, `/kategorien/neu/` stürzt nicht mehr ab.
- **Reparatur abschließen (A-0097, 28.10.):** „Ziel" hat jetzt zwei Optionsfelder mit eigenen Beschriftungen („Bisherige Zuordnung" und „Lager"), nicht mehr eine Auswahl. `reparatur_ziel`-Feld im `Vorgang`-Modell (Migration 0004).
- **F-58 Ausgemusterte nicht änderbar (A-0097, 28.10.):** „Ändern" und „Prüfung abhaken" ausgeblendet auf der Detailseite. `/aendern/` lehnt ab mit Weiterleitung und Fehlermeldung. Service-Schicht prüft `status == STATUS_AUSGEMUSTERT` und wirft `GeratFehler`.
- **F-40 Historie mit Änderungen (A-0098, 28.10.):** `gerat_bearbeiten` legt je geändertem Feld einen Vorgang vom Typ „Änderung" an mit `aenderung_feld`, `aenderung_alter_wert`, `aenderung_neuer_wert`. Ohne Änderung kein Vorgang. Test: `test_historie_aenderungen_gezeigt`, `test_historie_aenderung_kein_vorgang_ohne_aenderung`.
- **F-43 Konto in der Historie (A-0098, 28.10.):** `konten/models.py:bezeichnung` zeigt den Namen der Person, sonst die E-Mail-Adresse. Jede Zeile der Historie und „Erstellt" zeigen das Konto, das den Vorgang ausgeführt hat. Test: `test_historie_zeigt_konto`, `test_konto_bezeichnung_zeigt_namen`.
- **F-44 Suche je Feld (A-0098, 28.10.):** Suche nach Inventarnummer, Seriennummer, Modell, Hostname (Gerätename) und Person (Vor- und Nachname). Jede Trefferzeile trägt `data-test="suchtreffer"`, das Suchfeld trägt `data-test="suche"`. Test: `test_suche_inventarnummer`, `test_suche_seriennummer`, `test_suche_modell`, `test_suche_hostname`, `test_suche_person`.
- **F-131 Zustand in der Ausgabe (A-0098, 28.10.):** Der Ausgabe-Dialog bekommt „Zustand" (Auswahl mit den vier Stufen, voreingestellt mit dem Zustand des Geräts), „Zubehör komplett" (Ja/Nein) und „Bemerkung". Der Zustand geht in den Vorgang Ausgabe und auf das Gerät. Test: `test_ausgabe_zustand_neuwertig`, `test_ausgabe_zustand_gut`, `test_ausgabe_zustand_spuren`, `test_ausgabe_zustand_eingeschraenkt`.
- **F-02 Kontenverwaltung (A-0098, 28.10.):** Kontenliste unter `/konten/` mit `data-test="konten-liste"` und `data-test="konto-anlegen"`, nur für Admin (403 für Mitarbeiter). Navigation `nav-konten` zeigt dorthin. Test: `test_konten_liste_admin_200`, `test_konten_liste_mitarbeiter_403`, `test_konto_anlegen_admin_200`, `test_konto_anlegen_mitarbeiter_403`.
- **Raumplan Filter (A-0106, 30.10.):** `geraete/services.py:plaetze_des_plans` und `raumorte_des_plans` filterten nach `etage` (Feld existiert nur an `Plan`), nicht nach `plan_id`. Behoben: Filter nutzt jetzt `plan_id=plan.id`. `raumorte_des_plans` nimmt jetzt alle Räume des Plans, nicht nur mit Geräten (F-68). Beispieldaten setzen `plan_id` auf alle 15 Arbeitsplätze und 4 Räume (Plan: Eschborn, 1. OG). Template `raumplan.html` korrigiert: `o.ort.kennung` statt `o.kennung` für `plaetze` (Diktat mit `ort` und `abgleich`). `stringformat:'g'` für `data-x` und `data-y` (Punkt statt Komma, TESTSCHNITTSTELLE Kapitel 2). Test: `RaumplanTests` (5 Tests: Admin/Leser sehen 15 Plätze + 4 Räume, Mitarbeiter 403, Positionen mit Punkt, `data-id` auf `raumort`).

## Offene Fragen

## Hinweise für den Betrieb
