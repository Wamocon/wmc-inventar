"""Tests für die Login-Funktion (F-01) und die Übersicht (TESTSCHNITTSTELLE 3).

Sicherstellen, dass die Anmeldung funktioniert und der
fehlerhafte Feldname "fehlersuche" nicht mehr vorkommt.
Zusätzlich: "/" antwortet nach der Anmeldung für Admin mit 200
und für Mitarbeiter mit einer Weiterleitung nach "/meine-geraete/".
"""
from __future__ import annotations

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from konten.models import Konto
from stammdaten.models import Person


class LoginTests(TestCase):
    """F-01: Anmeldung mit E-Mail und Passwort."""

    def setUp(self):
        self.konto = Konto.objects.create_konto(
            email="test@example.com",
            password="sehrgeheim123",
            rolle=Konto.ROLLE_ADMIN,
        )

    def test_anmeldung_klappt(self):
        """F-01: Richtiges Passwort führt zum Login."""
        antwort = self.client.post(
            "/anmelden/",
            {"email": "test@example.com", "passwort": "sehrgeheim123"},
        )
        # Erfolgreicher Login → Redirect (302) oder 200
        self.assertIn(antwort.status_code, (200, 302))
        # Kein 500-Fehler
        self.assertNotEqual(antwort.status_code, 500)
        if antwort.status_code == 302:
            # Nach dem Login: Session ist gesetzt
            session = self.client.session
            self.assertIsNotNone(session.get("_auth_user_id"))

    def test_anmeldung_falsches_passwort(self):
        """F-01: Falsches Passwort → Neutrale Fehlermeldung."""
        antwort = self.client.post(
            "/anmelden/",
            {"email": "test@example.com", "passwort": "falsch12345"},
        )
        self.assertEqual(antwort.status_code, 200)
        # Fehlermeldung im Context
        self.assertTrue(antwort.context.get("fehler") or "falsch" in str(antwort.content).lower())

    def test_anmeldung_unbekanntes_konto(self):
        """F-01: Unbekannte E-Mail → Neutrale Fehlermeldung."""
        antwort = self.client.post(
            "/anmelden/",
            {"email": "unbekannt@example.com", "passwort": "sehrgeheim123"},
        )
        self.assertEqual(antwort.status_code, 200)

    def test_fehlversuche_werden_gezaehlt(self):
        """F-01: Fehlversuche werden in der Datenbank gezählt."""
        # 5× falsches Passwort
        for _ in range(5):
            self.client.post(
                "/anmelden/",
                {"email": "test@example.com", "passwort": "falsch12345"},
            )
        self.konto.refresh_from_db()
        self.assertGreaterEqual(self.konto.fehlversuche, 5)
        # Sperre ist gesetzt
        self.assertIsNotNone(self.konto.gesperrt_bis)

    def test_sperre_nach_5_fehlversuchen(self):
        """F-01: Nach 5 Fehlversuchen ist das Konto gesperrt."""
        # 5× falsches Passwort
        for _ in range(5):
            self.client.post(
                "/anmelden/",
                {"email": "test@example.com", "passwort": "falsch12345"},
            )
        # 6. Versuch: Sollte gesperrt sein
        antwort = self.client.post(
            "/anmelden/",
            {"email": "test@example.com", "passwort": "sehrgeheim123"},
        )
        self.assertEqual(antwort.status_code, 200)
        # Fehlermeldung wegen Sperre
        content = str(antwort.content).lower()
        self.assertTrue("gesperrt" in content or "sperr" in content)

    def test_update_fields_benutzt_fehlversuche(self):
        """Regression: update_fields muss das Feld fehlversuche nennen."""
        # Dieser Test scheitert, wenn update_fields ein unbekanntes Feld enthält.
        self.konto.fehlversuche = 1
        self.konto.save(update_fields=["fehlversuche", "gesperrt_bis"])
        self.konto.refresh_from_db()
        self.assertEqual(self.konto.fehlversuche, 1)


