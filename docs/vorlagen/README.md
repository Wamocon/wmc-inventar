# Vorlagen und Testdaten

| Datei | Inhalt |
|---|---|
| `bestandsliste_anonymisiert.xlsx` | Testfassung der Bestandsliste `WMC_Hardwarebestand.xlsx`. Gleiche Blätter, Spalten, Lücken und doppelten Kennungen wie das Original; Namen sind erfunden, Seriennummern, Rechnungs- und Vertragsnummern verfremdet. Gleiche Werte im Original sind auch hier gleich, damit das Zusammenführen über Seriennummer und Kennung testbar bleibt. |
| `grundriss_eschborn_1og.svg` | Grundriss Eschborn, 1. OG, nach dem Fluchtplan nachgezeichnet, ohne Plätze. Grundlage für den Raumplan in den Beispieldaten (`docs/TESTSCHNITTSTELLE.md`, Abschnitt 2) und Testdatei für das Hochladen eines Grundrisses (F-67). |
| `FRM-001.md`, `FRM-002.md` | Aufbau, Satzbild und Wortlaut der Protokolle WMC-IT-FRM-001 (Ausgabe) und WMC-IT-FRM-002 (Rücknahme), Version 1.1, mit Platzhaltern statt Personendaten. Maßgeblich für die PDFs (F-130) und für die Vorbelegung der Checklisten (F-132, F-133). Die Muster-PDFs selbst liegen nicht im Repo, weil sie Personendaten enthalten. |

Erwartete Eckwerte der Testdatei für Importtests (Kapitel 5.10):

- Blatt Inventar: 123 Zeilen, davon 31 Kleinteile, 10 Kamera-Zubehör, 1 Garantiezeile (AppleCare zum Mac Studio).
- Blatt Notebooks: 29 Zeilen. 11 davon passen über die Seriennummer zu Zeilen im Blatt Inventar (Mac Studio, zwei iPads, acht Huawei MateBook 16s), über den Gerätenamen allein passt keine.
- `WMC-I-2301` steht im Blatt Notebooks zweimal (Zeile 18 und 19) mit verschiedenen Seriennummern. Beide Seriennummern stehen auch im Blatt Inventar (Zeile 11 und 10), dort ohne Gerätenamen. Richtig ist: Jede Zeile ergänzt ihr eigenes iPad, beide iPads tragen danach den Gerätenamen `WMC-I-2301`, und beide zeigen den Hinweis auf den doppelten Namen. Falsch wäre, Zeile 19 über den Gerätenamen dem iPad aus Zeile 18 zuzuordnen (F-84: Seriennummer geht vor).
- Blatt Smartphones: 10 Zeilen, 5 mit „Defekt“ = Ja.
- Blatt Raumliste Hardware: 8 Arbeitsplätze `WMC-WP-01` bis `-08`, zwei davon aufgelöst, 56 Gerätezeilen.
- Blatt Headset ist leer, die drei Blätter Bedarfsanalyse werden nicht übernommen. Ihre Produktlinks sind durch `https://example.com/link-entfernt` ersetzt.

## Importtest mit festen Erwartungswerten

Für die Eckwerte wird erst Blatt Inventar, dann Blatt Notebooks eingelesen, in eine Datenbank nach `beispieldaten --neu`. Die Zuordnungen im Prototyp sind Anschauung; für diese Datei gelten die folgenden. Zeilenangaben sind Excel-Zeilen. Zeilen, in denen außer einer laufenden Nummer nichts steht, gelten als leer und werden nicht gezählt (Notebooks, Zeilen 34 bis 36). „-“, „?“ und „N.A.“ gelten als leer (F-82).

### Blatt Inventar (Kopfzeile in Zeile 3)

Spalten: Typ → Kategorie (über die Werte unten), Hersteller → Hersteller, Modell → Modell, Gerätename → Gerätename, Seriennummer → Seriennummer, Rechnungsnummer → Rechnungsnummer, Garantie Ende → Garantie bis, Datum erhalt → Kaufdatum, Kommentar → Notiz; Rechnung, Garantie, Datum Bestandsaufnahme und Status → nicht übernehmen. Geräte ohne Person und Arbeitsplatz kommen an den Lagerort `LAGER-EG`.

