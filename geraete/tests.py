"""Tests für die Geräte-App (M2 Bestand).

TESTSCHNITTSTELLE:
  - 1: INVENTAR_DEBUG=1, var/jetzt.txt
  - 5: data-wert, data-test, Anker in URLs
  - 6: Felder mit Namen, Pflichtfelder, Fehlertext
  - 7: Seitenpfade /geraete/ …
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase, Client
from django.urls import reverse

from konten.models import Konto
from stammdaten.models import Kategorie, Ort, Person

from . import services
from .models import Gerat, GeratKonflikt, Importlauf


# --- Konten-Helfer -----------------------------------------------------------

def konto_erstellen(username: str, rolle: str = "admin", email: str | None = None) -> Konto:
    email = email or f"{username}@wamocon.de"
    if rolle == "admin":
        rolle_wert = Konto.ROLLE_ADMIN
    elif rolle == "leser":
        rolle_wert = Konto.ROLLE_LESER
    else:
        rolle_wert = Konto.ROLLE_MITARBEITER
    konto = Konto(email=email, rolle=rolle_wert)
    konto.set_password("test-passwort-123")
    konto.save()
    return konto


def stammdaten_erstellen(kategorie_name: str = "Notebook", seriennummer_pflicht: bool = False,
                        ort_kennung: str = "WMC-L-01", person_email: str = "m.schulz@wamocon.de"):
    kat = Kategorie.objects.create(name=kategorie_name, seriennummer_pflicht=seriennummer_pflicht)
    ort = Ort.objects.create(typ=Ort.TYP_LAGER, kennung=ort_kennung)
    person = Person.objects.create(anrede=Person.ANREDE_FRAU, vorname="Miriam",
                                   nachname="Schulz", email=person_email)
    return kat, ort, person


# --- Modelle (TESTSCHNITTSTELLE 2: Namen der Felder) ---------------------------

class GeratModelTests(TestCase):
    def test_status_wert_gibt_data_wert(self):
        kat, ort, person = stammdaten_erstellen()
        g = services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="ThinkPad")
        self.assertEqual(g.status_wert(), "auf-lager")
        self.assertEqual(g.status_anzeige, "Auf Lager")

    def test_datenluecken_fehlende_angaben(self):
        kat, ort, person = stammdaten_erstellen(seriennummer_pflicht=True)
        g = services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="ThinkPad")
        luecken = set(g.datenluecken())
        self.assertIn("seriennummer", luecken)
        self.assertIn("kaufdatum", luecken)
        self.assertIn("verbleib", luecken)

    def test_unvollstaendig_bei_offenem_konflikt(self):
        kat, ort, person = stammdaten_erstellen()
        g = services.gerat_anlegen(
            kategorie=kat, hersteller="Lenovo", modell="ThinkPad",
            kaufdatum=date(2026, 1, 1), garantie_bis=date(2027, 1, 1), ort=ort,
        )
        self.assertFalse(g.ist_unvollstaendig())
        services.konflikt_anlegen(g, "zustand", "2", "3", "bestandsliste.xlsx, Blatt 1, Zeile 4")
        self.assertTrue(g.ist_unvollstaendig())
        konflikt = g.konflikte.first()
        services.konflikt_loesen(konflikt, "alt")
        self.assertFalse(g.ist_unvollstaendig())

    def test_doppelte_namen_hinweis(self):
        kat, ort, person = stammdaten_erstellen()
        g1 = services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="T14", geraetename="Pool-A")
        g2 = services.gerat_anlegen(kategorie=kat, hersteller="HP", modell="EliteBook", geraetename="pool-a")
        self.assertIn(g1, g2.doppelte_namen())
        self.assertIn(g2, g1.doppelte_namen())

    def test_importlauf_nachvollziehbar(self):
        kat, ort, person = stammdaten_erstellen()
        konto = konto_erstellen("max.admin")
        lauf = Importlauf.objects.create(
            dateiname="bestandsliste.xlsx", blatt="Blatt 1", anzahl_neu=3,
            erzeugt_von=konto,
        )
        self.assertEqual(str(lauf), "bestandsliste.xlsx (Blatt 1)")
        self.assertIsNotNone(lauf.erzeugt_von)


# --- Service: Inventarnummer (O-03) --------------------------------------------

class InventarnummerTests(TestCase):
    def test_automatisch_fortlaufend_format_wmc(self):
        kat, ort, person = stammdaten_erstellen()
        g1 = services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="T14")
        g2 = services.gerat_anlegen(kategorie=kat, hersteller="HP", modell="EliteBook")
        self.assertRegex(g1.inventarnummer, r"^WMC-\d{5}$")
        self.assertRegex(g2.inventarnummer, r"^WMC-\d{5}$")
        self.assertNotEqual(g1.inventarnummer, g2.inventarnummer)

    def test_inventarnummer_nicht_aenderbar(self):
        kat, ort, person = stammdaten_erstellen()
        g = services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="T14")
        alt = g.inventarnummer
        services.gerat_bearbeiten(g, werte={"hersteller": "HP"})
        g.refresh_from_db()
        self.assertEqual(g.inventarnummer, alt)


# --- Service: Anlegen, Bearbeiten, Prüfung (F-11 bis F-16) -----------------------

class VorgangTests(TestCase):
    def setUp(self):
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.konto = konto_erstellen("max.admin")

    def test_anlegen_ohne_seriennummer_klappt_ohne_pflicht(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.assertEqual(g.status, Gerat.STATUS_AUF_LAGER)

    def test_anlegen_mit_person_wird_in_benutzung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14",
                                   person=self.person)
        self.assertEqual(g.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(g.person, self.person)

    def test_person_und_ort_zugleich_abgelehnt(self):
        with self.assertRaises(services.GeratFehler):
            services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14",
                                   person=self.person, ort=self.ort)

    def test_bearbeiten_fremdes_feld_abgelehnt(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        with self.assertRaises(services.GeratFehler):
            services.gerat_bearbeiten(g, werte={"inventarnummer": "XYZ"})

    def test_bearbeiten_gultige_felder(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_bearbeiten(g, werte={"hersteller": "HP", "geraetename": "Pool-B"})
        g.refresh_from_db()
        self.assertEqual(g.hersteller, "HP")
        self.assertEqual(g.geraetename, "Pool-B")

    def test_pruefung_datum_und_kontext(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_pruefen(g, self.konto)
        g.refresh_from_db()
        self.assertIsNotNone(g.zuletzt_geprueft_am)
        self.assertEqual(g.zuletzt_geprueft_von, self.konto)

    def test_konflikt_loesen_neu_uebernimmt_wert(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.konflikt_anlegen(g, "zustand", "2", "3", "datei.xlsx, Zeile 2")
        k = g.konflikte.first()
        services.konflikt_loesen(k, "neu")
        g.refresh_from_db()
        k.refresh_from_db()
        self.assertEqual(g.zustand, 3)
        self.assertFalse(k.offen)


# --- Ansichten (TESTSCHNITTSTELLE 5 und 6) ---------------------------------------

class AnsichtsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.kat = Kategorie.objects.create(name="Notebook")
        self.kat_pflicht = Kategorie.objects.create(name="Datenträger", seriennummer_pflicht=True)
        self.ort = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="WMC-L-01")
        self.person = Person.objects.create(anrede=Person.ANREDE_FRAU, vorname="Miriam",
                                           nachname="Schulz", email="m.schulz@wamocon.de")
        self.g1 = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14",
            geraetename="Pool-A", ort=self.ort,
            kaufdatum=date(2026, 1, 1), garantie_bis=date(2027, 1, 1),
        )
        self.g2 = services.gerat_anlegen(kategorie=self.kat, hersteller="HP", modell="EliteBook 840")
        self.konto = konto_erstellen("max.admin")
        self.client.login(username="max.admin@wamocon.de", password="test-passwort-123")

    def test_liste_zeigt_alle_geraete_ascending(self):
        antwort = self.client.get("/geraete/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn(self.g1.inventarnummer, text)
        self.assertIn(self.g2.inventarnummer, text)
        self.assertIn('data-test="geraete-liste"', text)
        pos1 = text.index(self.g1.inventarnummer)
        pos2 = text.index(self.g2.inventarnummer)
        self.assertLess(pos1, pos2, "Standard aufsteigend nach Inventarnummer (F-41)")

    def test_liste_filter_status(self):
        antwort = self.client.get("/geraete/?status=on-lager".replace("on-lager", "auf-lager"))
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn(self.g1.inventarnummer, text)

    def test_liste_filter_ort(self):
        antwort = self.client.get(f"/geraete/?ort={self.ort.pk}")
        text = antwort.content.decode()
        self.assertIn(self.g1.inventarnummer, text)
        self.assertNotIn(self.g2.inventarnummer, text)

    def test_liste_suche_nach_name(self):
        antwort = self.client.get("/geraete/?q=pool-a")
        text = antwort.content.decode()
        self.assertIn(self.g1.inventarnummer, text)

    def test_liste_suche_nach_seriennummer(self):
        services.gerat_bearbeiten(self.g1, werte={"seriennummer": "SN-12345"})
        antwort = self.client.get("/geraete/?q=SN-12345")
        text = antwort.content.decode()
        self.assertIn(self.g1.inventarnummer, text)

    def test_detail_zeigt_alte_werte_und_pruefung(self):
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="hersteller"', text)
        self.assertIn("Lenovo", text)
        self.assertIn('data-test="pruefen"', text)

    def test_pruefen_aktualisiert_datum(self):
        antwort = self.client.post(f"/geraete/{self.g1.inventarnummer}/pruefen/")
        self.assertEqual(antwort.status_code, 302)
        self.g1.refresh_from_db()
        self.assertIsNotNone(self.g1.zuletzt_geprueft_am)
        self.assertEqual(self.g1.zuletzt_geprueft_von, self.konto)

    def test_aendern_zurueck_zu_detail(self):
        antwort = self.client.post(
            f"/geraete/{self.g1.inventarnummer}/aendern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "HP",
                "modell": "EliteBook 840",
                "seriennummer": "",
                "zustand": 2,
                "person": "",
                "ort": self.ort.pk,
                "geraetename": "Pool-B",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.hersteller, "HP")
        self.assertEqual(self.g1.geraetename, "Pool-B")

    def test_konflikt_loesen_neu(self):
        services.konflikt_anlegen(self.g1, "zustand", "2", "3", "datei.xlsx, Zeile 2")
        k = self.g1.konflikte.first()
        antwort = self.client.post(
            f"/geraete/{self.g1.inventarnummer}/konflikt/{k.pk}/loesen/",
            {"nehmen": "neu"},
        )
        self.assertEqual(antwort.status_code, 302)
        self.g1.refresh_from_db()
        k.refresh_from_db()
        self.assertEqual(self.g1.zustand, 3)
        self.assertFalse(k.offen)

    def test_neu_anlegen_mit_seriennummer_pflicht(self):
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat_pflicht.pk,
                "hersteller": "Kingston",
                "modell": "SA400",
                "seriennummer": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn("Diese Kategorie verlangt eine Seriennummer.", text)
        self.assertEqual(Gerat.objects.filter(hersteller="Kingston").count(), 0)

    def test_neu_anlegen_klappt(self):
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Kingston",
                "modell": "SA400",
                "seriennummer": "SN-999",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        g = Gerat.objects.get(hersteller="Kingston")
        self.assertRegex(g.inventarnummer, r"^WMC-\d{5}$")

    def test_arbeitsliste_zeigt_unvollstaendige(self):
        g_leer = services.gerat_anlegen(kategorie=self.kat, hersteller="Dell", modell="OptiPlex")
        antwort = self.client.get("/geraete/?unvollstaendig=1")
        text = antwort.content.decode()
        self.assertIn(g_leer.inventarnummer, text)
        self.assertNotIn(self.g1.inventarnummer, text, "Gerät mit Ort ist vollständig.")

    def test_leser_kann_nicht_anlegen(self):
        konto_erstellen("leser.k", rolle="leser")
        self.client.logout()
        self.client.login(username="leser.k@wamocon.de", password="test-passwort-123")
        antwort = self.client.get("/geraete/neu/")
        self.assertEqual(antwort.status_code, 302)
        self.assertNotIn("/geraete/neu/", antwort["Location"])

    def test_leser_kann_nicht_bearbeiten(self):
        konto_erstellen("leser.k", rolle="leser")
        self.client.logout()
        self.client.login(username="leser.k@wamocon.de", password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/aendern/")
        self.assertEqual(antwort.status_code, 302)


class OhneDebugTests(TestCase):
    """TESTSCHNITTSTELLE 1: INVENTAR_DEBUG=0 – ohne Entwicklungsmeldungen."""

    def test_liste_ohne_debug(self):
        kat = Kategorie.objects.create(name="Notebook")
        konto_erstellen("max.admin")
        services.gerat_anlegen(kategorie=kat, hersteller="Lenovo", modell="T14")
        client = Client()
        client.login(username="max.admin@wamocon.de", password="test-passwort-123")
        antwort = client.get("/geraete/")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("WMC-", antwort.content.decode())
