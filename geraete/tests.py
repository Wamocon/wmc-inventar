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
from .models import Gerat, GeratKonflikt, Importlauf, Leihe, Vorgang
from .services import GeratFehler, leihe_ablehnen, leihe_anfragen, leihe_genehmigen, leihe_zurueckziehen


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

    def test_seriennummer_doppelte_selber_hersteller_abgelehnt(self):
        """A-0097 F-10: dieselbe Seriennummer beim selben Hersteller wird abgelehnt."""
        kat, ort, person = stammdaten_erstellen()
        g1 = services.gerat_anlegen(
            kategorie=kat, hersteller="Lenovo", modell="T14", seriennummer="SN-12345"
        )
        with self.assertRaises(services.GeratFehler) as ctx:
            services.gerat_anlegen(
                kategorie=kat, hersteller="Lenovo", modell="X1", seriennummer="sn-12345 "
            )
        self.assertIn(g1.inventarnummer, str(ctx.exception))

    def test_seriennummer_doppelte_ander_hersteller_laeuft(self):
        """A-0097 F-10: beim anderen Hersteller wird das Gerät angelegt (kein Fehler)."""
        kat, ort, person = stammdaten_erstellen()
        g1 = services.gerat_anlegen(
            kategorie=kat, hersteller="Lenovo", modell="T14", seriennummer="SN-99999"
        )
        # Beim anderen Hersteller: kein GeratFehler, Gerät wird angelegt.
        g2 = services.gerat_anlegen(
            kategorie=kat, hersteller="HP", modell="EliteBook", seriennummer="SN-99999"
        )
        self.assertIsNotNone(g2.pk)
        self.assertEqual(g2.seriennummer, "SN-99999")

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
        self.assertIn('data-test="geprueft"', text)

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
        self.assertEqual(antwort.status_code, 403)

    def test_leser_kann_nicht_bearbeiten(self):
        konto_erstellen("leser.k", rolle="leser")
        self.client.logout()
        self.client.login(username="leser.k@wamocon.de", password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/aendern/")
        self.assertEqual(antwort.status_code, 403)

    def test_ausgemustert_zeigt_keine_aktion_bearbeiten(self):
        """A-0097 F-58: Ausgemustertes Gerät zeigt weder „Ändern“ noch „Prüfung abhaken“."""
        services.ausmustern(
            self.g1, grund="verloren", datum=date(2026, 10, 1),
            bestaetigt_gemeldt=True, ausgefuehrt_von=self.konto,
        )
        self.client.login(username=self.konto.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/")
        text = antwort.content.decode()
        self.assertNotIn('data-test="aktion-bearbeiten"', text)
        self.assertNotIn('data-test="pruefen"', text)

    def test_ausgemustert_aendern_adresse_lehnt_ab(self):
        """A-0097 F-58: /aendern/ eines ausgemusterten Geräts wird abgelehnt."""
        services.ausmustern(
            self.g1, grund="verloren", datum=date(2026, 10, 1),
            bestaetigt_gemeldt=True, ausgefuehrt_von=self.konto,
        )
        self.client.login(username=self.konto.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/aendern/")
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort.headers["Location"], f"/geraete/{self.g1.inventarnummer}/")
        detail = self.client.get(f"/geraete/{self.g1.inventarnummer}/")
        text = detail.content.decode()
        self.assertIn('data-test="fehler"', text)
        self.assertIn("nicht mehr änderbar", text)


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

    def test_historie_aenderungen_gezeigt(self):
        """A-0098 (F-40): Ändert man Felder, zeigt die Historie je geändertem
        Feld einen Vorgang vom Typ „Änderung“ mit dem Feld, dem alten und dem
        neuen Wert (data-typ trägt „Änderung“)."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_bearbeiten(
            g, werte={"modell": "T16", "seriennummer": "SN-1234"}, erzeugt_von=self.admin
        )
        antwort = self._detail(g, self.admin)
        text = antwort.content.decode()
        self.assertIn('data-typ="Änderung"', text)
        self.assertIn('data-feld="modell"', text)
        self.assertIn('data-alt="T14"', text)
        self.assertIn('data-neu="T16"', text)
        self.assertIn('data-feld="seriennummer"', text)
        self.assertIn('data-alt=""', text)
        self.assertIn('data-neu="SN-1234"', text)

    def test_historie_aenderung_kein_vorgang_ohne_aenderung(self):
        """A-0098 (F-40): Ohne Änderung entsteht kein Vorgang."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        vorher = g.vorgaenge.count()
        services.gerat_bearbeiten(g, werte={"modell": "T14"}, erzeugt_von=self.admin)
        self.assertEqual(g.vorgaenge.count(), vorher)

    def test_historie_zeigt_konto(self):
        """A-0098 (F-43, N-03): Jede Zeile der Historie und die Zeile
        „Erstellt“ zeigen das Konto, das den Vorgang ausgeführt hat: den
        Namen, sonst die E-Mail-Adresse."""
        g = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14", erzeugt_von=self.admin
        )
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        antwort = self._detail(g, self.admin)
        text = antwort.content.decode()
        self.assertIn(self.admin.email, text)
        self.assertIn('data-test="erzeugt-von"', text)

    def test_konto_bezeichnung_zeigt_namen(self):
        """A-0098 (F-43): Bezeichnung des Kontos – Name, sonst E-Mail."""
        person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker",
            email="anna.becker@example.test",
        )
        konto = Konto(email="anna@example.test", rolle=Konto.ROLLE_MITARBEITER, person=person)
        konto.save()
        self.assertEqual(konto.bezeichnung(), "Anna Becker")
        # Ohne Person: die E-Mail-Adresse.
        leer = Konto(email="it-admin@beispiel.test", rolle=Konto.ROLLE_ADMIN)
        leer.save()
        self.assertEqual(leer.bezeichnung(), "it-admin@beispiel.test")

    def test_aufnahme_erzeugt_von_gezaehlt(self):
        """A-0098 (F-43): Der Vorgang Aufnahme bekommt ein Konto,
        wenn erzeugt_von übergeben wird."""
        g = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14", erzeugt_von=self.admin
        )
        aufnahme = g.vorgaenge.filter(typ=Vorgang.TYP_AUFNAHME).first()
        self.assertIsNotNone(aufnahme)
        self.assertEqual(aufnahme.erzeugt_von, self.admin)

    # --- A-0098 (F-44): Suche je Feld ----------------------------------------

    def _suche(self, wert: str):
        antwort = self.client.get("/geraete/", {"q": wert})
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def test_suche_inventarnummer(self):
        """A-0098 (F-44): Die Suche findet nach Inventarnummer;
        jede Trefferzeile trägt data-test=suchtreffer."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        text = self._suche(g.inventarnummer)
        self.assertIn('data-test="suchtreffer"', text)
        self.assertIn(g.inventarnummer, text)

    def test_suche_seriennummer(self):
        """A-0098 (F-44): Die Suche findet nach Seriennummer."""
        g = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14", seriennummer="SN-8842"
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        text = self._suche("SN-8842")
        self.assertIn('data-test="suchtreffer"', text)
        self.assertIn(g.inventarnummer, text)

    def test_suche_modell(self):
        """A-0098 (F-44): Die Suche findet nach Modell."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        text = self._suche("T14")
        self.assertIn('data-test="suchtreffer"', text)
        self.assertIn(g.inventarnummer, text)

    def test_suche_hostname(self):
        """A-0098 (F-44): Die Suche findet nach Hostname (Gerätename)."""
        g = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14", geraetename="Pool-A"
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        text = self._suche("Pool-A")
        self.assertIn('data-test="suchtreffer"', text)
        self.assertIn(g.inventarnummer, text)

    def test_suche_person(self):
        """A-0098 (F-44): Die Suche findet nach Person (Vor- und Nachname)."""
        g = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="T14", person=self.person
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        text = self._suche("Muster")
        self.assertIn('data-test="suchtreffer"', text)
        self.assertIn(g.inventarnummer, text)

    def test_suche_feld_traegt_data_test(self):
        """A-0098 (F-44): Das Suchfeld trägt data-test=suche (Kapitel 4)."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/geraete/")
        text = antwort.content.decode()
        self.assertIn('data-test="suche"', text)

    # --- A-0098 (F-131): Zustand je Stufe in der Ausgabe ----------------------

    def _ausgabe_abschliessen(self, g, zustand):
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausgeben/",
            {
                "ziel_person": self.person.pk,
                "zustand": zustand,
                "zubehoer_komplett": "ja",
                "anmerkung": "ausgabe-test",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        g.refresh_from_db()
        return g.vorgaenge.filter(typ=Vorgang.TYP_AUSGABE).latest("zeitpunkt")

    def _zustand_je_stufe(self, stufe: int):
        """A-0098 (F-131): Der Zustand geht je Stufe in den Vorgang Ausgabe
        und auf das Gerät."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        vorgang = self._ausgabe_abschliessen(g, int(stufe))
        self.assertEqual(g.zustand, stufe)
        zustaende = dict(Gerat.ZUSTAENDE)
        self.assertIn("Zustand: " + zustaende[stufe], vorgang.notiz)
        self.assertIn("Zubehör komplett: Ja", vorgang.notiz)

    def test_ausgabe_zustand_neuwertig(self):
        self._zustand_je_stufe(Gerat.ZUSTAND_NEUWERTIG)

    def test_ausgabe_zustand_gut(self):
        self._zustand_je_stufe(Gerat.ZUSTAND_GUT)

    def test_ausgabe_zustand_spuren(self):
        self._zustand_je_stufe(Gerat.ZUSTAND_SPUREN)

    def test_ausgabe_zustand_eingeschraenkt(self):
        self._zustand_je_stufe(Gerat.ZUSTAND_EINGESCHRAENKT)

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

    # --- A-0075: Dialoge (Testschnittstelle Kapitel 4) ---------------------------

    def test_dialog_ausgabe_oeffnet_mit_speichern(self):
        """Testschnittstelle Zeile 210: Nach Klick auf Aktion ist data-test=dialog
        mit data-name=ausgabe sichtbar, darin data-test=speichern."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/ausgeben/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="ausgabe"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_ausgabe_speichern_zeigt_meldung(self):
        """A-0098 (F-131): Nach dem Speichern zeigt /geraete/<nr>/ die Meldung
        (data-test=meldung). Der Dialog trägt jetzt Zustand, Zubehör komplett,
        Bemerkung."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausgeben/",
            {
                "ziel_person": self.person.pk,
                "zustand": Gerat.ZUSTAND_GUT,
                "zubehoer_komplett": "ja",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort.headers["Location"], f"/geraete/{g.inventarnummer}/")
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())

    def test_dialog_ausgabe_oeffnet_mit_zustand_zubehoer_bemerkung(self):
        """A-0098 (F-131): Der Ausgabe-Dialog trägt die Felder des Prototyps:
        „Zustand“ (Auswahl mit den vier Stufen von Gerat.ZUSTAENDE,
        voreingestellt mit dem Zustand des Geräts), „Zubehör komplett“
        (Ja, Nein) und „Bemerkung“."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/ausgeben/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="ausgabe-zustand"', text)
        self.assertIn('data-test="zubehoer-komplett"', text)
        self.assertIn('data-test="anmerkung"', text)
        # Voreingestellt mit dem Zustand des Geräts (default 2 – gut).
        self.assertIn('value="2" selected', text)
        # Alle vier Stufen stehen in der Auswahl.
        for stufe in (1, 2, 3, 4):
            self.assertIn(f'value="{stufe}"', text)

    def test_dialog_rueckgabe_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/rueckgeben/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="rueckgabe"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_rueckgabe_speichern_zeigt_meldung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/rueckgeben/",
            {"zustand_rueckgabe": "2", "zubehoer_komplett": "ja", "ziel": "lager"},
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())
        self.assertIn('data-test="status"', detail.content.decode())

    def test_dialog_rueckgabe_fehlend_startet_ausmusterung(self):
        """A-0097: „fehlt, Ausmusterung starten“ startet die Ausmusterung."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/rueckgeben/",
            {"zustand_rueckgabe": "2", "zubehoer_komplett": "nein", "ziel": "fehlend"},
        )
        self.assertEqual(antwort.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.status, "ausgemustert")
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        text = detail.content.decode()
        self.assertIn('data-test="status"', text)
        self.assertIn("ausgemustert", text)

    def test_dialog_umzug_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/umziehen/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="umzug"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_umzug_speichern_zeigt_meldung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/umziehen/",
            {"ziel_ort": self.ort.pk},
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())

    def test_dialog_reparatur_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/reparatur/start/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="reparatur"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_reparatur_speichern_zeigt_meldung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/reparatur/start/",
            {
                "dienstleister": "FixIT",
                "vorgangsnummer": "VR-001",
                "notiz": "Display rissig",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_IN_REPARATUR)

    def test_dialog_reparatur_abschliessen_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-001",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/reparatur/fertig/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="reparatur-abschliessen"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_reparatur_abschliessen_speichern_zeigt_meldung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-001",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/reparatur/fertig/",
            {"zustand": "2", "ziel": "lager"},
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_AUF_LAGER)

    def test_dialog_reparatur_abschliessen_ziel_bisherige_zuordnung(self):
        """A-0097: Ziel „Bisherige Zuordnung“ gibt das Gerät zurück an die Person."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        services.gerat_in_reparatur_geschickt(
            g, dienstleister="FixIT", vorgangsnummer="VR-002",
            notiz="Defekt", ausgefuehrt_von=self.admin,
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/reparatur/fertig/",
            {"zustand": "2", "ziel": "zuordnung"},
        )
        self.assertEqual(antwort.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(g.person, self.person)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertIn('data-test="meldung"', detail.content.decode())

    def test_dialog_ausmustern_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/ausmustern/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="ausmustern"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_ausmustern_speichern_zeigt_meldung(self):
        from datetime import date
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausmustern/",
            {
                "grund": "veraltet",
                "datum": "2026-10-01",
                "disposition": "Schrotten",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_dialog_ausmustern_grund_pflicht(self):
        """A-0097: Grund ohne Auswahl zeigt „Bitte einen Grund wählen.“"""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausmustern/",
            {"grund": "", "datum": "2026-10-01", "disposition": "Schrotten"},
        )
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="fehler"', text)
        self.assertIn("Bitte einen Grund wählen.", text)
        g.refresh_from_db()
        self.assertNotEqual(g.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_dialog_ausmustern_verloren_ohne_bestätigung(self):
        """A-0097: Verlust ohne Bestätigung „gemeldet“ zeigt fehler."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausmustern/",
            {"grund": "verloren", "datum": "2026-10-01"},
        )
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="fehler"', text)
        self.assertIn("gemeldet", text)
        g.refresh_from_db()
        self.assertNotEqual(g.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_dialog_ausmustern_verloren_mit_bestätigung(self):
        """A-0097: Verlust mit Bestätigung läuft durch."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausmustern/",
            {"grund": "verloren", "datum": "2026-10-01", "bestaetigt_gemeldt": "on"},
        )
        self.assertEqual(antwort.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_dialog_bearbeiten_oeffnet_mit_speichern(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/aendern/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="dialog"', text)
        self.assertIn('data-name="bearbeiten"', text)
        self.assertIn('data-test="speichern"', text)

    def test_dialog_bearbeiten_speichern_zeigt_meldung(self):
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/aendern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "HP",
                "modell": "ZBook",
                "seriennummer": "",
                "zustand": "2",
                "geraetename": "",
                "standardzuehoer": "",
                "technische_daten": "",
                "kaufdatum": "2026-01-01",
                "kaufpreis_netto": "",
                "lieferant": "",
                "rechnungsnummer": "",
                "garantie_bis": "",
                "notiz": "",
                "person": "",
                "ort": "",
                "leihpool": "",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        detail = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-test="meldung"', detail.content.decode())

    def test_dialog_feuer_fehler_bei_ungueltigem_formular(self):
        """Bei ungültigem Formular zeigt das Element data-test=fehler."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{g.inventarnummer}/ausgeben/",
            {"ziel_person": "", "ziel_ort": ""},
        )
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('data-test="fehler"', antwort.content.decode())

    def test_detail_verbleib_zeigt_person(self):
        """Gerätedetail zeigt die Markierung verbleib (Testschnittstelle Kapitel 4)."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('data-test="verbleib"', antwort.content.decode())

    def test_detail_data_typ_am_vorgang(self):
        """data-typ steht auf dem Element data-test=vorgang, nicht auf der Zeile."""
        g = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="vorgang" data-typ="Aufnahme"', text)


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
        # A-0076: Die Seiten der Arbeitsplätze liegen unter /arbeitsplaetze/,
        # die Detailseite und Prüfen nehmen die Kennung (TESTSCHNITTSTELLE Kap. 3).
        response = self.client.post("/arbeitsplaetze/M4-AP-01/pruefen/")
        self.assertEqual(response.status_code, 302)
        self.ort.refresh_from_db()
        self.assertIsNotNone(self.ort.aktualisiert_am)


# --- F-14 (A-0099): Löschen ---------------------------------------------------

class LoeschenTests(TestCase):
    """Gerät löschen: Admin, nur ohne Vorgang außer Aufnahme (F-14)."""

    def setUp(self):
        self.kat = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        self.admin = konto_erstellen("loeschen.admin")
        self.mitarbeiter = konto_erstellen("loeschen.mitarbeiter", rolle="mitarbeiter")

    def _gerat(self):
        return services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")

    def test_admin_ohne_vorgang_kann_loeschen(self):
        g = self._gerat()
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/loeschen/bestaetigen/")
        self.assertEqual(antwort.status_code, 302)
        self.assertFalse(Gerat.objects.filter(inventarnummer=g.inventarnummer).exists())

    def test_mitarbeiter_kann_nicht_loeschen(self):
        g = self._gerat()
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/loeschen/bestaetigen/")
        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(Gerat.objects.filter(inventarnummer=g.inventarnummer).exists())

    def test_admin_mit_vorgang_kann_nicht_loeschen(self):
        g = self._gerat()
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/loeschen/bestaetigen/")
        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(Gerat.objects.filter(inventarnummer=g.inventarnummer).exists())

    def test_admin_ohne_vorgang_zeigt_loeschen_aktion(self):
        g = self._gerat()
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/")
        text = antwort.content.decode()
        self.assertIn('data-test="aktion-loeschen"', text)

    def test_admin_mit_vorgang_zeigt_keine_loeschen_aktion(self):
        g = self._gerat()
        services.gerat_ausgeben(g, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/")
        text = antwort.content.decode()
        self.assertNotIn('data-test="aktion-loeschen"', text)

    def test_mitarbeiter_zeigt_keine_loeschen_aktion(self):
        g = self._gerat()
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/")
        text = antwort.content.decode()
        self.assertNotIn('data-test="aktion-loeschen"', text)


# --- A-0106: Raumplan (F-65, F-68) --------------------------------------------

class RaumplanTests(TestCase):
    """Raumplan: 15 Plätze und 4 Räume (F-65, F-68, A-0106).

    TESTSCHNITTSTELLE Kapitel 2: 15 Arbeitsplätze und 4 Orte vom Typ Raum.
    """

    def setUp(self):
        from stammdaten.models import Plan

        # Plan und Orte wie in beispieldaten anlegen
        self.plan = Plan.objects.create(
            standort="Eschborn",
            etage="1. OG",
        )

        # 15 Arbeitsplätze (TESTSCHNITTSTELLE Kapitel 2)
        arbeitsplaetze = [
            ("WMC-WP-01", "Großraumbüro", 50.1, 55.6),
            ("WMC-WP-02", "Großraumbüro", 64.1, 55.6),
            ("WMC-WP-03", "Großraumbüro", 50.1, 61.3),
            ("WMC-WP-04", "Großraumbüro", 64.1, 61.3),
            ("WMC-WP-05", "Großraumbüro", 50.1, 69.3),
            ("WMC-WP-06", "Großraumbüro", 64.1, 69.3),
            ("WMC-WP-07", "Großraumbüro", 50.1, 75.1),
            ("WMC-WP-08", "Großraumbüro", 64.1, 75.1),
            ("WMC-WP-09", "Großraumbüro", 50.1, 83.1),
            ("WMC-WP-10", "Großraumbüro", 64.1, 83.1),
            ("WMC-WP-11", "Großraumbüro", 50.1, 88.9),
            ("WMC-WP-12", "Großraumbüro", 64.1, 88.9),
            ("WMC-WP-13", "Büro Geschäftsführung", 10.4, 62.7),
            ("WMC-WP-14", "Büro Geschäftsführung", 24.3, 62.7),
            ("WMC-WP-15", "Studio", 10.7, 77.3),
        ]
        for kennung, raum, x, y in arbeitsplaetze:
            Ort.objects.create(
                typ=Ort.TYP_ARBEITSPLATZ,
                kennung=kennung,
                name=kennung,
                standort="Eschborn",
                raum=raum,
                position_x=x,
                position_y=y,
                plan_id=self.plan.id,
            )

        # 4 Räume (TESTSCHNITTSTELLE Kapitel 2)
        raume = [
            ("STUDIO-TECHNIK", "Studiotechnik", "Studio", 24.1, 87.3),
            ("ACADEMY-TECHNIK", "Academy-Technik", "Academy-Raum", 77.4, 36.9),
            ("SERVER-TECHNIK", "Serverschrank", "Serverraum", 24.6, 30.3),
            ("EINGANG", "Eingangsbereich", "Großraumbüro", 44.6, 44.7),
        ]
        for kennung, name, raum, x, y in raume:
            Ort.objects.create(
                typ=Ort.TYP_RAUM,
                kennung=kennung,
                name=name,
                standort="Eschborn",
                raum=raum,
                position_x=x,
                position_y=y,
                plan_id=self.plan.id,
            )

        # Konten
        self.admin = konto_erstellen("raumplan.admin", rolle="admin")
        self.leser = konto_erstellen("raumplan.leser", rolle="leser")
        self.mitarbeiter = konto_erstellen("raumplan.mitarbeiter", rolle="mitarbeiter")

    def test_raumplan_admin_sieht_alle_plaetze(self):
        """F-65: Admin sieht 15 Plätze und 4 Räume im Raumplan."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()

        # 15 Plätze mit data-x und data-y
        platz_count = html.count('data-test="platz"')
        self.assertEqual(platz_count, 15, f"Erwartet 15 Plätze, gefunden: {platz_count}")

        # 4 Räume mit data-id
        raumort_count = html.count('data-test="raumort"')
        self.assertEqual(raumort_count, 4, f"Erwartet 4 Räume, gefunden: {raumort_count}")

        # Prüfen, dass alle Platz-Kennungen vorhanden sind
        for kennung in [f"WMC-WP-{i:02d}" for i in range(1, 16)]:
            self.assertIn(kennung, html, f"Platz {kennung} fehlt im HTML")

        # Prüfen, dass alle Raum-Kennungen vorhanden sind
        for kennung in ["STUDIO-TECHNIK", "ACADEMY-TECHNIK", "SERVER-TECHNIK", "EINGANG"]:
            self.assertIn(kennung, html, f"Raum {kennung} fehlt im HTML")

    def test_raumplan_leser_sieht_alle_plaetze(self):
        """F-65: Leser sieht 15 Plätze und 4 Räume im Raumplan."""
        self.client.login(username=self.leser.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()

        platz_count = html.count('data-test="platz"')
        self.assertEqual(platz_count, 15)

        raumort_count = html.count('data-test="raumort"')
        self.assertEqual(raumort_count, 4)

    def test_raumplan_mitarbeiter_erhaelt_403(self):
        """F-112: Mitarbeiter erhält 403 bei /arbeitsplaetze/."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertEqual(antwort.status_code, 403)

    def test_raumplan_plaetze_haben_position(self):
        """F-65: Alle Plätze haben Position (data-x und data-y)."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()

        # Jeder Platz muss data-x und data-y haben
        self.assertIn('data-x="50.1"', html)
        self.assertIn('data-y="55.6"', html)

    def test_raumplan_raume_haben_data_id(self):
        """F-68: Alle Räume haben data-id."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()

        # Jeder Raum muss data-id mit seiner Kennung haben
        for kennung in ["STUDIO-TECHNIK", "ACADEMY-TECHNIK", "SERVER-TECHNIK", "EINGANG"]:
            self.assertIn(f'data-id="{kennung}"', html)


# --- A-0107: Raumplan pflegen (F-67, Teil 2) -----------------------------------

class PlanPflegeTests(TestCase):
    """Raumplan pflegen: Rechte, Upload, Position, ohne Position (F-67).

    TESTSCHNITTSTELLE:
      - Kapitel 1: DATEIABLAGE, Grundriss PNG, JPG, SVG oder erste Seite eines PDF
      - Kapitel 2: Position in Prozent von Breite und Höhe, gemessen am Mittelpunkt
      - Kapitel 3: /arbeitsplaetze/plan/<id>/bearbeiten/ – Admin 200, sonst 403
      - Kapitel 4: ohne Position in „ohne-position“ neben dem Plan
    """

    def setUp(self):
        from stammdaten.models import Plan
        from konten.models import Konto

        self.plan = Plan.objects.create(standort="Eschborn", etage="Erdgeschoss")
        self.ort_mit = Ort.objects.create(
            typ=Ort.TYP_ARBEITSPLATZ, kennung="WMC-WP-01",
            standort="Eschborn", raum="Großraumbüro",
            plan_id=self.plan.id, position_x=30.0, position_y=40.0,
        )
        self.ort_ohne = Ort.objects.create(
            typ=Ort.TYP_ARBEITSPLATZ, kennung="WMC-WP-02",
            standort="Eschborn", raum="Großraumbüro",
            plan_id=self.plan.id,
        )
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.mitarbeiter = konto_erstellen(
            "anna.becker", rolle="mitarbeiter", email="anna.becker@beispiel.test"
        )
        self.admin = konto_erstellen(
            "it-admin", rolle="admin", email="it-admin@beispiel.test"
        )

    @staticmethod
    def _png_datei(name="grundriss.png"):
        import io
        from PIL import Image
        bild = Image.new("RGB", (200, 100), color=(240, 244, 255))
        puffer = io.BytesIO()
        bild.save(puffer, format="PNG")
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, puffer.getvalue(), content_type="image/png")

    @staticmethod
    def _pdf_datei(name="grundriss.pdf"):
        # Minimal-Valides PDF mit einer Seite (300x200).
        datei = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000052 00000 n \n"
            b"0000000101 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n161\n%%EOF\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, datei, content_type="application/pdf")

    def test_admin_erhaelt_200(self):
        """Kapitel 3: Admin sieht die Pflege-Seite mit 200."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/")
        self.assertEqual(antwort.status_code, 200)

    def test_leser_erhaelt_403(self):
        """Kapitel 3: Leser erhält 403."""
        self.client.login(username=self.leser.email, password="test-passwort-123")
        antwort = self.client.get(f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/")
        self.assertEqual(antwort.status_code, 403)

    def test_mitarbeiter_erhaelt_403(self):
        """Kapitel 3: Mitarbeiter erhält 403."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get(f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/")
        self.assertEqual(antwort.status_code, 403)

    def test_upload_png_wird_abgelegt(self):
        """Kapitel 1: PNG wird als Grundriss gespeichert."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/",
            {"grundriss": self._png_datei()},
            follow=True,
        )
        self.assertEqual(antwort.status_code, 200)
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.grundriss, "Grundriss ist leer")
        self.assertTrue(self.plan.grundriss.name.endswith("grundriss.png"),
                        f"Name ist '{self.plan.grundriss.name}', erwartet Ende mit 'grundriss.png'")

    def test_upload_einseitiges_pdf_wird_zum_bild(self):
        """Kapitel 1: Einseitiges PDF wird mit pypdfium2 zum Bild."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/",
            {"grundriss": self._pdf_datei()},
            follow=True,
        )
        self.assertEqual(antwort.status_code, 200)
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.grundriss)
        self.assertTrue(self.plan.grundriss.name.endswith("grundriss.png"))

    def test_position_erscheint_im_raumplan(self):
        """Kapitel 2 und 4: Gespeicherte Position steht als data-x/data-y am platz."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        html = antwort.content.decode()
        self.assertIn('data-x="30"', html)
        self.assertIn('data-y="40"', html)

    @staticmethod
    def _ohne_position_kennungen(html: str) -> list[str]:
        """Kennungen aus dem Abschnitt „ohne-position“ ziehen (Kapitel 4)."""
        if 'data-test="ohne-position"' not in html:
            return []
        start = html.split('data-test="ohne-position"')[1]
        # Ende des Abschnitts suchen: Das nächste data-test-Attribut oder das Ende
        kennungen = []
        import re
        # Suchen alle ort-kennung Werte im Abschnitt
        for match in re.finditer(r'data-test="ort-kennung">([^<]+)</span>', start):
            kennungen.append(match.group(1).strip())
        return kennungen

    def test_ohne_position_erscheint_neben_dem_plan(self):
        """Kapitel 4: Platz ohne Position steht in „ohne-position“."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/arbeitsplaetze/")
        html = antwort.content.decode()
        self.assertIn('data-test="ohne-position"', html)
        kennungen = self._ohne_position_kennungen(html)
        self.assertIn("WMC-WP-02", kennungen)
        self.assertNotIn("WMC-WP-01", kennungen)

    def test_position_wird_im_plan_bearbeiten_gespeichert(self):
        """Kapitel 2: Position wird in Prozent gespeichert und im Plan angezeigt."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/arbeitsplaetze/plan/{self.plan.id}/bearbeiten/",
            {
                "ort": self.ort_ohne.id,
                "x": "55.5",
                "y": "25.0",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.ort_ohne.refresh_from_db()
        self.assertEqual(self.ort_ohne.position_x, 55.5)
        self.assertEqual(self.ort_ohne.position_y, 25.0)

        antwort = self.client.get("/arbeitsplaetze/")
        html = antwort.content.decode()
        self.assertIn('data-x="55.5"', html)
        self.assertIn('data-y="25"', html)
        # Platz ohne Position verschwindet aus „ohne-position“,
        # sobald er eine Position hat.
        kennungen = self._ohne_position_kennungen(html)
        self.assertNotIn("WMC-WP-02", kennungen)


# --- QR-Code und Etiketten (F-12, F-70 bis F-73, F-89) -------------------------

class QRCodeTests(TestCase):
    """F-70: QR-Code je Gerät, Inhalt BASIS_URL + /g/<Inventarnummer>."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.mitarbeiter = konto_erstellen("anna", rolle="mitarbeiter", email="anna.becker@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad"
        )

    def test_detail_traegt_qr_mit_data_qr(self):
        """TESTSCHNITTSTELLE 4: detail trägt qr mit data-qr = BASIS_URL/g/<Inventarnummer>."""
        from django.conf import settings
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        html = antwort.content.decode()
        erwarteter_inhalt = f"{settings.BASIS_URL}/g/{self.gerat.inventarnummer}"
        self.assertIn('data-qr="', html)
        self.assertIn(erwarteter_inhalt, html)
        self.assertIn('<svg', html)

    def test_kurzansicht_admin_weiterleitung(self):
        """F-70: /g/<Inventarnummer> leitet Admin weiter zu /geraete/<Inventarnummer>/."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/g/{self.gerat.inventarnummer}/")
        self.assertEqual(antwort.status_code, 302)
        self.assertIn(f"/geraete/{self.gerat.inventarnummer}/", antwort.headers["Location"])

    def test_kurzansicht_leser_weiterleitung(self):
        """F-70: /g/<Inventarnummer> leitet Leser weiter."""
        self.client.login(username=self.leser.email, password="test-passwort-123")
        antwort = self.client.get(f"/g/{self.gerat.inventarnummer}/")
        self.assertEqual(antwort.status_code, 302)
        self.assertIn(f"/geraete/{self.gerat.inventarnummer}/", antwort.headers["Location"])

    def test_kurzansicht_mitarbeiter_keine_berechtigung(self):
        """F-112: Mitarbeiter erhalten auf /g/<Inventarnummer> 403."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get(f"/g/{self.gerat.inventarnummer}/")
        self.assertEqual(antwort.status_code, 403)

    def test_etikett_drucken_admin_200(self):
        """F-72: /geraete/<Inventarnummer>/etikett/ liefert PDF für Admin."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/etikett/")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertTrue(antwort.content.startswith(b"%PDF"))

    def test_etikett_drucken_leser_200(self):
        """F-72: Leser können Etikett drucken."""
        self.client.login(username=self.leser.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/etikett/")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")

    def test_etikett_drucken_mitarbeiter_403(self):
        """F-112: Mitarbeiter können kein Etikett drucken."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/etikett/")
        self.assertEqual(antwort.status_code, 403)


class EtikettenBogenTests(TestCase):
    """F-72, F-73: Etikettenbogen als PDF, Startposition wählbar."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.mitarbeiter = konto_erstellen("anna", rolle="mitarbeiter", email="anna.becker@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad")
        self.g2 = services.gerat_anlegen(kategorie=self.kat, hersteller="Dell", modell="XPS")
        self.g3 = services.gerat_anlegen(kategorie=self.kat, hersteller="Apple", modell="MacBook")

    def test_bogen_drei_geraete_admin_200(self):
        """F-72: Bogen für 3 ausgewählte Geräte kommt als application/pdf."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        auswahl = ",".join([self.g1.inventarnummer, self.g2.inventarnummer, self.g3.inventarnummer])
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": auswahl, "startposition": "1"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertTrue(antwort.content.startswith(b"%PDF"))

    def test_bogen_startposition_3_felder_davor_frei(self):
        """F-73: Startposition 3 lässt die Felder 1 und 2 frei."""
        from .etiketten import bogen_pdf
        geraete = [self.g1, self.g2, self.g3]
        pdf = bogen_pdf(geraete, startposition=3)
        self.assertTrue(pdf.startswith(b"%PDF"))
        # Ohne Startposition: 3 Etiketten in Feldern 1-3
        pdf_start1 = bogen_pdf(geraete, startposition=1)
        self.assertTrue(pdf_start1.startswith(b"%PDF"))
        # Die PDFs sind unterschiedlich (verschiedene Startpositionen)
        self.assertNotEqual(pdf, pdf_start1)

    def test_bogen_mitarbeiter_403(self):
        """F-112: Mitarbeiter können keinen Bogen drucken."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        auswahl = self.g1.inventarnummer
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": auswahl})
        self.assertEqual(antwort.status_code, 403)

    def test_bogen_leere_auswahl_redirect(self):
        """Leere Auswahl führt zur Geräteliste zurück."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": ""})
        self.assertEqual(antwort.status_code, 302)
        self.assertIn("/geraete/", antwort.headers["Location"])


class EtikettenOrtTests(TestCase):
    """F-89: /etiketten/?ort=<Kennung> druckt Etiketten je Ort, sortiert nach Kennung."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.mitarbeiter = konto_erstellen("anna", rolle="mitarbeiter", email="anna.becker@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen(ort_kennung="WMC-WP-01")
        # Geräte an diesem Ort
        for i, (hersteller, modell) in enumerate([("Lenovo", "ThinkPad"), ("Dell", "XPS"), ("Apple", "MacBook")]):
            services.gerat_anlegen(
                kategorie=self.kat, hersteller=hersteller, modell=modell,
                ort=self.ort,
            )

    def test_etiketten_ort_admin_200(self):
        """F-89: /etiketten/?ort=<Kennung> für Admin mit 200."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/etiketten/", {"ort": "WMC-WP-01"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertTrue(antwort.content.startswith(b"%PDF"))

    def test_etiketten_ort_leser_403(self):
        """F-89: /etiketten/ für Leser mit 403 (Keine Berechtigung)."""
        self.client.login(username=self.leser.email, password="test-passwort-123")
        antwort = self.client.get("/etiketten/", {"ort": "WMC-WP-01"})
        self.assertEqual(antwort.status_code, 403)
        self.assertIn("Keine Berechtigung", antwort.content.decode())
        # Auch die Auswahlseite bleibt für den Leser 403.
        antwort2 = self.client.get("/etiketten/")
        self.assertEqual(antwort2.status_code, 403)
        antwort3 = self.client.get("/etiketten/auswahl/")
        self.assertEqual(antwort3.status_code, 403)

    def test_etiketten_ort_mitarbeiter_403(self):
        """F-89: /etiketten/ für Mitarbeiter mit 403."""
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.get("/etiketten/", {"ort": "WMC-WP-01"})
        self.assertEqual(antwort.status_code, 403)

    def test_etiketten_ort_admin_auswahlseite(self):
        """F-89: /etiketten/ ohne Parameter zeigt für Admin die Auswahl der Orte."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/etiketten/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertIn('data-test="etiketten-ort-auswahl"', html)
        self.assertIn('value="WMC-WP-01"', html)
        self.assertIn('data-test="startposition"', html)
        self.assertIn('data-test="etiketten-drucken"', html)