| Wert in „Typ“ | Zeilen | Kategorie |
|---|---|---|
| Notebook | 8 | Notebook |
| Rechner | 1 | Desktop-PC |
| Tablet | 3 | Tablet |
| Smartphone | 3 | Smartphone |
| Smartwatch | 1 | Smartwatch |
| Monitor | 3 | Monitor |
| Docking Station | 8 | Dockingstation |
| Headset | 11 | Headset |
| Webcam | 8 | Webcam |
| Maus | 5 | Maus |
| Maus + Tastatur, Tastatur | 5 + 1 | Tastatur |
| Konferenzsystem | 1 | Konferenzsystem |
| Power Bank | 10 | Powerbank |
| USB-Hub | 9 | USB-Hub |
| Mikrofon, DJI Mic 2 (Einzelmikrofon für Osmo Pocket 3), Gimbel-Büro, Gimbel-Mobile | 4 | Kamera und Video |
| Garantie | 1 | Garantiezeile, ergänzt das Gerät mit derselben Seriennummer (F-84) |
| USB-C Kabel, Steckdose (Tisch), 13in1 USB-C Multifunction Adapter, Mauspad | 31 | nicht übernehmen (O-18) |
| die zehn Werte mit Kamera-Akku, „Kamera Zubehör“ oder „(Zubehör)“ | 10 | nicht übernehmen (O-18) |

Erwartete Vorschau: 81 neu, 1 ergänzt (Garantiezeile 5 zum Mac Studio aus Zeile 4), 0 Konflikt, 41 übersprungen. Danach gibt es 81 Geräte, alle „Auf Lager“. Darin liegen drei Fallen:

- Zeile 18 hat dieselbe Seriennummer wie Zeile 17 (beide Logitech). Zeile 18 wird ohne Seriennummer angelegt, ihre Notiz nennt die Nummer, Hinweis `seriennummer-doppelt`.
- `WMC-HB-01` steht in Zeile 71 und 97, `WMC-HB-07` in Zeile 77 (USB-Hub) und 80 (iPad). Innerhalb eines Blatts wird nicht zusammengeführt: Es entstehen vier Geräte, alle mit Hinweis `geraetename-doppelt`.
- Die acht Huawei MateBook 16s (Zeilen 38 bis 45) haben hier keinen Gerätenamen und keine Person.

### Blatt Notebooks (Kopfzeile in Zeile 4)

Spalten: ID → nicht übernehmen, Gerät → Modell und über die Werte Kategorie, Gerätename → Gerätename, Seriennummer → Seriennummer, Verliehen an MA → Person, Kommentar → Notiz.

| Wert in „Gerät“ | Kategorie |
|---|---|
| alle MacBook-, Lenovo-, Huawei-Matebook-Werte und „Huawei Notebook“ | Notebook |
| iMac (zwei Werte), Mac Studio | Desktop-PC |
| iPad 11 Zoll 128 GB Silber, iPad 11 Zoll 128 GB Space Grau | Tablet |
| Huawei Monitor | Monitor |
| Huawei Maus | Maus |
| Synnology Nas 12 TB, Synnology Nas 4 TB, Buffalo 4 TB | NAS |

Personen: Jeder volle Name wird eine neue Person ohne Konto, Vor- und Nachname wie geschrieben, Abteilung leer (Henrik Lorenz, Viktor Albrecht, Marta Albrecht, Aidan Novak, Ravi Mehta, Ben Hartung, Simon Albrecht, Jonas Albrecht, Arjun Sharma, Theo Albrecht). „Milan“ (nur ein Vorname, keine passende Person), „N.N.“ und „-“ → keine Person.

Erwartete Vorschau: 18 neu, 11 ergänzt, 0 Konflikt, 0 übersprungen. Danach gibt es 99 Geräte:

- 15 „In Benutzung“, alle „Altbestand ohne Protokoll“: die acht MateBooks, deren Person dieses Blatt ergänzt (F-85), und sieben neue Geräte mit Person.
- 84 „Auf Lager“, darunter Mac Studio und die beiden iPads, für die das Blatt keine Person nennt.
- Zeile 5 (Kommentar „Defect“) hat Zustand 4 und die Notiz aus F-85.