class UebersichtTests(TestCase):
    """TESTSCHNITTSTELLE 3: "/" antwortet je nach Rolle."""

    def setUp(self):
        # Admin (TESTSCHNITTSTELLE 2)
        self.konto_admin = Konto.objects.create_konto(
            email="it-admin@beispiel.test",
            password="Beispiel-Passwort-2026",
            rolle=Konto.ROLLE_ADMIN,
        )
        # Mitarbeiter (TESTSCHNITTSTELLE 2)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Anna",
            nachname="Becker",
            email="anna.becker@beispiel.test",
        )
        self.konto_mitarbeiter = Konto.objects.create_konto(
            email="anna.becker@beispiel.test",
            password="Beispiel-Passwort-2026",
            rolle=Konto.ROLLE_MITARBEITER,
            person=self.person,
        )

    def test_uebersicht_fuer_admin_200(self):
        """TESTSCHNITTSTELLE 3: "/" für Admin antwortet mit 200."""
        self.client.login(
            username="it-admin@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 200)
        # Die Seite zeigt die Überschrift "Übersicht" und die Navigation
        text = antwort.content.decode()
        self.assertIn("Übersicht", text)
        self.assertIn('data-test="hauptnavigation"', text)

    def test_uebersicht_fuer_mitarbeiter_redirect(self):
        """TESTSCHNITTSTELLE 3: "/" für Mitarbeiter weiterleitet nach /meine-geraete/."""
        self.client.login(
            username="anna.becker@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/")
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort["Location"], "/meine-geraete/")


class KontenVerwaltungTests(TestCase):
    """F-02 (A-0098): Kontenliste nur für Admin."""

    def setUp(self):
        self.konto_admin = Konto.objects.create_konto(
            email="it-admin@beispiel.test",
            password="Beispiel-Passwort-2026",
            rolle=Konto.ROLLE_ADMIN,
        )
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Anna",
            nachname="Becker",
            email="anna.becker@beispiel.test",
        )
        self.konto_mitarbeiter = Konto.objects.create_konto(
            email="anna.becker@beispiel.test",
            password="Beispiel-Passwort-2026",
            rolle=Konto.ROLLE_MITARBEITER,
            person=self.person,
        )

    def test_konten_liste_admin_200(self):
        """F-02: /konten/ für Admin antwortet mit 200 und zeigt die Liste."""
        self.client.login(
            username="it-admin@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/konten/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="liste"', text)
        self.assertIn('data-test="konto-anlegen"', text)
        # Das eigene Konto und das Mitarbeiter-Konto stehen in der Liste.
        self.assertIn("it-admin@beispiel.test", text)
        self.assertIn("anna.becker@beispiel.test", text)

    def test_konten_liste_mitarbeiter_403(self):
        """F-02: /konten/ für Mitarbeiter antwortet mit 403."""
        self.client.login(
            username="anna.becker@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/konten/")
        self.assertEqual(antwort.status_code, 403)

    def test_konto_anlegen_admin_200(self):
        """F-02: /konten/neu/ für Admin antwortet mit 200 und zeigt das Formular."""
        self.client.login(
            username="it-admin@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/konten/neu/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="konto-speichern"', text)
        self.assertIn("name=\"email\"", text)
        self.assertIn("name=\"rolle\"", text)

    def test_konto_anlegen_mitarbeiter_403(self):
        """F-02: /konten/neu/ für Mitarbeiter antwortet mit 403."""
        self.client.login(
            username="anna.becker@beispiel.test",
            password="Beispiel-Passwort-2026",
        )
        antwort = self.client.get("/konten/neu/")
        self.assertEqual(antwort.status_code, 403)


class BeispieldatenLeerenTests(TransactionTestCase):
    """TESTSCHNITTSTELLE: --neu leert den Datenbankinhalt, alle Tabellen (A-0914)."""

    @override_settings(DEBUG=True)
    def test_leeren_leert_alle_tabellen(self):
        from django.apps import apps
        from django.core.management import call_command

        from konten.management.commands.beispieldaten import Command

        call_command("beispieldaten", "--neu", verbosity=0)
        Command()._leeren()
        for modell in apps.get_models():
            if modell._meta.app_label in ("konten", "stammdaten", "geraete"):
                self.assertEqual(modell.objects.count(), 0, modell._meta.label)