class SpeichernUndEtikettTests(TestCase):
    """F-12: „Speichern und Etikett drucken“ anlegt das Gerät und liefert das PDF."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()

    def test_speichern_und_etikett_drucken(self):
        """F-12: Gerät wird angelegt und PDF geliefert."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Lenovo",
                "modell": "ThinkPad",
                "zustand": 1,
                "aktion": "etikett",
            },
        )
        # PDF geliefert
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertTrue(antwort.content.startswith(b"%PDF"))
        # Gerät angelegt
        self.assertTrue(Gerat.objects.filter(hersteller="Lenovo", modell="ThinkPad").exists())

    def test_speichern_ohne_etikett_redirect(self):
        """Ohne „aktion=etikett" wird zum Detail weitergeleitet."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Dell",
                "modell": "XPS",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.assertIn("/geraete/", antwort.headers["Location"])
        self.assertTrue(Gerat.objects.filter(hersteller="Dell", modell="XPS").exists())


class ListEtikettenTests(TestCase):
    """F-72: Liste trägt auswahl je Zeile und etiketten-drucken."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad")
        self.g2 = services.gerat_anlegen(kategorie=self.kat, hersteller="Dell", modell="XPS")

    def test_liste_traegt_auswahl_und_etiketten_drucken(self):
        """Die Liste hat auswahl-Checkboxen und einen etiketten-drucken-Button."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/geraete/")
        html = antwort.content.decode()
        self.assertIn('data-test="auswahl"', html)
        self.assertIn('data-test="etiketten-drucken"', html)
        self.assertIn('data-test="startposition"', html)
        self.assertIn(f'name="auswahl" value="{self.g1.inventarnummer}"', html)
        self.assertIn(f'name="auswahl" value="{self.g2.inventarnummer}"', html)

    def test_detail_traegt_aktion_etikett(self):
        """F-72: Detail trägt aktion-etikett für Admin."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.g1.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-test="aktion-etikett"', html)
        self.assertIn(f"/geraete/{self.g1.inventarnummer}/etikett/", html)


