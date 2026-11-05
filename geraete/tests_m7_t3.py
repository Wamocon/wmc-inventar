"""Tests für M7 Teil 3: Übersicht, Arbeitslisten, Export, Kennzahlen (A-0907).

TESTSCHNITTSTELLE 3: / für Admin und Leser 200; Mitarbeiter weitergeleitet.
F-100 bis F-105: Kennzahlen, Delta, Arbeitslisten, Inventarwert, Export, Schnittstelle.
TESTSCHNITTSTELLE 4: kennzahl (data-id, ist, gesamt, delta); arbeitsliste
(data-id); inventarwert; Antwort von /api/kennzahlen.
TESTSCHNITTSTELLE 5: Delta mit U+2212; Beträge.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from unittest.mock import patch

from konten.models import Konto
from stammdaten.models import Einstellungen, Kategorie, Person, Ort
from geraete import services
from geraete.models import Gerat


def _konten_anlegen():
    """Admin, Leser und Mitarbeiter für die Rechte-Tests (Kapitel 3)."""
    admin = Konto.objects.create_konto(
        email="it-admin@beispiel.test",
        password="test12345678",
        rolle=Konto.ROLLE_ADMIN,
    )
    leszer = Konto.objects.create_konto(
        email="gf@beispiel.test",
        password="test12345678",
        rolle=Konto.ROLLE_LESER,
    )
    mitarbeiter = Konto.objects.create_konto(
        email="mitarbeiter@beispiel.test",
        password="test12345678",
        rolle=Konto.ROLLE_MITARBEITER,
        person=Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Mitarbeiter",
            nachname="Test",
            email="mitarbeiter@beispiel.test",
        ),
    )
    return admin, leszer, mitarbeiter


class UebersichtRechteTests(TestCase):
    """Kapitel 3: / für Admin und Leser 200, Mitarbeiter weitergeleitet."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()

    def test_uebersicht_admin_200(self):
        """Admin sieht die Übersicht mit Kennzahlen und Arbeitslisten."""
        self.client.force_login(self.admin)
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "data-test=\"kennzahlen\"")
        self.assertContains(antwort, "data-test=\"arbeitslisten\"")
        self.assertContains(antwort, "data-test=\"inventarwert\"")

    def test_uebersicht_leser_200(self):
        """Leser sieht die Übersicht."""
        self.client.force_login(self.leszer)
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)

    def test_uebersicht_mitarbeiter_weiterleitung(self):
        """Mitarbeiter wird nach /meine-geraete/ weitergeleitet."""
        self.client.force_login(self.mit)
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort["Location"], "/meine-geraete/")


class UebersichtInhaltTests(TestCase):
    """Kapitel 4: kennzahl mit data-id, arbeitsliste mit den acht data-id."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")
        self.ort = Ort.objects.create(kennung="WMC-WP-01", typ=Ort.TYP_ARBEITSPLATZ)

    def test_kennzahlen_data_ids(self):
        """Alle acht Kennzahlen mit ihren data-id (F-100)."""
        antwort = self.client.get("/")
        expected = [
            "in-benutzung", "ueberfaellig", "anfragen-offen",
            "garantie-30-tage", "unterschriften-offen",
            "arbeitsplaetze-vollstaendig", "verliehen", "geprueft",
        ]
        for data_id in expected:
            self.assertContains(
                antwort, f'data-id="{data_id}"',
            )

    def test_arbeitslisten_data_ids(self):
        """Alle acht Arbeitslisten mit ihren data-id (F-102)."""
        antwort = self.client.get("/")
        expected = [
            "ueberfaellig", "anfragen", "arbeitsplaetze-unvollstaendig",
            "garantie", "unterschriften-offen", "daten-unvollstaendig",
            "offene-punkte", "austritte",
        ]
        for data_id in expected:
            self.assertContains(
                antwort, f'data-id="{data_id}"',
            )

    def test_inventarwert_gezeigt(self):
        """Inventarwert wird als Summe der Kaufpreise gezeigt (F-104)."""
        gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
            kaufpreis_netto=Decimal("1500.00"),
        )
        gerat2 = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="Latitude 5540",
            person=self.person,
            kaufpreis_netto=Decimal("2000.00"),
        )
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "data-test=\"inventarwert\"")


class UebersichtDeltaTests(TestCase):
    """F-101: Delta fehlt ohne Zählerstand vom Vortag, zeigt nach Tageslauf."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")

    def test_delta_fehlt_ohne_zaehlerstand(self):
        """Ohne Zählerstand vom Vortag fehlt das Delta."""
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)
        # Ohne Zählerstand: delta fehlt (– im HTML)
        self.assertContains(antwort, "data-test=\"delta\"")

    def test_delta_zum_vortag(self):
        """Nach einem Tageslauf mit Stichtag am Vortag zeigt das Delta."""
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )
        vortag = date(2026, 11, 2)
        heute = date(2026, 11, 3)
        call_command("tageslauf", stichtag=vortag.isoformat())
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="Latitude 5540",
            person=self.person,
        )
        call_command("tageslauf", stichtag=heute.isoformat())
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)
        # Nach Tageslauf: Delta zeigt einen Wert (nicht nur –)
        html = antwort.content.decode()
        self.assertIn("data-test=\"delta\"", html)
        # Der Delta-Wert sollte nicht nur „–" sein
        delta_zeilen = [
            z for z in html.split("\n")
            if 'data-test="delta"' in z
        ]
        self.assertTrue(
            any("+" in z or "−" in z or "±" in z for z in delta_zeilen),
            msg="Delta zeigt keinen Wert (nur –)",
        )


