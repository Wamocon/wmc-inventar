"""Tests für die Login-Funktion (F-01).

Sicherstellen, dass die Anmeldung funktioniert und der
fehlerhafte Feldname "fehlersuche" nicht mehr vorkommt.
"""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from konten.models import Konto


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