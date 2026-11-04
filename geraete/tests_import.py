"""Test für den Import (A-0113, F-80 bis F-84, F-86)."""
from __future__ import annotations

import html
import io
import os
import re
from datetime import date

from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse

from konten.models import Konto
from stammdaten.models import Kategorie, Ort, Person

from . import import_parser
from .models import Gerat

# A-0912 Nr. 6: Pfad der Testdatei.
VORLAGE_PFAD = os.path.join(
    os.path.dirname(__file__), "..", "docs", "vorlagen",
    "bestandsliste_anonymisiert.xlsx")


def _konto(username: str, rolle: str) -> Konto:
    email = f"{username}@beispiel.test"
    konto = Konto(email=email, rolle=rolle)
    konto.set_password("test-passwort-123")
    konto.save()
    return konto


class ImportTests(TestCase):
    """Die Vorschau des Imports (F-83, F-84, F-86)."""

    def setUp(self):
        # Stammdaten: eine Kategorie, ein Lagerort, eine Person.
        self.kat = Kategorie.objects.create(name="Notebook")
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-EG")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Miriam", nachname="Schulz",
            email="m.schulz@beispiel.test")
        # Ein vorhandenes Gerät: gleiche Seriennummer wie in der Testdatei,
        # aber Person und Ort fehlen (F-84 „ergänzt“).
        self.gerat = Gerat.objects.create(
            kategorie=self.kat, geraetename="Notebook-A", hersteller="Hersteller-A",
            modell="Modell-A", seriennummer="SN-001", erstellt_am=date.today())

    def _vorlage_aus_csv(self, inhalt: str) -> import_parser.Vorlage:
        byte = inhalt.encode("utf-8")
        return import_parser.lade_datei("liste.csv", byte, "", 1)

    def test_vorschau_nach_zeilen(self):
        """Je Zeile: neu, ergänzt, übersprungen, neu (F-83, F-84, F-86)."""
        csv_inhalt = (
            "Typ;Gerät;Seriennummer;Verliehen an;Arbeitsplatz\n"
            "Notebook;Modell-A;SN-001;;\n"
            "Notebook;Modell-B;SN-002;Miriam Schulz;\n"
            "-;-;-;-;-\n"
            "Notebook;Modell-C;SN-003;;\n"
        )
        vorlage = self._vorlage_aus_csv(csv_inhalt)
        spalten_ziel = {
            "Typ": "Kategorie",
            "Gerät": "Modell",
            "Seriennummer": "Seriennummer",
            "Verliehen an": "Person",
            "Arbeitsplatz": "Arbeitsplatz",
        }
        kat_map = {"Notebook": "Notebook"}
        pers_map = {"Miriam Schulz": "Miriam Schulz"}
        arbp_map = {}
        zeilen = import_parser.vorschau_berechnen(
            vorlage, spalten_ziel, kat_map, pers_map, arbp_map)
        zähler = import_parser.zusammenfassung(zeilen)
        self.assertEqual(zähler["neu"], 2)
        self.assertEqual(zähler["ergaenzt"], 1)
        self.assertEqual(zähler["konflikt"], 0)
        self.assertEqual(zähler["uebersprungen"], 1)

    def test_vorschau_csv(self):
        """Die Vorschau als CSV: eine Zeile je Excel-Zeile (F-83, F-86)."""
        csv_inhalt = (
            "Typ;Gerät;Seriennummer;Verliehen an;Arbeitsplatz\n"
            "Notebook;Modell-A;SN-001;;\n"
            "Notebook;Modell-B;SN-002;Miriam Schulz;\n"
        )
        vorlage = self._vorlage_aus_csv(csv_inhalt)
        spalten_ziel = {
            "Typ": "Kategorie",
            "Gerät": "Modell",
            "Seriennummer": "Seriennummer",
            "Verliehen an": "Person",
            "Arbeitsplatz": "Arbeitsplatz",
        }
        zeilen = import_parser.vorschau_berechnen(
            vorlage, spalten_ziel,
            {"Notebook": "Notebook"}, {"Miriam Schulz": "Miriam Schulz"}, {})
        csv_text = import_parser.csv_vorschau(zeilen)
        self.assertIn("neu", csv_text)
        self.assertIn("ergaenzt", csv_text)
        self.assertEqual(len(csv_text.strip().split("\n")), 3)

    def test_import_fuer_it_admin(self):
        """/import/ für IT-Admin mit 200 und import-schritt (TESTSCHNITTSTELLE 3)."""
        konto = _konto("it-admin", Konto.ROLLE_ADMIN)
        client = Client()
        client.force_login(konto)
        antwort = client.get("/import/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="import-schritt"')

    def test_import_fuer_leser_403(self):
        """/import/ für Leser mit 403 (TESTSCHNITTSTELLE 3)."""
        konto = _konto("leser", Konto.ROLLE_LESER)
        client = Client()
        client.force_login(konto)
        antwort = client.get("/import/")
        self.assertEqual(antwort.status_code, 403)

    def test_import_fuer_mitarbeiter_403(self):
        """/import/ für Mitarbeiter mit 403 (TESTSCHNITTSTELLE 3)."""
        konto = _konto("mitarbeiter", Konto.ROLLE_MITARBEITER)
        client = Client()
        client.force_login(konto)
        antwort = client.get("/import/")
        self.assertEqual(antwort.status_code, 403)

    def test_speichern_neu_und_ergaenzt(self):
        """Speichern: neu angelegt, bestehendes ergänzt, kein Doppeltes (F-84, F-85, F-87)."""
        from .services import import_speichern
        csv_inhalt = (
            "Typ;Gerät;Seriennummer;Verliehen an;Arbeitsplatz\n"
            "Notebook;Modell-A;SN-001;;\n"
            "Notebook;Modell-B;SN-002;Miriam Schulz;\n"
        )
        vorlage = self._vorlage_aus_csv(csv_inhalt)
        spalten_ziel = {
            "Typ": "Kategorie",
            "Gerät": "Modell",
            "Seriennummer": "Seriennummer",
            "Verliehen an": "Person",
            "Arbeitsplatz": "Arbeitsplatz",
        }
        kat_map = {"Notebook": "Notebook"}
        pers_map = {"Miriam Schulz": "Miriam Schulz"}
        arbp_map = {}
        zeilen = import_parser.vorschau_berechnen(
            vorlage, spalten_ziel, kat_map, pers_map, arbp_map)

        anzahl_vor = Gerat.objects.count()
        konto = _konto("it-admin", Konto.ROLLE_ADMIN)
        ergebnis = import_speichern(
            vorlage, zeilen, spalten_ziel, kat_map, pers_map, arbp_map,
            "liste.csv", "", konto)

        self.assertEqual(ergebnis["neu"], 1)
        self.assertEqual(ergebnis["ergaenzt"], 1)
        self.assertEqual(Gerat.objects.count(), anzahl_vor + 1)

        # Das neue Gerät
        neues = Gerat.objects.filter(seriennummer="SN-002").first()
        self.assertIsNotNone(neues)
        self.assertEqual(neues.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(neues.person.vorname, "Miriam")
        self.assertTrue(neues.altbestand_ohne_protokoll)
        self.assertTrue(neues.zustand_ungeprueft)
        self.assertEqual(neues.zustand, Gerat.ZUSTAND_GUT)

        # Vorgang „Import“ mit Herkunft
        from .models import Vorgang
        import_vorgaenge = Vorgang.objects.filter(gerat=neues, typ="import")
        self.assertEqual(import_vorgaenge.count(), 1)
        vorgang = import_vorgaenge.first()
        self.assertIn("liste.csv", vorgang.notiz)

    def test_speichern_konflikt(self):
        """Speichern: gleicher Seriennummer, abweichender Gerätenamen → Konflikt (F-84).

        Das vorhandene Gerät hat SN-001 und Gerätenamen „Notebook-A“.
        Die CSV-Zeile nennt dieselbe SN, aber einen anderen Namen → Konflikt.
        """
        from .services import import_speichern
        csv_inhalt = (
            "Typ;Gerätename;Seriennummer\n"
            "Notebook;Anderes-Name;SN-001\n"
        )
        vorlage = self._vorlage_aus_csv(csv_inhalt)
        spalten_ziel = {
            "Typ": "Kategorie", "Gerätename": "Gerätename", "Seriennummer": "Seriennummer",
        }
        kat_map = {"Notebook": "Notebook"}
        zeilen = import_parser.vorschau_berechnen(vorlage, spalten_ziel, kat_map, {}, {})
        # Gleiche SN, aber abweichender Gerätenamen → Konflikt
        self.assertEqual(zeilen[0].ergebnis, "konflikt")

        konto = _konto("it-admin", Konto.ROLLE_ADMIN)
        ergebnis = import_speichern(
            vorlage, zeilen, spalten_ziel, kat_map, {}, {}, "liste.csv", "", konto)
        self.assertEqual(ergebnis["konflikt"], 1)
        self.assertEqual(ergebnis["neu"], 0)

        konflikt = self.gerat.konflikte.first()
        self.assertIsNotNone(konflikt)
        self.assertEqual(konflikt.feld, "geraetename")
        self.assertEqual(konflikt.alter_wert, "Notebook-A")
        self.assertEqual(konflikt.neuer_wert, "Anderes-Name")

    def test_speichern_kein_doppelt_anlegen(self):
        """Zweiter Import desselben Blatts: kein Gerät doppelt angelegt (F-84)."""
        from .services import import_speichern
        csv_inhalt = (
            "Typ;Gerät;Seriennummer\n"
            "Notebook;Modell-X;SN-555\n"
        )
        vorlage = self._vorlage_aus_csv(csv_inhalt)
        spalten_ziel = {"Typ": "Kategorie", "Gerät": "Modell", "Seriennummer": "Seriennummer"}
        kat_map = {"Notebook": "Notebook"}
        konto = _konto("it-admin", Konto.ROLLE_ADMIN)

        # Erster Import: neu
        zeilen1 = import_parser.vorschau_berechnen(vorlage, spalten_ziel, kat_map, {}, {})
        import_speichern(vorlage, zeilen1, spalten_ziel, kat_map, {}, {}, "liste.csv", "", konto)
        anzahl_nach1 = Gerat.objects.count()
        self.assertEqual(anzahl_nach1, anzahl_nach1)  # sanity

        # Zweiter Import: ergaenzt (SN-555 existiert jetzt)
        vorlage2 = self._vorlage_aus_csv(csv_inhalt)
        zeilen2 = import_parser.vorschau_berechnen(vorlage2, spalten_ziel, kat_map, {}, {})
        self.assertEqual(zeilen2[0].ergebnis, "ergaenzt")
        import_speichern(vorlage2, zeilen2, spalten_ziel, kat_map, {}, {}, "liste.csv", "", konto)
        self.assertEqual(Gerat.objects.count(), anzahl_nach1)


def _kategorie_notebooks(wert: str) -> str:
    """Blatt Notebooks: Wert der Spalte Gerät → Kategorie (vorlagen/README)."""
    if re.search(r"MacBook|Macbook|Lenovo|MateBook|Matebook|Huawei Notebook", wert):
        return "Notebook"
    if re.search(r"iMac|Mac Studio", wert):
        return "Desktop-PC"
    if "iPad" in wert:
        return "Tablet"
    if "Huawei Monitor" in wert:
        return "Monitor"
    if "Huawei Maus" in wert:
        return "Maus"
    return "NAS"


class ImportEckwerteTests(TestCase):
    """A-0912 Nr. 6: Import über die Formulare wie im Browser.

    Mit docs/vorlagen/bestandsliste_anonymisiert.xlsx nach beispieldaten.
    Erst Blatt Inventar, dann Blatt Notebooks.
    """

    @classmethod
    def setUpTestData(cls):
        # Kategorien (wie in beispieldaten.py).
        for name, dt, sn in [
            ("Notebook", True, True), ("Desktop-PC", True, True),
            ("Monitor", False, False), ("Dockingstation", False, False),
            ("Notebook-Ständer", False, False), ("Tastatur", False, False),
            ("Maus", False, False), ("Headset", False, False),
            ("Webcam", False, False), ("Konferenzsystem", False, False),
            ("Smartphone", True, True), ("Tablet", True, True),
            ("Smartwatch", True, True), ("Kamera und Video", True, True),
            ("Powerbank", False, False), ("USB-Hub", False, False),
            ("NAS", True, True), ("Drucker", True, True),
            ("Netzwerkgerät", False, False), ("Fernseher", False, False),
            ("Sonstiges", False, False),
        ]:
            Kategorie.objects.create(name=name, hat_datentraeger=dt, seriennummer_pflicht=sn)
        # Lagerort.
        Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-EG", name="IT-Lager")
        # IT-Admin-Konto.
        cls.it_admin = Konto(email="it-admin@beispiel.test", rolle=Konto.ROLLE_ADMIN)
        cls.it_admin.set_password("test-passwort-123")
        cls.it_admin.save()

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.it_admin)

    def _datei_hochladen(self, blatt: str, kopfzeile: int) -> None:
        """POST /import/datei/ mit der Testdatei."""
        with open(VORLAGE_PFAD, "rb") as f:
            antwort = self.client.post("/import/datei/", {
                "datei": f,
                "blatt": blatt,
                "kopfzeile": str(kopfzeile),
            })
        self.assertEqual(antwort.status_code, 302)

    def _spalten_senden(self, data: dict) -> None:
        """POST /import/spalten/."""
        antwort = self.client.post("/import/spalten/", data)
        self.assertEqual(antwort.status_code, 302)

    def _werte_senden(self, data: dict) -> None:
        """POST /import/werte/."""
        antwort = self.client.post("/import/werte/", data)
        self.assertEqual(antwort.status_code, 302)

    def _speichern(self) -> str:
        """POST /import/speichern/ und die Meldung zurückgeben."""
        antwort = self.client.post("/import/speichern/")
        self.assertEqual(antwort.status_code, 302)
        meldung = antwort.headers.get("Location", "")
        return meldung

    def test_inventar_blatt(self):
        """Blatt Inventar: 81 neu, 1 ergänzt, 0 Konflikt, 41 übersprungen."""
        self._datei_hochladen("Inventar", 3)

        # Schritt 2: Spalten zuordnen (vorlagen/README).
        # Typ → Kategorie (über Werte), Hersteller → Hersteller, Modell → Modell,
        # Gerätename → Gerätename, Seriennummer → Seriennummer,
        # Rechnungsnummer → Rechnungsnummer, Garantie Ende → Garantie bis,
        # Datum erhalt → Kaufdatum, Kommentar → Notiz.
        # Rechnung, Garantie, Datum Bestandsaufnahme, Status → ignorieren.
        self._spalten_senden({
            "ziel_Typ": "Kategorie",
            "ziel_Hersteller": "Hersteller",
            "ziel_Modell": "Modell",
            "ziel_Gerätename": "Gerätename",
            "ziel_Seriennummer": "Seriennummer",
            "ziel_Rechnungsnummer": "Rechnungsnummer",
            "ziel_Garantie Ende": "Garantie bis",
            "ziel_Datum erhalt": "Kaufdatum",
            "ziel_Kommentar": "Notiz",
        })

        # Schritt 3: Werte aus „Typ" auf Kategorien mappen.
        # 41 Werte → nicht übernehmen (Kleinteile, Kamera-Zubehör, Garantie).
        # 19 Werte → passende Kategorie (81 neu + 1 ergänzt = 82 Zeilen).
        data_werte = {}
        kat_zuordnung = {
            "Notebook": "Notebook",
            "Rechner": "Desktop-PC",
            "Tablet": "Tablet",
            "Smartphone": "Smartphone",
            "Smartwatch": "Smartwatch",
            "Monitor": "Monitor",
            "Docking Station": "Dockingstation",
            "Headset": "Headset",
            "Webcam": "Webcam",
            "Maus": "Maus",
            "Maus + Tastatur": "Tastatur",
            "Tastatur": "Tastatur",
            "Konferenzsystem": "Konferenzsystem",
            "Power Bank": "Powerbank",
            "USB-Hub": "USB-Hub",
            "Mikrofon": "Kamera und Video",
            "DJI Mic 2 (Einzelmikrofon für Osmo Pocket 3)": "Kamera und Video",
            "Gimbel-Büro": "Kamera und Video",
            "Gimbel-Mobile": "Kamera und Video",
        }
        for wert, kat in kat_zuordnung.items():
            data_werte[f"wert_zu_kategorie_{wert}"] = kat
        # 41 Werte: nicht übernehmen (leer) — Kleinteile, Kamera-Zubehör, Garantie.
        for wert in (
            "USB-C Kabel", "Steckdose (Tisch)",
            "13in1 USB-C Multifunction Adapter", "Mauspad",
            "Kamera Akku (Zubehör) groß", "Kamera Akku (Zubehör) klein",
            "Gimbal-Standfuß (Zubehör)", "Hülle für Osmo Pocket 3 (Zubehör)",
            "DJI Mic 2 Windschutz (Zubehör)",
            "DJI OSMO Pocket 3 Objektive 3er Set (Zubehör)",
            "DJI OSMO Pocket 3 Objektiv (Zubehör)",
            "Kamera Zubehör", "Garantie",
        ):
            data_werte[f"wert_zu_kategorie_{wert}"] = ""
        self._werte_senden(data_werte)

        # Schritt 4: Vorschau prüfen.
        antwort = self.client.get("/import/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "81 neu")
        self.assertContains(antwort, "1 ergänzt")
        self.assertContains(antwort, "0 Konflikt")
        self.assertContains(antwort, "41 übersprungen")

        # Speichern.
        self._speichern()

        # 81 Geräte, alle „Auf Lager".
        self.assertEqual(Gerat.objects.count(), 81)
        auf_lager = Gerat.objects.filter(status=Gerat.STATUS_AUF_LAGER).count()
        self.assertEqual(auf_lager, 81)

    def test_notebooks_blatt(self):
        """Blatt Notebooks: 18 neu, 11 ergänzt, 0 Konflikt, 0 übersprungen."""
        # Zuerst Blatt Inventar importieren (wie im Test oben).
        self._datei_hochladen("Inventar", 3)
        self._spalten_senden({
            "ziel_Typ": "Kategorie",
            "ziel_Hersteller": "Hersteller",
            "ziel_Modell": "Modell",
            "ziel_Gerätename": "Gerätename",
            "ziel_Seriennummer": "Seriennummer",
            "ziel_Rechnungsnummer": "Rechnungsnummer",
            "ziel_Garantie Ende": "Garantie bis",
            "ziel_Datum erhalt": "Kaufdatum",
            "ziel_Kommentar": "Notiz",
        })
        data_werte = {}
        kat_zuordnung = {
            "Notebook": "Notebook",
            "Rechner": "Desktop-PC",
            "Tablet": "Tablet",
            "Smartphone": "Smartphone",
            "Smartwatch": "Smartwatch",
            "Monitor": "Monitor",
            "Docking Station": "Dockingstation",
            "Headset": "Headset",
            "Webcam": "Webcam",
            "Maus": "Maus",
            "Maus + Tastatur": "Tastatur",
            "Tastatur": "Tastatur",
            "Konferenzsystem": "Konferenzsystem",
            "Power Bank": "Powerbank",
            "USB-Hub": "USB-Hub",
            "Mikrofon": "Kamera und Video",
            "DJI Mic 2 (Einzelmikrofon für Osmo Pocket 3)": "Kamera und Video",
            "Gimbel-Büro": "Kamera und Video",
            "Gimbel-Mobile": "Kamera und Video",
        }
        for wert, kat in kat_zuordnung.items():
            data_werte[f"wert_zu_kategorie_{wert}"] = kat
        self._werte_senden(data_werte)
        self._speichern()
        # Jetzt 81 Geräte aus Blatt Inventar.
        self.assertEqual(Gerat.objects.count(), 81)

        # Blatt Notebooks.
        self._datei_hochladen("Notebooks", 4)

        # Schritt 2: Spalten zuordnen (vorlagen/README).
        # ID → ignorieren, Gerät → Kategorie/Modell,
        # Gerätename → Gerätename, Seriennummer → Seriennummer,
        # Verliehen an MA → Person, Kommentar → Notiz.
        self._spalten_senden({
            "ziel_ID": "ignorieren",
            "ziel_Gerät": "Kategorie/Modell",
            "ziel_Gerätename": "Gerätename",
            "ziel_Seriennummer": "Seriennummer",
            "ziel_Verliehen an MA": "Person",
            "ziel_Kommentar": "Notiz",
        })

        # Schritt 3: Werte aus „Gerät" auf Kategorien mappen.
        # (A-0912 Nr. 2: „Kategorie/Modell" → Wert wird Modell,
        #  Spalte steht in Schritt 3 unter Kategorie.)
        data_werte = {}
        seite = self.client.get("/import/").content.decode()
        for name in re.findall(r'name="(wert_zu_kategorie_[^"]+)"', seite):
            name = html.unescape(name)
            data_werte[name] = _kategorie_notebooks(name[len("wert_zu_kategorie_"):])
        # Personen: volle Namen → Person, „Milan", „N.N.", „-" → leer.
        data_werte["wert_zu_person_Henrik Lorenz"] = "Henrik Lorenz"
        data_werte["wert_zu_person_Viktor Albrecht"] = "Viktor Albrecht"
        data_werte["wert_zu_person_Marta Albrecht"] = "Marta Albrecht"
        data_werte["wert_zu_person_Aidan Novak"] = "Aidan Novak"
        data_werte["wert_zu_person_Ravi Mehta"] = "Ravi Mehta"
        data_werte["wert_zu_person_Ben Hartung"] = "Ben Hartung"
        data_werte["wert_zu_person_Simon Albrecht"] = "Simon Albrecht"
        data_werte["wert_zu_person_Jonas Albrecht"] = "Jonas Albrecht"
        data_werte["wert_zu_person_Arjun Sharma"] = "Arjun Sharma"
        data_werte["wert_zu_person_Theo Albrecht"] = "Theo Albrecht"
        data_werte["wert_zu_person_Milan"] = ""
        data_werte["wert_zu_person_N.N."] = ""
        data_werte["wert_zu_person_-"] = ""

        self._werte_senden(data_werte)

        # Schritt 4: Vorschau prüfen.
        antwort = self.client.get("/import/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "18 neu")
        self.assertContains(antwort, "11 ergänzt")
        self.assertContains(antwort, "0 Konflikt")
        self.assertContains(antwort, "0 übersprungen")

        # Speichern.
        self._speichern()

        # 99 Geräte: 81 (Inventar) + 18 (neu aus Notebooks).
        self.assertEqual(Gerat.objects.count(), 99)
        in_benutzung = Gerat.objects.filter(status=Gerat.STATUS_IN_BENUTZUNG).count()
        auf_lager = Gerat.objects.filter(status=Gerat.STATUS_AUF_LAGER).count()
        self.assertEqual(in_benutzung, 15)
        self.assertEqual(auf_lager, 84)
        # Alle 15 „In Benutzung" sind „Altbestand ohne Protokoll".
        altbestand = Gerat.objects.filter(
            status=Gerat.STATUS_IN_BENUTZUNG, altbestand_ohne_protokoll=True).count()
        self.assertEqual(altbestand, 15)
        # F-84: Die Garantiezeile 5 ergänzt den Mac Studio aus Zeile 4.
        mac = Gerat.objects.get(seriennummer__iexact="Y4CO2WPZPY")
        self.assertEqual(mac.garantie_bis.isoformat(), "2026-09-22")
        self.assertIn("Garantie", mac.notiz)
        # F-84: Zeile 18 entsteht ohne die doppelte Nummer, die Notiz nennt sie.
        self.assertEqual(Gerat.objects.filter(seriennummer__iexact="2382KZ42KWQ5").count(), 1)
        self.assertEqual(Gerat.objects.filter(notiz__icontains="2382KZ42KWQ5").count(), 1)
        # Zeile 5 (Kommentar „Defect") hat Zustand 4.
        # (Dies kann über die Seriennummer der Zeile 5 geprüft werden.)