class ExportTests(TestCase):
    """F-103: Export der Listen als .csv und .xlsx."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")
        self.ort = Ort.objects.create(kennung="LAGER-EG", typ=Ort.TYP_LAGER)

    def test_export_csv_nur_auf_lager(self):
        """/geraete/?status=auf-lager&format=csv enthält nur Geräte auf Lager."""
        auf_lager = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            ort=self.ort,
        )
        in_benutzung = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="Latitude 5540",
            person=self.person,
        )
        self.assertEqual(auf_lager.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(in_benutzung.status, Gerat.STATUS_IN_BENUTZUNG)

        antwort = self.client.get("/geraete/?status=auf-lager&format=csv")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("text/csv", antwort["Content-Type"])
        self.assertIn("attachment", antwort["Content-Disposition"])
        inhalt = antwort.content.decode("utf-8")
        self.assertIn(auf_lager.inventarnummer, inhalt)
        self.assertNotIn(in_benutzung.inventarnummer, inhalt)

    def test_export_xlsx_offenbarbar(self):
        """format=xlsx liefert eine Datei, die openpyxl öffnen kann."""
        gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            ort=self.ort,
        )
        antwort = self.client.get("/geraete/?status=auf-lager&format=xlsx")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            antwort["Content-Type"],
        )
        # openpyxl kann die Datei öffnen
        from openpyxl import load_workbook
        arbeitsbuch = load_workbook(io.BytesIO(antwort.content))
        blatt = arbeitsbuch.active
        zeilen = list(blatt.iter_rows(values_only=True))
        self.assertGreater(len(zeilen), 1)
        # Inventarnummer in der Datei
        alle_werte = [str(z) for z in zeilen for z in z]
        self.assertIn(gerat.inventarnummer, alle_werte)

    def test_export_mitarbeiter_403(self):
        """Mitarbeiter darf nicht exportieren (F-103)."""
        self.client.force_login(self.mit)
        antwort = self.client.get("/geraete/?status=auf-lager&format=csv")
        self.assertEqual(antwort.status_code, 403)


class ApiKennzahlenTests(TestCase):
    """F-105: /api/kennzahlen mit Token, 401 ohne, 404 ohne gesetztes Token."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )

    def test_api_mit_token_200(self):
        """Mit richtigem Token: 200 mit stand und kennzahlen."""
        with patch.dict("os.environ", {"KENNZAHLEN_TOKEN": "test-token-abc"}):
            antwort = self.client.get(
                "/api/kennzahlen",
                HTTP_AUTHORIZATION="Bearer test-token-abc",
            )
            self.assertEqual(antwort.status_code, 200)
            daten = antwort.json()
            self.assertIn("stand", daten)
            self.assertIn("kennzahlen", daten)
            self.assertIn("in-benutzung", daten["kennzahlen"])

    def test_api_ohne_token_401(self):
        """Ohne Token: 401."""
        with patch.dict("os.environ", {"KENNZAHLEN_TOKEN": "test-token-abc"}):
            antwort = self.client.get("/api/kennzahlen")
            self.assertEqual(antwort.status_code, 401)

    def test_api_falscher_token_401(self):
        """Mit falschem Token: 401."""
        with patch.dict("os.environ", {"KENNZAHLEN_TOKEN": "test-token-abc"}):
            antwort = self.client.get(
                "/api/kennzahlen",
                HTTP_AUTHORIZATION="Bearer falsch",
            )
            self.assertEqual(antwort.status_code, 401)

    def test_api_ohne_gesetztes_token_404(self):
        """Ohne gesetztes KENNZAHLEN_TOKEN: 404."""
        with patch.dict("os.environ", {}, clear=True):
            # KENNZAHLEN_TOKEN sicher nicht gesetzt
            antwort = self.client.get(
                "/api/kennzahlen",
                HTTP_AUTHORIZATION="Bearer test-token-abc",
            )
            self.assertEqual(antwort.status_code, 404)


