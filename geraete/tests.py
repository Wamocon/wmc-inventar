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
from .models import Gerat, GeratKonflikt, Importlauf, Vorgang


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


# --- M3 Lebenszyklus (Kapitel 4, F-50 bis F-58) ---------------------------------

class M3LebenszyklusTests(TestCase):
    """Alle Übergänge aus Kapitel 4, jeder mit Test, auch die verbotenen (AUFTRAG M3)."""

    def setUp(self):
        self.admin = konto_erstellen("m3.admin")
        self.kat = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        self.ort = Ort.objects.create(
            typ=Ort.TYP_LAGER, kennung="M3-LAG", name="M3-Lager"
        )
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14",
            seriennummer="SN-M3-001", erzeugt_von=self.admin,
        )

    # --- F-20 bis F-23: Ausgabe ---------------------------------------------------

    def test_ausgabe_an_person(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(self.gerat.person, self.person)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertEqual(v.typ, Vorgang.TYP_AUSGABE)
        self.assertTrue(v.abschliesst)

    def test_ausgabe_an_ort(self):
        services.gerat_ausgeben(self.gerat, self.ort, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(self.gerat.ort, self.ort)

    def test_ausgabe_verweigert_aus_ausgemustert(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Schrotten", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)

    def test_ausgabe_verweigert_aus_reparatur(self):
        services.gerat_in_reparatur_geschickt(
            self.gerat, dienstleister="FixIT", vorgangsnummer="VR-001",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)

    # --- F-50: Rückgabe ----------------------------------------------------------

    def test_rueckgabe_nach_lager(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_rueckgeben(
            self.gerat, zustand_rueckgabe=2, maengel="Display rissig",
            ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertIsNone(self.gerat.person)
        self.assertEqual(self.gerat.zustand, 2)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertEqual(v.typ, Vorgang.TYP_RUECKGABE)
        self.assertTrue(v.abschliesst)

    def test_rueckgabe_ziel_reparatur(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_rueckgeben(
            self.gerat, zustand_rueckgabe=3, ziel="reparatur",
            ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_REPARATUR)

    def test_rueckgabe_fehlend_startet_ausmusterung(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_rueckgeben(
            self.gerat, zustand_rueckgabe=1, fehlend=True,
            ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_rueckgabe_verweigert_auf_lager(self):
        """F-50: Nur In Benutzung oder Verliehen kann zurückgegeben werden."""
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        with self.assertRaises(services.GeratFehler):
            services.gerat_rueckgeben(
                self.gerat, zustand_rueckgabe=1, ausgefuehrt_von=self.admin
            )

    # --- F-41: Umzug -------------------------------------------------------------

    def test_umzug(self):
        ort2 = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="M3-LAG2", name="M3-Lager2")
        services.gerat_ausgeben(self.gerat, self.ort, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_umziehen(self.gerat, ort2, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.ort, ort2)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertEqual(v.typ, Vorgang.TYP_UMZUG)
        self.assertTrue(v.abschliesst)

    def test_umzug_verweigert_aus_reparatur(self):
        services.gerat_in_reparatur_geschickt(
            self.gerat, dienstleister="FixIT", vorgangsnummer="VR-002",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        ort2 = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="M3-LAG2", name="M3-Lager2")
        with self.assertRaises(services.GeratFehler):
            services.gerat_umziehen(self.gerat, ort2, ausgefuehrt_von=self.admin)

    def test_umzug_verweigert_aus_ausgemustert(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Schrotten", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        ort2 = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="M3-LAG2", name="M3-Lager2")
        with self.assertRaises(services.GeratFehler):
            services.gerat_umziehen(self.gerat, ort2, ausgefuehrt_von=self.admin)

    # --- F-42: Reparatur ---------------------------------------------------------

    def test_reparatur_start(self):
        services.gerat_in_reparatur_geschickt(
            self.gerat, dienstleister="FixIT", vorgangsnummer="VR-003",
            notiz="Display defekt", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_REPARATUR)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertEqual(v.typ, Vorgang.TYP_REPARATUR)
        self.assertFalse(v.abschliesst)

    def test_reparatur_fertig_ziel_zuordnung(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_in_reparatur_geschickt(
            self.gerat, dienstleister="FixIT", vorgangsnummer="VR-004",
            notiz="Taste defekt", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        services.gerat_reparatur_fertig(
            self.gerat, zustand=2, ziel="zuordnung",
            kosten=150.0, beleg="RB-2026-001", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(self.gerat.zustand, 2)

    def test_reparatur_fertig_ziel_lager(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_in_reparatur_geschickt(
            self.gerat, dienstleister="FixIT", vorgangsnummer="VR-005",
            notiz="Mauspad", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        services.gerat_reparatur_fertig(
            self.gerat, zustand=3, ziel="lager", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertIsNone(self.gerat.person)

    def test_reparatur_start_verweigert_aus_ausgemustert(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Schrotten", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_in_reparatur_geschickt(
                self.gerat, dienstleister="FixIT", vorgangsnummer="VR-006",
                notiz="X", ausgefuehrt_von=self.admin,
            )

    def test_reparatur_fertig_verweigert_ohne_reparatur(self):
        with self.assertRaises(services.GeratFehler):
            services.gerat_reparatur_fertig(
                self.gerat, zustand=2, ziel="lager", ausgefuehrt_von=self.admin
            )

    # --- F-55 bis F-58: Ausmusterung ---------------------------------------------

    def test_ausmusterung(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Recycling", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUSGEMUSTERT)
        self.assertIsNone(self.gerat.person)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertEqual(v.typ, Vorgang.TYP_AUSMUSTERUNG)
        self.assertTrue(v.abschliesst)

    def test_ausmusterung_verweigert_wenn_bereits_ausgemustert(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Schrotten", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(
                self.gerat, grund="defekt", datum=date(2026, 2, 1),
                disposition="Schrotten", ausgefuehrt_von=self.admin,
            )

    def test_ausmusterung_verloren_ohne_bestatigung(self):
        from datetime import date
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(
                self.gerat, grund="verloren", datum=date(2026, 1, 1),
                disposition="Verlust", bestaetigt_gemeldt=False,
                ausgefuehrt_von=self.admin,
            )

    def test_ausmusterung_verloren_mit_bestatigung(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="verloren", datum=date(2026, 1, 1),
            disposition="Verlust", bestaetigt_gemeldt=True,
            ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_ausmusterung_datentraeger_ohne_loeschung(self):
        kat_dd = Kategorie.objects.create(name="Notebook DD", hat_datentraeger=True)
        g = services.gerat_anlegen(kategorie=kat_dd, hersteller="Lenovo", modell="T14")
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(
                g, grund="defekt", datum=date(2026, 1, 1),
                disposition="Schrotten", ausgefuehrt_von=self.admin,
            )

    def test_ausmusterung_datentraeger_mit_loeschung(self):
        kat_dd = Kategorie.objects.create(name="Notebook DD", hat_datentraeger=True)
        g = services.gerat_anlegen(kategorie=kat_dd, hersteller="Lenovo", modell="T14")
        services.ausmustern(
            g, grund="defekt", datum=date(2026, 1, 1),
            disposition="Recycling",
            loeschung_art="physisch", loeschung_nachweis="Zertifikat XYZ",
            ausgefuehrt_von=self.admin,
        )
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_AUSGEMUSTERT)

    # --- N-03: Nachvollziehbarkeit -------------------------------------------------

    def test_vorgaenge_nicht_geloescht(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_rueckgeben(self.gerat, zustand_rueckgabe=1, ausgefuehrt_von=self.admin)
        anzahl = Vorgang.objects.filter(gerat=self.gerat).count()
        self.assertEqual(anzahl, 3)

    def test_jeder_vorgang_hat_konto_und_zeitstempel(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        v = Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt').first()
        self.assertIsNotNone(v.erzeugt_von)
        self.assertIsNotNone(v.zeitpunkt)

    def test_vorgangshistorie_neueste_zuerst(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        services.gerat_rueckgeben(self.gerat, zustand_rueckgabe=1, ausgefuehrt_von=self.admin)
        hist = list(Vorgang.objects.filter(gerat=self.gerat).order_by('-zeitpunkt'))
        self.assertEqual(hist[0].typ, Vorgang.TYP_RUECKGABE)
        self.assertEqual(hist[1].typ, Vorgang.TYP_AUSGABE)

    def test_nach_ausmusterung_keine_weiteren_vorgaenge(self):
        from datetime import date
        services.ausmustern(
            self.gerat, grund="veraltet", datum=date(2026, 1, 1),
            disposition="Schrotten", ausgefuehrt_von=self.admin,
        )
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        with self.assertRaises(services.GeratFehler):
            services.gerat_rueckgeben(self.gerat, zustand_rueckgabe=1, ausgefuehrt_von=self.admin)
        ort2 = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="M3-LAG3", name="M3-Lager3")
        with self.assertRaises(services.GeratFehler):
            services.gerat_umziehen(self.gerat, ort2, ausgefuehrt_von=self.admin)
        with self.assertRaises(services.GeratFehler):
            services.gerat_in_reparatur_geschickt(
                self.gerat, dienstleister="FixIT", vorgangsnummer="VR-999",
                notiz="X", ausgefuehrt_von=self.admin,
            )


# --- M3 Nachbesserung: Gerätedetail Aktionen (A-0074) --------------------------

class DetailAktionenTests(TestCase):
    """Gerätedetail zeigt Aktionen je Status und Recht (TESTSCHNITTSTELLE 5)."""

    def setUp(self):
        self.client = Client()
        self.kat = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        self.ort = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="DET-LAG")
        self.admin = konto_erstellen("det.admin")
        self.mitarbeiter = konto_erstellen("det.mitarbeiter", rolle="mitarbeiter")

    def _detail(self, gerat, user):
        self.client.logout()
        self.client.login(username=user.email, password="test-passwort-123")
        return self.client.get(f"/geraete/{gerat.inventarnummer}/")

    def test_auf_lager_admin_zeigt_alle_aktionen(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        antwort = self._detail(g, self.admin)
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="aktion-ausgabe"', text)
        self.assertIn('data-test="aktion-reparatur"', text)
        self.assertIn('data-test="aktion-ausmustern"', text)
        self.assertIn('data-test="aktion-bearbeiten"', text)
        self.assertNotIn('data-test="aktion-rueckgabe"', text)
        self.assertNotIn('data-test="aktion-reparatur-abschliessen"', text)

    def test_in_benutzung_admin_zeigt_rueckgabe(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        antwort = self._detail(g, self.admin)
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="aktion-rueckgabe"', text)
        self.assertIn('data-test="aktion-umzug"', text)
        self.assertNotIn('data-test="aktion-ausgabe"', text)
        self.assertNotIn('data-test="aktion-reparatur"', text)
        self.assertNotIn('data-test="aktion-ausmustern"', text)

    def test_in_reparatur_admin_zeigt_abschliessen(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-001",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        antwort = self._detail(g, self.admin)
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="aktion-reparatur-abschliessen"', text)
        self.assertNotIn('data-test="aktion-ausgabe"', text)
        self.assertNotIn('data-test="aktion-rueckgabe"', text)
        self.assertNotIn('data-test="aktion-umzug"', text)
        self.assertNotIn('data-test="aktion-ausmustern"', text)

    def test_mitarbeiter_zeigt_keine_aktionen(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        antwort = self._detail(g, self.mitarbeiter)
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertNotIn('data-test="aktion-ausgabe"', text)
        self.assertNotIn('data-test="aktion-rueckgabe"', text)
        self.assertNotIn('data-test="aktion-umzug"', text)
        self.assertNotIn('data-test="aktion-reparatur"', text)
        self.assertNotIn('data-test="aktion-reparatur-abschliessen"', text)
        self.assertNotIn('data-test="aktion-ausmustern"', text)
        self.assertNotIn('data-test="aktion-bearbeiten"', text)

    def test_status_data_wert(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        antwort = self._detail(g, self.admin)
        text = antwort.content.decode()
        self.assertIn('data-wert="auf-lager"', text)

    def test_historie_aufnahme(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        antwort = self._detail(g, self.admin)
        text = antwort.content.decode()
        self.assertIn('data-typ="Aufnahme"', text)
        self.assertIn('data-test="historie"', text)

    def test_historie_ausgabe(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        antwort = self._detail(g, self.admin)
        text = antwort.content.decode()
        self.assertIn('data-typ="Ausgabe"', text)

    def test_link_ausgabe_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/ausgeben/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_rueckgabe_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/rueckgeben/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_umzug_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/umziehen/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_reparatur_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/reparatur/start/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_reparatur_abschliessen_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-001",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/reparatur/fertig/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_ausmustern_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/ausmustern/")
        self.assertEqual(antwort.status_code, 200)

    def test_link_bearbeiten_offnet_seite(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/aendern/")
        self.assertEqual(antwort.status_code, 200)


# --- M4 Arbeitsplätze (F-62 bis F-64, F-89) -----------------------------------

class M4ArbeitsplatzTests(TestCase):
    """Soll-Ist-Abgleich, Bedarf, Erstinventur (AUFTRAG M4)."""

    def setUp(self):
        self.admin = konto_erstellen("m4.admin")
        self.kat_monitor = Kategorie.objects.create(name="Monitor")
        self.kat_docking = Kategorie.objects.create(name="Dockingstation")
        self.kat_notebook = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        from stammdaten.models import Ausstattungsprofil, Profilposition
        self.profil = Ausstattungsprofil.objects.create(name="Standard")
        Profilposition.objects.create(profil=self.profil, kategorie=self.kat_monitor, anzahl=2)
        Profilposition.objects.create(profil=self.profil, kategorie=self.kat_docking, anzahl=1)
        self.ort = Ort.objects.create(
            typ=Ort.TYP_ARBEITSPLATZ, kennung="M4-AP-01", name="M4-Arbeitsplatz",
            profil=self.profil, feste_person=self.person,
        )
        self.lager = Ort.objects.create(
            typ=Ort.TYP_LAGER, kennung="M4-LAG", name="M4-Lager"
        )

    def _gerat(self, kategorie, ort=None, person=None, status=Gerat.STATUS_IN_BENUTZUNG):
        return services.gerat_anlegen(
            kategorie=kategorie, hersteller="Test", modell="M4",
            erzeugt_von=self.admin,
        )

    # --- F-62: Soll-Ist-Abgleich -------------------------------------------------

    def test_soll_ist_vollstaendig(self):
        for i in range(2):
            g = self._gerat(self.kat_monitor, ort=self.ort)
            services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        g = self._gerat(self.kat_docking, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        abgleich = services.soll_ist_abgleich(self.ort)
        self.assertEqual(abgleich["ergebnis"], "vollstaendig")
        self.assertEqual(abgleich["fehlend"], [])
        self.assertEqual(abgleich["zuviel"], [])

    def test_soll_ist_unvollstaendig(self):
        g = self._gerat(self.kat_monitor, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        abgleich = services.soll_ist_abgleich(self.ort)
        self.assertEqual(abgleich["ergebnis"], "unvollstaendig")
        self.assertEqual(len(abgleich["fehlend"]), 2)
        fehlend = {k.name: a for k, a in abgleich["fehlend"]}
        self.assertEqual(fehlend["Monitor"], 1)
        self.assertEqual(fehlend["Dockingstation"], 1)

    def test_soll_ist_mehr_als_soll(self):
        for i in range(3):
            g = self._gerat(self.kat_monitor, ort=self.ort)
            services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        g = self._gerat(self.kat_docking, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        abgleich = services.soll_ist_abgleich(self.ort)
        self.assertEqual(abgleich["ergebnis"], "mehr-als-soll")
        self.assertEqual(abgleich["zuviel"], [(self.kat_monitor, 1)])

    def test_geraete_aus_reparatur_nicht_im_abgleich(self):
        g = self._gerat(self.kat_monitor, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-M4",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        abgleich = services.soll_ist_abgleich(self.ort)
        self.assertEqual(abgleich["ergebnis"], "unvollstaendig")
        fehlend = {k.name: a for k, a in abgleich["fehlend"]}
        self.assertEqual(fehlend["Monitor"], 2)
        self.assertEqual(fehlend["Dockingstation"], 1)

    def test_geraete_ausgemustert_nicht_im_abgleich(self):
        from datetime import date
        g = self._gerat(self.kat_monitor, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        services.ausmustern(
            g, grund="defekt", datum=date(2026, 10, 1),
            disposition="Recycling", ausgefuehrt_von=self.admin,
        )
        abgleich = services.soll_ist_abgleich(self.ort)
        self.assertEqual(abgleich["ergebnis"], "unvollstaendig")
        fehlend = {k.name: a for k, a in abgleich["fehlend"]}
        self.assertEqual(fehlend["Monitor"], 2)
        self.assertEqual(fehlend["Dockingstation"], 1)

    # --- F-64: Geräte der Person getrennt ---------------------------------------

    def test_gerate_der_person_getrennt(self):
        g = self._gerat(self.kat_notebook, person=self.person)
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        gerate_person = services.gerate_der_person(self.person)
        self.assertEqual(len(gerate_person), 1)
        gerate_ort = services.gerate_am_ort(self.ort)
        self.assertEqual(len(gerate_ort), 0)

    # --- F-63: Bedarf -------------------------------------------------------------

    def test_bedarf_zeigt_fehlende(self):
        abgleich = services.bedarf_uebersicht([self.ort])
        self.assertIn(self.kat_monitor, abgleich["summe"])
        self.assertEqual(abgleich["summe"][self.kat_monitor], 2)
        self.assertIn(self.kat_docking, abgleich["summe"])
        self.assertEqual(abgleich["summe"][self.kat_docking], 1)

    def test_bedarf_mit_lagerbestand(self):
        g = self._gerat(self.kat_monitor, ort=self.lager)
        services.gerat_umziehen(g, self.lager, ausgefuehrt_von=self.admin)
        abgleich = services.bedarf_uebersicht([self.ort])
        self.assertEqual(abgleich["lagerbestand"][self.kat_monitor], 1)
        self.assertEqual(abgleich["summe"][self.kat_monitor], 2)

    def test_bedarf_ohne_orte(self):
        abgleich = services.bedarf_uebersicht([])
        self.assertEqual(abgleich["summe"], {})

    # --- F-89: Erstinventur Fortschritt -------------------------------------------

    def test_fortschritt_je_ort(self):
        g = self._gerat(self.kat_monitor, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        zeilen = services.fortschritt_je_ort([self.ort])
        self.assertEqual(len(zeilen), 1)
        self.assertEqual(zeilen[0]["geprueft"], 0)
        self.assertEqual(zeilen[0]["alle"], 1)
        self.assertFalse(zeilen[0]["vollstaendig"])

    def test_fortschritt_nach_pruefen(self):
        g = self._gerat(self.kat_monitor, ort=self.ort)
        services.gerat_umziehen(g, self.ort, ausgefuehrt_von=self.admin)
        services.gerat_pruefen(g, self.admin)
        zeilen = services.fortschritt_je_ort([self.ort])
        self.assertEqual(zeilen[0]["geprueft"], 1)
        self.assertEqual(zeilen[0]["alle"], 1)
        self.assertTrue(zeilen[0]["vollstaendig"])

    def test_ort_pruefen_view(self):
        self.client.login(email="m4.admin@wamocon.de", password="test-passwort-123")
        response = self.client.post(f"/geraete/arbeitsplaetze/{self.ort.pk}/pruefen/")
        self.assertEqual(response.status_code, 302)
        self.ort.refresh_from_db()
        self.assertIsNotNone(self.ort.aktualisiert_am)