# --- M4 Teil 4: Notiz am Gerät und Geprüft (F-74, F-16) -----------------------


class NotizGeratTests(TestCase):
    """F-74, A-0111 Teil 4: Notiz am Gerät (TESTSCHNITTSTELLE Kapitel 4).

    Dialog ``data-name="notiz"`` mit ``speichern``. Die Notiz steht
    danach am Gerät.
    """

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad")

    def _anmelden(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")

    def test_detail_traegt_aktion_notiz(self):
        """F-74: Detail trägt aktion-notiz für Admin."""
        self._anmelden()
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-test="aktion-notiz"', html)
        self.assertIn(f"/geraete/{self.gerat.inventarnummer}/notiz/", html)

    def test_notiz_dialog_oeffnet_mit_feld_und_speichern(self):
        """TESTSCHNITTSTELLE Kapitel 4: dialog data-name=notiz mit speichern."""
        self._anmelden()
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/notiz/")
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertIn('data-test="dialog" data-name="notiz"', html)
        self.assertIn('data-test="speichern"', html)
        self.assertIn('data-test="notiz-feld"', html)

    def test_notiz_speichern_stellt_notiz_am_gerat(self):
        """F-74: Notiz speichern → Notiz steht am Gerät."""
        self._anmelden()
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/notiz/",
            {"notiz": "Akku schwach, Ersatz bestellt"},
        )
        self.assertEqual(antwort.status_code, 302)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.notiz, "Akku schwach, Ersatz bestellt")
        # Die Notiz steht am Gerät: Detail zeigt sie an.
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        self.assertIn("Akku schwach, Ersatz bestellt", antwort.content.decode())

    def test_notiz_leer_aeustern_loescht_notiz(self):
        """F-74: Leere Notiz speichern entfernt den alten Text."""
        self._anmelden()
        self.gerat.notiz = "Alter Text"
        self.gerat.save(update_fields=["notiz"])
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/notiz/",
            {"notiz": ""},
        )
        self.assertEqual(antwort.status_code, 302)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.notiz, "")


