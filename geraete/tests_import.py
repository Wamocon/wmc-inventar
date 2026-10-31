"""Test für den Import (A-0113, F-80 bis F-84, F-86)."""
from __future__ import annotations

import io
from datetime import date

from django.test import TestCase, Client
from django.urls import reverse

from konten.models import Konto
from stammdaten.models import Kategorie, Ort, Person

from . import import_parser
from .models import Gerat


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
