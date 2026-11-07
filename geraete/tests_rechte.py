"""Rechte je Rolle gegen die Tabelle aus TESTSCHNITTSTELLE Kapitel 3 (Kapitel 2, F-112, N-02).

Diese Tests stehen eigens für die Prüfung vom 05.11.2026: Vorher durfte ein Mitarbeiter
Geräte anlegen, ändern und ausmustern, und die alten Tests hielten das für richtig.
"""
from __future__ import annotations

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from geraete.models import Gerat, Protokoll
from konten.models import Konto
from stammdaten.models import Kategorie, Person


@override_settings(DEBUG=True)
class RechteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("beispieldaten", verbosity=0, stdout=open("/dev/null", "w"))
        cls.admin = Konto.objects.get(email="it-admin@beispiel.test")
        cls.mitarbeiter = Konto.objects.get(email="anna.becker@beispiel.test")
        cls.leser = Konto.objects.filter(rolle=Konto.ROLLE_LESER).first()
        cls.maus = Kategorie.objects.get(name="Maus")
        cls.felix = Person.objects.get(nachname="Hoffmann")
        from django.utils import timezone
        cls.gerat = Gerat.objects.create(
            inventarnummer="WMC-08001", kategorie=cls.maus, hersteller="H", modell="M",
            status=Gerat.STATUS_AUF_LAGER, kaufpreis_netto=500,
            erstellt_von=cls.admin, erstellt_am=timezone.now(),
        )

    def _client(self, konto=None):
        c = Client(HTTP_HOST="127.0.0.1", raise_request_exception=False)
        if konto is not None:
            c.force_login(konto)
        return c

    def test_tabelle_kapitel_3(self):
        nr = self.gerat.inventarnummer
        tabelle = [
            ("/", 200, 200, 302),
            ("/geraete/", 200, 200, 403),
            (f"/geraete/{nr}/", 200, 200, 403),
            ("/geraete/?format=csv", 200, 200, 403),
            ("/geraete/neu/", 200, 403, 403),
            ("/import/", 200, 403, 403),
            ("/etiketten/", 200, 403, 403),
            ("/einstellungen/", 200, 403, 403),
            ("/arbeitsplaetze/", 200, 200, 403),
            ("/personen/", 200, 200, 403),
            ("/verleih/", 200, 403, 403),
            ("/exporte/?liste=garantie&format=csv", 200, 200, 403),
        ]
        for pfad, admin, leser, mitarbeiter in tabelle:
            with self.subTest(pfad=pfad):
                self.assertEqual(self._client(self.admin).get(pfad).status_code, admin, "Admin")
                self.assertEqual(self._client(self.leser).get(pfad).status_code, leser, "Leser")
                self.assertEqual(self._client(self.mitarbeiter).get(pfad).status_code, mitarbeiter, "Mitarbeiter")

    def test_403_zeigt_keine_berechtigung(self):
        antwort = self._client(self.mitarbeiter).get(f"/geraete/{self.gerat.inventarnummer}/")
        self.assertEqual(antwort.status_code, 403)
        html = antwort.content.decode()
        self.assertIn('data-test="keine-berechtigung"', html)
        self.assertNotIn("500", html)

    def test_vorgaenge_nur_admin(self):
        nr = self.gerat.inventarnummer
        vorgaenge = [
            ("/geraete/speichern/", {"kategorie": self.maus.pk, "hersteller": "H", "modell": "neu", "zustand": 2}),
            (f"/geraete/{nr}/aendern/", {"kategorie": self.maus.pk, "hersteller": "X", "modell": "M", "zustand": 1}),
            (f"/geraete/{nr}/ausmustern/", {"grund": "defekt", "datum": "2026-11-05", "disposition": "Müll"}),
            (f"/geraete/{nr}/ausgeben/", {"ziel_person": self.felix.pk, "zustand": 2, "zubehoer_komplett": "ja", "unterschrift": "papier"}),
            (f"/geraete/{nr}/rueckgeben/", {"zustand_rueckgabe": 2, "zubehoer_komplett": "ja", "ziel": "lager"}),
            (f"/geraete/{nr}/umziehen/", {"ziel_ort": 1}),
            (f"/geraete/{nr}/reparatur/start/", {"dienstleister": "D", "vorgangsnummer": "V"}),
            (f"/geraete/{nr}/notiz/", {"notiz": "x"}),
            (f"/geraete/{nr}/pruefen/", {}),
        ]
        anzahl = Gerat.objects.count()
        for konto in (self.mitarbeiter, self.leser):
            c = self._client(konto)
            for pfad, daten in vorgaenge:
                with self.subTest(konto=konto.email, pfad=pfad):
                    self.assertEqual(c.post(pfad, daten).status_code, 403)
        self.gerat.refresh_from_db()
        self.assertEqual(Gerat.objects.count(), anzahl)
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(self.gerat.hersteller, "H")
        self.assertIsNone(self.gerat.zuletzt_geprueft_am)

    def test_protokoll_schreiben_nur_admin(self):
        from django.utils import timezone
        p = Protokoll.objects.create(
            nr="UP-2026-9001", art=Protokoll.ART_AUSGABE, geraet=self.gerat,
            person=self.mitarbeiter.person, stand=Protokoll.STAND_BEARBEITER_OFFEN,
            erzeugt_von=self.admin, datum=timezone.now().date(),
        )
        for konto in (self.mitarbeiter, self.leser):
            c = self._client(konto)
            self.assertEqual(c.get(f"/protokolle/{p.nr}/").status_code, 200, konto.email)
            for rest in ("scan", "foto", "checkliste", "offboarding", "signieren", "abbrechen", "code-senden", "link-neu-senden", "korrigieren"):
                with self.subTest(konto=konto.email, rest=rest):
                    self.assertEqual(c.post(f"/protokolle/{p.nr}/{rest}/", {}).status_code, 403)
        self.assertTrue(Protokoll.objects.filter(nr=p.nr).exists())

    def test_fremdes_protokoll_403(self):
        from django.utils import timezone
        p = Protokoll.objects.create(
            nr="UP-2026-9002", art=Protokoll.ART_AUSGABE, geraet=self.gerat,
            person=self.felix, stand=Protokoll.STAND_BEARBEITER_OFFEN,
            erzeugt_von=self.admin, datum=timezone.now().date(),
        )
        self.assertEqual(self._client(self.mitarbeiter).get(f"/protokolle/{p.nr}/").status_code, 403)

    def test_ohne_anmeldung_leitet_um(self):
        c = self._client()
        for pfad in ("/", "/geraete/", "/personen/", "/konten/", "/einstellungen/", "/import/", "/orte/", "/verleih/"):
            with self.subTest(pfad=pfad):
                antwort = c.get(pfad)
                self.assertEqual(antwort.status_code, 302)
                self.assertTrue(antwort["Location"].startswith("/anmelden/?next="), antwort["Location"])
        for pfad in ("/anmelden/", "/passwort-vergessen/"):
            self.assertEqual(c.get(pfad).status_code, 200, pfad)

    def test_anmeldung_folgt_next(self):
        c = self._client()
        self.admin.set_password("Passwort-fuer-den-Test-1")
        self.admin.save()
        antwort = c.post("/anmelden/", {"email": "IT-Admin@beispiel.test", "passwort": "Passwort-fuer-den-Test-1", "next": f"/g/{self.gerat.inventarnummer}"})
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort["Location"], f"/g/{self.gerat.inventarnummer}")

    def test_anmeldung_folgt_keinem_fremden_ziel(self):
        c = self._client()
        self.admin.set_password("Passwort-fuer-den-Test-1")
        self.admin.save()
        antwort = c.post("/anmelden/", {"email": self.admin.email, "passwort": "Passwort-fuer-den-Test-1", "next": "https://boese.example/"})
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort["Location"], "/")

    def test_deaktiviertes_konto_verliert_die_sitzung(self):
        c = self._client(self.mitarbeiter)
        self.assertEqual(c.get("/meine-geraete/").status_code, 200)
        Konto.objects.filter(pk=self.mitarbeiter.pk).update(aktiv=False)
        antwort = c.get("/meine-geraete/")
        self.assertEqual(antwort.status_code, 302)
        self.assertIn("/anmelden/", antwort["Location"])

    def test_rahmen_marker(self):
        c = self._client(self.admin)
        html = c.get("/").content.decode()
        self.assertIn('name="csrf-token"', html)
        c.post("/geraete/speichern/", {"kategorie": self.maus.pk, "hersteller": "H", "modell": "Marker", "zustand": 2})
        html = c.get("/geraete/").content.decode()
        self.assertIn('data-test="meldungen"', html)
        self.assertIn('data-test="nav-verleih"', html)
        html = self._client(self.leser).get("/").content.decode()
        self.assertNotIn('data-test="nav-verleih"', html)
        self.assertIn('data-test="nav-meine-geraete"', html)
        html = self._client(self.mitarbeiter).get("/meine-geraete/").content.decode()
        self.assertNotIn('data-test="nav-geraete"', html)
        self.assertNotIn('data-test="nav-uebersicht"', html)