class GeprueftButtonTests(TestCase):
    """F-16, A-0111 Teil 4: „Geprüft“ setzt „Zuletzt geprüft“.

    TESTSCHNITTSTELLE Kapitel 4: ``geprueft``-Button im Detail.
    Abnahme: Geprüft an einem Gerät von WMC-WP-01 setzt „Zuletzt
    geprüft“ und erhöht inventur-fortschritt um eins.
    """

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad", ort=self.ort
        )

    def _anmelden(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")

    def test_detail_traegt_geprueft_button(self):
        """F-74: Detail trägt geprueft-Button für Admin."""
        self._anmelden()
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-test="geprueft"', html)
        self.assertIn("Geprüft", html)

    def test_geprueft_setzt_zuletzt_geprueft(self):
        """F-16: Geprüft setzt „Zuletzt geprüft“ (Datum + Benutzer)."""
        self._anmelden()
        self.gerat.refresh_from_db()
        self.assertIsNone(self.gerat.zuletzt_geprueft_am)
        antwort = self.client.post(f"/geraete/{self.gerat.inventarnummer}/pruefen/")
        self.assertEqual(antwort.status_code, 302)
        self.gerat.refresh_from_db()
        self.assertIsNotNone(self.gerat.zuletzt_geprueft_am)
        self.assertEqual(str(self.gerat.zuletzt_geprueft_von), "it-admin@beispiel.test")

    def test_geprueft_erhoht_fortschritt_orts(self):
        """F-16: Geprüft erhöht inventur-fortschritt des Ortes um eins."""
        self._anmelden()
        vorher = services.fortschritt_des_orts(self.ort.pk)
        gezaehlt_vorher = vorher["geprueft"]
        antwort = self.client.post(f"/geraete/{self.gerat.inventarnummer}/pruefen/")
        self.assertEqual(antwort.status_code, 302)
        nachher = services.fortschritt_des_orts(self.ort.pk)
        self.assertEqual(nachher["geprueft"], gezaehlt_vorher + 1)


# --- A-0112: F-40, F-11, F-13 -------------------------------------------------


class AenderungsHistorieTests(TestCase):
    """F-40, A-0112: Eine Änderung über /geraete/<Nr>/aendern/ legt einen
    Vorgang „Änderung“ an, mit altem und neuem Wert als Text in der Historie.
    """

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad")

    def _anmelden(self, rolle="admin"):
        if rolle == "admin":
            self.client.login(username=self.admin.email, password="test-passwort-123")
        else:
            self.client.login(username=self.leser.email, password="test-passwort-123")

    def test_aendern_zeugt_vorgang_aenderung_mit_alt_neu(self):
        """F-40: Änderung des Herstellers erzeugt einen Vorgang „Änderung“
        mit altem und neuem Wert, beide als Text sichtbar."""
        self._anmelden()
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/aendern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "HP",
                "modell": "ThinkPad",
                "seriennummer": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        # Der Vorgang existiert und hat Typ „Änderung“.
        vorgang = Vorgang.objects.filter(
            gerat=self.gerat, typ=Vorgang.TYP_AENDERUNG
        ).first()
        self.assertIsNotNone(vorgang, "Kein Vorgang „Änderung“ angelegt.")
        self.assertEqual(vorgang.aenderung_feld, "hersteller")
        self.assertEqual(vorgang.aenderung_alter_wert, "Lenovo")
        self.assertEqual(vorgang.aenderung_neuer_wert, "HP")
        # In der Historie im Detail: altes und neues Wert stehen als Text.
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-typ="Änderung"', html)
        self.assertIn('data-feld="hersteller"', html)
        self.assertIn('data-alt="Lenovo"', html)
        self.assertIn('data-neu="HP"', html)
        # Auch als sichtbarer Text, nicht nur in data-Attributen.
        self.assertIn("hersteller: Lenovo → HP", html)

    def test_aendern_kein_vorgang_wenn_kein_feld_geaendert(self):
        """F-40: Gibt man denselben Wert ein, entsteht kein neuer Vorgang."""
        self._anmelden()
        vorher = self.gerat.vorgaenge.filter(typ=Vorgang.TYP_AENDERUNG).count()
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/aendern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Lenovo",
                "modell": "ThinkPad",
                "seriennummer": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        nachher = self.gerat.vorgaenge.filter(typ=Vorgang.TYP_AENDERUNG).count()
        self.assertEqual(nachher, vorher)

    def test_aendern_leser_erhaelt_403(self):
        """F-40: Leser kann nicht ändern; die Ansicht antwortet mit 403."""
        self._anmelden(rolle="leser")
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/aendern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "HP",
                "modell": "ThinkPad",
                "seriennummer": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 403)
        # Kein neuer „Änderung“-Vorgang.
        self.assertEqual(
            self.gerat.vorgaenge.filter(typ=Vorgang.TYP_AENDERUNG).count(), 0
        )