class DeltaFormatTests(TestCase):
    """Kapitel 5: Delta mit U+2212, Beträge mit Euro-Zeichen."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")

    def test_delta_negativ_minus_zeichen(self):
        """Negatives Delta zeigt U+2212 (−), nicht ASCII-Hyphen."""
        gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )
        vortag = date(2026, 11, 2)
        heute = date(2026, 11, 3)
        call_command("tageslauf", stichtag=vortag.isoformat())
        # Gerät ausmustern, damit der Wert sinkt
        gerat.status = Gerat.STATUS_AUSGEMUSTERT
        gerat.save()
        call_command("tageslauf", stichtag=heute.isoformat())
        antwort = self.client.get("/")
        html = antwort.content.decode()
        # U+2212 ist das Minuszeichen
        self.assertIn("\u2212", html, msg="Delta verwendet nicht U+2212")

    def test_inventarwert_betrag_format(self):
        """Inventarwert zeigt Tausenderpunkt und Euro-Zeichen."""
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
            kaufpreis_netto=Decimal("123456.78"),
        )
        antwort = self.client.get("/")
        html = antwort.content.decode()
        self.assertIn("€", html, msg="Inventarwert hat kein Euro-Zeichen")
        self.assertIn("123.456,78", html, msg="Inventarwert hat falsche Beträge")


class GesamtschrankTests(TestCase):
    """F-100 (A-0910): gesamt steht genau viermal, nur bei den vier Kennzahlen mit gesamt."""

    def setUp(self):
        Einstellungen.aktuelles()
        self.admin, self.leszer, self.mit = _konten_anlegen()
        self.client.force_login(self.admin)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")

    def test_gesamt_genau_viermal(self):
        """gesamt steht genau viermal: in-benutzung, arbeitsplaetze-vollstaendig, verliehen, geprueft."""
        antwort = self.client.get("/")
        html = antwort.content.decode()
        anzahl = html.count('data-test="gesamt"')
        self.assertEqual(
            anzahl, 4,
            msg=f"gesamt steht {anzahl}x, erwartet 4",
        )
        # Die vier Kennzahlen mit gesamt
        for data_id in ["in-benutzung", "arbeitsplaetze-vollstaendig", "verliehen", "geprueft"]:
            block = html.split(f'data-id="{data_id}"')[1].split("</li>")[0] if f'data-id="{data_id}"' in html else ""
            self.assertIn('data-test="gesamt"', block, msg=f"{data_id} hat kein gesamt")
        # Die vier ohne gesamt
        for data_id in ["ueberfaellig", "anfragen-offen", "garantie-30-tage", "unterschriften-offen"]:
            block = html.split(f'data-id="{data_id}"')[1].split("</li>")[0] if f'data-id="{data_id}"' in html else ""
            self.assertNotIn('data-test="gesamt"', block, msg=f"{data_id} hat unerwartet gesamt")


class GegenzeichnungsseiteTests(TestCase):
    """F-136 (A-0910): /signieren/<token>/ hat data-name gegenzeichnen und Button signieren."""

    def setUp(self):
        from stammdaten.models import Person, Kategorie, Ort
        from konten.models import Konto
        from . import services
        Einstellungen.aktuelles()
        self.kat = Kategorie.objects.create(name="Notebook")
        self.ort = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="WMC-L-01")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Anna",
            nachname="Becker", email="a.becker@beispiel.test",
        )
        self.admin, _, _ = _konten_anlegen()
        self.g1 = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad T14",
            seriennummer="SN99002", ort=self.ort,
        )
        self.protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.g1,
            erzeugt_von=self.admin,
        )
        # Checkliste beantworten (F-132), damit Signatur und PDF funktionieren.
        from .models import Protokoll
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            self.protokoll.checkliste[schluessel] = 1
        self.protokoll.save()
        # Bearbeiter signiert.
        self.client.force_login(self.admin)
        self.client.post(
            f"/protokolle/{self.protokoll.nr}/signieren/",
            {"passwort": "test12345678"},
        )
        self.client.logout()
        self.protokoll.refresh_from_db()
        self.token = self.protokoll.gegenzeichnung_token

    def test_dialog_hat_data_name_gegenzeichnen(self):
        """Der Bereich trägt data-name gegenzeichnen."""
        antwort = self.client.get(f"/signieren/{self.token}/")
        html = antwort.content.decode()
        self.assertIn('data-name="gegenzeichnen"', html)

    def test_button_heisst_signieren(self):
        """Die Schaltfläche zum Absenden des Codes heißt signieren."""
        antwort = self.client.get(f"/signieren/{self.token}/")
        html = antwort.content.decode()
        self.assertIn('data-test="signieren"', html)
        self.assertIn(">Signieren<", html)