class MehrfacherfassungTests(TestCase):
    """F-11, A-0112: Zeilenweise Seriennummern in ``seriennummern`` erzeugen
    so viele Geräte wie Zeilen, je mit eigener Inventarnummer und Vorgang
    Aufnahme."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()

    def _anmelden(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")

    def test_drei_zeilen_erzeugen_drei_geraete(self):
        """F-11: Drei Zeilen in seriennummern → drei Geräte, je mit eigener
        Inventarnummer und Vorgang Aufnahme."""
        self._anmelden()
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Lenovo",
                "modell": "ThinkPad",
                "seriennummer": "",
                "seriennummern": "SN-001\nSN-002\nSN-003",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.assertIn("/geraete/", antwort.headers["Location"])
        # Drei Geräte mit den drei Seriennummern.
        gerate = Gerat.objects.filter(hersteller="Lenovo", modell="ThinkPad").order_by("inventarnummer")
        self.assertEqual(gerate.count(), 3)
        serien = sorted(g.seriennummer for g in gerate)
        self.assertEqual(serien, ["SN-001", "SN-002", "SN-003"])
        # Jedes Gerät hat einen eigenen Vorgang Aufnahme.
        for g in gerate:
            aufnahme = g.vorgaenge.filter(typ=Vorgang.TYP_AUFNAHME)
            self.assertEqual(aufnahme.count(), 1, f"Gerät {g.inventarnummer} hat keinen Aufnahme-Vorgang.")

    def test_leere_zeilen_werden_verworfen(self):
        """F-11: Leere Zeilen in seriennummern werden verworfen."""
        self._anmelden()
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Lenovo",
                "modell": "ThinkPad",
                "seriennummer": "",
                "seriennummern": "SN-001\n\n  \nSN-002",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        gerate = Gerat.objects.filter(hersteller="Lenovo", modell="ThinkPad")
        self.assertEqual(gerate.count(), 2)

    def test_ohne_seriennummern_ein_geraet(self):
        """F-11: Ohne Seriennummern entsteht ein Gerät wie bisher."""
        self._anmelden()
        vorher = Gerat.objects.count()
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Dell",
                "modell": "XPS",
                "seriennummer": "",
                "seriennummern": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(Gerat.objects.count(), vorher + 1)

    def test_seriennummer_einzel_feld_funktioniert_noch(self):
        """F-11: Das Einzel-Feld seriennummer funktioniert noch."""
        self._anmelden()
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "Apple",
                "modell": "MacBook",
                "seriennummer": "SN-SINGLE-01",
                "seriennummern": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 302)
        gerat = Gerat.objects.filter(seriennummer="SN-SINGLE-01").first()
        self.assertIsNotNone(gerat)
        self.assertEqual(gerat.vorgaenge.filter(typ=Vorgang.TYP_AUFNAHME).count(), 1)


class VorlageTests(TestCase):
    """F-13, A-0112: /geraete/neu/?vorlage=<Inventarnummer> übernimmt die
    Stammdaten des Geräts; die Seriennummer bleibt leer."""

    def setUp(self):
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.leser = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.vorlage = services.gerat_anlegen(
            kategorie=self.kat,
            hersteller="Lenovo",
            modell="ThinkPad",
            seriennummer="SN-ORIGINAL",
            geraetename="Pool-A",
        )

    def _anmelden(self, rolle="admin"):
        if rolle == "admin":
            self.client.login(username=self.admin.email, password="test-passwort-123")
        else:
            self.client.login(username=self.leser.email, password="test-passwort-123")

    def test_vorlage_uebernaehmt_stammdaten(self):
        """F-13: ?vorlage=<Nr> zeigt Hersteller und Modell vorbelegt."""
        self._anmelden()
        antwort = self.client.get("/geraete/neu/", {"vorlage": self.vorlage.inventarnummer})
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        # Hersteller und Modell stehen im Formular.
        self.assertIn("Lenovo", html)
        self.assertIn("ThinkPad", html)
        # Das Feld seriennummer ist leer (kein value="SN-ORIGINAL").
        self.assertNotIn('value="SN-ORIGINAL"', html)

    def test_vorlage_detail_traegt_aktion_vorlage(self):
        """F-13: Das Gerätedetail trägt aktion-vorlage für Admin."""
        self._anmelden()
        antwort = self.client.get(f"/geraete/{self.vorlage.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-test="aktion-vorlage"', html)
        self.assertIn(f"/geraete/neu/?vorlage={self.vorlage.inventarnummer}", html)

    def test_neu_fuer_leser_403(self):
        """F-11: /geraete/neu/ für gf@beispiel.test mit 403 antwortet."""
        self._anmelden(rolle="leser")
        antwort = self.client.get("/geraete/neu/")
        self.assertEqual(antwort.status_code, 403)

    def test_neu_anlegen_fuer_leser_403(self):
        """F-11: POST auf /geraete/speichern/ für Leser → 403, kein Gerät."""
        self._anmelden(rolle="leser")
        vorher = Gerat.objects.count()
        antwort = self.client.post(
            "/geraete/speichern/",
            {
                "kategorie": self.kat.pk,
                "hersteller": "HP",
                "modell": "EliteBook",
                "seriennummer": "",
                "seriennummern": "",
                "zustand": 2,
            },
        )
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(Gerat.objects.count(), vorher)


# --- M5 Verleih (F-30, F-36, F-133) ---------------------------------------------

class VerleihServiceTests(TestCase):
    """Tests für die Verleih-Service-Funktionen (F-30, F-36, F-133)."""

    def setUp(self):
        self.kat, self.ort, self.person = stammdaten_erstellen()
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad",
            seriennummer="SN-LEIH-01",
        )

    def test_leihe_erstellen(self):
        """F-30: Verleih erstellt eine Leihe mit Status 'ausgegeben'."""
        from .models import Leihe, Protokoll

        rueckgabe = date(2026, 11, 15)
        leihe = services.leih_gerat_ausgeben(
            gerat=self.gerat, person=self.person, rueckgabe_bis=rueckgabe,
            zweck="Präsentation", ausgefuehrt_von=self.admin,
        )
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)
        self.assertEqual(self.gerat.status, Gerat.STATUS_VERLIEHEN)

    def test_leihe_rueckgeben(self):
        """F-133: Rückgabe setzt Leihe auf 'zurueckgegeben' und Gerät auf 'Auf Lager'."""
        from .models import Leihe
        from datetime import date

        rueckgabe = date(2026, 11, 15)
        leihe = services.leih_gerat_ausgeben(
            gerat=self.gerat, person=self.person, rueckgabe_bis=rueckgabe,
            zweck="Präsentation", ausgefuehrt_von=self.admin,
        )
        services.leihe_zurueckgeben(leihe, ausgefuehrt_von=self.admin)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEGEBEN)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_leihe_ueberfaellig(self):
        """F-36: Leihe mit überfälligem Rückgabedatum wird erkannt."""
        from .models import Leihe
        from datetime import date, timedelta
        from konten.zeit import jetzt_wie_im_entwicklungsmodus

        # Rückgabedatum in der Vergangenheit
        rueckgabe = date(2026, 10, 1)
        leihe = services.leih_gerat_ausgeben(
            gerat=self.gerat, person=self.person, rueckgabe_bis=rueckgabe,
            zweck="Präsentation", ausgefuehrt_von=self.admin,
        )
        ueberfaellige = list(services.leihen_ueberfaellig())
        self.assertEqual(len(ueberfaellige), 1)
        self.assertEqual(ueberfaellige[0].id, leihe.id)


class VerleihViewTests(TestCase):
    """Tests für die Verleih-Views (F-36, TESTSCHNITTSTELLE 3)."""

    def setUp(self):
        self.kat, self.ort, self.person = stammdaten_erstellen(
            person_email="anna.becker@beispiel.test"
        )
        self.admin = konto_erstellen("it-admin", rolle="admin", email="it-admin@beispiel.test")
        self.gf = konto_erstellen("gf", rolle="leser", email="gf@beispiel.test")
        self.anna = konto_erstellen(
            "anna-becker", rolle="mitarbeiter", email="anna.becker@beispiel.test"
        )
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad",
            seriennummer="SN-LEIH-02",
        )

    def test_verleih_liste_admin_200(self):
        """F-36: /verleih/ für it-admin@beispiel.test mit 200 antwortet."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get("/verleih/")
        self.assertEqual(antwort.status_code, 200)

    def test_verleih_liste_mitarbeiter_403(self):
        """F-36: /verleih/ für anna.becker@beispiel.test mit 403 antwortet."""
        self.client.login(username=self.anna.email, password="test-passwort-123")
        antwort = self.client.get("/verleih/")
        self.assertEqual(antwort.status_code, 403)

    def test_verleih_liste_leser_403(self):
        """F-36: /verleih/ für gf@beispiel.test mit 403 antwortet."""
        self.client.login(username=self.gf.email, password="test-passwort-123")
        antwort = self.client.get("/verleih/")
        self.assertEqual(antwort.status_code, 403)

    def test_verleih_dialog_admin(self):
        """F-30: Verleih-Dialog zeigt sich für Admin am Gerätedetail."""
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/geraete/{self.gerat.inventarnummer}/")
        html = antwort.content.decode()
        self.assertIn('data-test="aktion-verleih"', html)

    def test_verleih_dialog_post(self):
        """F-30: POST auf /geraete/<nr>/verleih/ verleih das Gerät."""
        from .models import Leihe, Protokoll
        from datetime import date

        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/geraete/{self.gerat.inventarnummer}/verleih/",
            {
                "person": self.person.pk,
                "rueckgabe_bis": "2026-11-15",
                "zweck": "Präsentation",
            },
        )
        self.assertEqual(antwort.status_code, 302)
        leihe = Leihe.objects.filter(gerat=self.gerat).first()
        self.assertIsNotNone(leihe)
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_VERLIEHEN)
        protokoll = Protokoll.objects.filter(geraet=self.gerat).first()
        self.assertIsNotNone(protokoll)
        self.assertEqual(protokoll.stand, Protokoll.STAND_SCAN_OFFEN)


# ---------------------------------------------------------------------------
# M5 Teil 2: Anfrage und Entscheidung
# ---------------------------------------------------------------------------

class LeiheAnfrageServiceTests(TestCase):
    """F-31: Mitarbeiter fragt ein Leihgerät an."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.admin = konto_erstellen("admin", "admin")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()
        self.beginn = date(2026, 11, 2)
        self.ende = date(2026, 11, 10)

    def test_anfrage_ohne_gerat(self):
        leihe = leihe_anfragen(
            person=self.person,
            kat=self.kategorie,
            beginn=self.beginn,
            ende=self.ende,
            zweck="Vorführung",
            gerat=None,
            erzeugt_von=self.mitarbeiter,
        )
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)
        self.assertIsNone(leihe.gerat)
        self.assertEqual(leihe.zweck, "Vorführung")

    def test_anfrage_mit_gerat(self):
        leihe = leihe_anfragen(
            person=self.person,
            kat=self.kategorie,
            beginn=self.beginn,
            ende=self.ende,
            zweck="Vorführung",
            gerat=self.gerat,
            erzeugt_von=self.mitarbeiter,
        )
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)
        self.assertEqual(leihe.gerat, self.gerat)

    def test_anfrage_gerat_nicht_im_leihpool(self):
        self.gerat.leihpool = False
        self.gerat.save()
        with self.assertRaises(GeratFehler):
            leihe_anfragen(
                person=self.person,
                kat=self.kategorie,
                beginn=self.beginn,
                ende=self.ende,
                zweck="Test",
                gerat=self.gerat,
                erzeugt_von=self.mitarbeiter,
            )


class LeiheEntscheidungServiceTests(TestCase):
    """F-32, F-34: IT genehmigt oder lehnt ab."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.admin = konto_erstellen("admin", "admin")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()
        self.beginn = date(2026, 11, 2)
        self.ende = date(2026, 11, 10)

    def _anfrage_erstellen(self, beginn=None, ende=None):
        return leihe_anfragen(
            person=self.person,
            kat=self.kategorie,
            beginn=beginn or self.beginn,
            ende=ende or self.ende,
            zweck="Test",
            gerat=None,
            erzeugt_von=self.mitarbeiter,
        )

    def test_genehmigen(self):
        leihe = self._anfrage_erstellen()
        leihe_genehmigen(
            leihe, gerat=self.gerat, ausgefuehrt_von=self.admin
        )
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_GENEHMIGT)
        self.assertEqual(leihe.gerat, self.gerat)
        self.gerat.refresh_from_db()
        self.assertTrue(self.gerat.reserviert)

    def test_ablehnen_mit_begrundung(self):
        leihe = self._anfrage_erstellen()
        leihe_ablehnen(
            leihe, begruendung="Kein Gerät verfügbar", ausgefuehrt_von=self.admin
        )
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ABGELEHNT)
        self.assertTrue(leihe.abgelehnt)
        self.assertEqual(leihe.abgelehnt_bis, "Kein Gerät verfügbar")

    def test_ablehnen_ohne_begrundung_scheitert(self):
        leihe = self._anfrage_erstellen()
        with self.assertRaises(GeratFehler):
            leihe_ablehnen(leihe, begruendung="", ausgefuehrt_von=self.admin)

    def test_ueberschneidung_lehnt_ab(self):
        """F-34: Zweites Genehmigen desselben Geräts im selben Zeitraum."""
        leihe1 = self._anfrage_erstellen()
        leihe_genehmigen(
            leihe1, gerat=self.gerat, ausgefuehrt_von=self.admin
        )
        leihe2 = self._anfrage_erstellen()
        with self.assertRaises(GeratFehler):
            leihe_genehmigen(
                leihe2, gerat=self.gerat, ausgefuehrt_von=self.admin
            )


class LeiheZurueckziehenServiceTests(TestCase):
    """F-37: Mitarbeiter zieht die Leihe zurück."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.admin = konto_erstellen("admin", "admin")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()
        self.beginn = date(2026, 11, 2)
        self.ende = date(2026, 11, 10)

    def _anfrage_erstellen(self):
        return leihe_anfragen(
            person=self.person,
            kat=self.kategorie,
            beginn=self.beginn,
            ende=self.ende,
            zweck="Test",
            gerat=None,
            erzeugt_von=self.mitarbeiter,
        )

    def test_zurueckziehen_angefragt(self):
        leihe = self._anfrage_erstellen()
        leihe_zurueckziehen(leihe, ausgefuehrt_von=self.mitarbeiter)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)

    def test_zurueckziehen_genehmigt_hebt_reservierung_auf(self):
        leihe = self._anfrage_erstellen()
        leihe_genehmigen(
            leihe, gerat=self.gerat, ausgefuehrt_von=self.admin
        )
        self.gerat.refresh_from_db()
        self.assertTrue(self.gerat.reserviert)
        leihe_zurueckziehen(leihe, ausgefuehrt_von=self.mitarbeiter)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)


class LeiheAnfrageViewTests(TestCase):
    """F-31: /geraete/meine-geraete/leihe/neu/ für Mitarbeiter."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.client.force_login(self.mitarbeiter)
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()

    def test_leihe_neu_antwortet_200(self):
        answer = self.client.get("/geraete/meine-geraete/leihe/neu/")
        self.assertEqual(answer.status_code, 200)
        self.assertContains(answer, "Leihe anfragen")

    def test_leihe_neu_zeigt_freie_geraete(self):
        answer = self.client.get("/geraete/meine-geraete/leihe/neu/")
        self.assertContains(answer, "freie")

    def test_admin_darf_nicht(self):
        admin = konto_erstellen("admin", "admin")
        self.client.force_login(admin)
        answer = self.client.get("/geraete/meine-geraete/leihe/neu/")
        self.assertEqual(answer.status_code, 403)

    def test_anfrage_wird_erstellt(self):
        answer = self.client.post("/geraete/meine-geraete/leihe/neu/", {
            "kat": self.kategorie.id,
            "beginn": "2026-11-02",
            "ende": "2026-11-10",
            "zweck": "Vorführung",
        })
        self.assertEqual(answer.status_code, 302)
        leihe = Leihe.objects.filter(person=self.person).first()
        self.assertIsNotNone(leihe)
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)


class LeiheEntscheidungViewTests(TestCase):
    """F-32: Genehmigen und Ablehnen über die Ansicht."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.admin = konto_erstellen("admin", "admin")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()
        self.leihe = Leihe.objects.create(
            kat=self.kategorie,
            beginn=date(2026, 11, 2),
            ende=date(2026, 11, 10),
            zweck="Test",
            person=self.person,
            status=Leihe.STATUS_ANGEFRAGT,
        )

    def test_genehmigen_ansicht(self):
        self.client.force_login(self.admin)
        answer = self.client.post(
            f"/geraete/verleih/{self.leihe.id}/genehmigen/",
            {"gerat": self.gerat.id},
        )
        self.assertEqual(answer.status_code, 302)
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.status, Leihe.STATUS_GENEHMIGT)

    def test_ablehnen_ohne_begrundung_nicht_gespeichert(self):
        self.client.force_login(self.admin)
        answer = self.client.post(
            f"/geraete/verleih/{self.leihe.id}/ablehnen/",
            {"begründung": ""},
        )
        self.assertEqual(answer.status_code, 200)
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.status, Leihe.STATUS_ANGEFRAGT)

    def test_mitarbeiter_darf_nicht_genehmigen(self):
        self.client.force_login(self.mitarbeiter)
        answer = self.client.get(
            f"/geraete/verleih/{self.leihe.id}/genehmigen/"
        )
        self.assertEqual(answer.status_code, 403)


class LeiheZurueckziehenViewTests(TestCase):
    """F-37: Zurückziehen über die Ansicht."""

    def setUp(self):
        self.kategorie, self.ablage, self.person = stammdaten_erstellen()
        self.mitarbeiter = konto_erstellen("anna", "mitarbeiter")
        self.admin = konto_erstellen("admin", "admin")
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie, hersteller="Lenovo", modell="ThinkPad"
        )
        self.gerat.leihpool = True
        self.gerat.save()
        self.leihe = Leihe.objects.create(
            kat=self.kategorie,
            beginn=date(2026, 11, 2),
            ende=date(2026, 11, 10),
            zweck="Test",
            person=self.person,
            status=Leihe.STATUS_ANGEFRAGT,
        )

    def test_zurueckziehen_angefragt(self):
        self.client.force_login(self.mitarbeiter)
        answer = self.client.post(
            f"/geraete/meine-geraete/leihe/{self.leihe.id}/zurueckziehen/",
            {"bestätigung": "on"},
        )
        self.assertEqual(answer.status_code, 302)
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)

    def test_zurueckziehen_genehmigt_hebt_reservierung_auf(self):
        leihe_genehmigen(
            self.leihe, gerat=self.gerat, ausgefuehrt_von=self.admin
        )
        self.gerat.refresh_from_db()
        self.assertTrue(self.gerat.reserviert)
        self.client.force_login(self.mitarbeiter)
        answer = self.client.post(
            f"/geraete/meine-geraete/leihe/{self.leihe.id}/zurueckziehen/",
            {"bestätigung": "on"},
        )
        self.assertEqual(answer.status_code, 302)
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_admin_darf_nicht_zurueckziehen(self):
        self.client.force_login(self.admin)
        answer = self.client.get(
            f"/geraete/meine-geraete/leihe/{self.leihe.id}/zurueckziehen/"
        )
        self.assertEqual(answer.status_code, 403)
