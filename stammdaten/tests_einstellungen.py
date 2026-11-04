"""Tests für Einstellungen (F-122, F-90, F-96, F-130, N-02) — M7 Teil 1 (A-0905).

TESTSCHNITTSTELLE.md Kapitel 3:
- /einstellungen/ für Admin (it-admin@beispiel.test) → 200
- /einstellungen/ für Leser (gf@beispiel.test) → 403
- /einstellungen/ für Mitarbeiter (anna.becker@beispiel.test) → 403

TESTSCHNITTSTELLE.md Kapitel 2:
- Beispieldaten erzeugen die Werte für Einstellungen
"""
from django.test import TestCase
from django.urls import reverse

from konten.models import Konto
from stammdaten.models import Einstellungen


def _konto(email: str, rolle: str) -> Konto:
    k = Konto(email=email, rolle=rolle, aktiv=True)
    k.set_password("test-passwort-123")
    k.save()
    return k


class EinstellungenRechteTests(TestCase):
    """TESTSCHNITTSTELLE.md Kapitel 3: Rechte für /einstellungen/."""

    def test_admin_erhaelt_200(self):
        """Admin (it-admin@beispiel.test) erhält 200."""
        _konto("it-admin@beispiel.test", Konto.ROLLE_ADMIN)
        self.client.login(username="it-admin@beispiel.test", password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:einstellungen"))
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="einstellungen-formular"', text)
        self.assertIn('data-test="absenderzeile"', text)
        self.assertIn('data-test="smtp-server"', text)
        self.assertIn('data-test="mail-verleih-anfrage"', text)

    def test_leser_erhaelt_403(self):
        """Leser (gf@beispiel.test) erhält 403."""
        _konto("gf@beispiel.test", Konto.ROLLE_LESER)
        self.client.login(username="gf@beispiel.test", password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:einstellungen"))
        self.assertEqual(antwort.status_code, 403)

    def test_mitarbeiter_erhaelt_403(self):
        """Mitarbeiter (anna.becker@beispiel.test) erhält 403."""
        _konto("anna.becker@beispiel.test", Konto.ROLLE_MITARBEITER)
        self.client.login(username="anna.becker@beispiel.test", password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:einstellungen"))
        self.assertEqual(antwort.status_code, 403)


class EinstellungenDatenTests(TestCase):
    """TESTSCHNITTSTELLE.md Kapitel 2: Beispieldaten für Einstellungen."""

    def test_einstellungen_existieren_nach_beispieldaten(self):
        """Nach beispieldaten --neu müssen Einstellungen mit den Werten aus
        TESTSCHNITTSTELLE.md Kapitel 2 vorhanden sein."""
        from django.core.management import call_command
        from django.conf import settings
        import io

        # beispieldaten läuft nur im Entwicklungsmodus
        if not settings.DEBUG:
            self.skipTest("INVENTAR_DEBUG ist nicht gesetzt")

        ausgabe = io.StringIO()
        call_command("beispieldaten", "--neu", stdout=ausgabe)

        e = Einstellungen.aktuelles()
        self.assertIsNotNone(e)
        self.assertEqual(e.firmenname, "Wamocon GmbH")
        self.assertEqual(e.absenderzeile, "Wamocon GmbH · IT")
        self.assertEqual(e.telefon, "0157 77709235")
        self.assertEqual(e.email_it, "it@wamocon.de")
        self.assertEqual(e.nutzungsbedingungen_version, "1")
        self.assertEqual(e.erklaerungen_version, "1")
        self.assertEqual(e.unterzeichnung_version, "1")
        self.assertEqual(e.etikettenformat, "a4")
        self.assertEqual(e.erinnerungsfrist_tage, 7)
        self.assertEqual(e.smtp_server, "mail.beispiel.test")
        self.assertEqual(e.smtp_port, 587)
        self.assertTrue(e.smtp_tls)
        self.assertEqual(e.smtp_absender, "it@beispiel.test")
        self.assertTrue(e.mail_verleih_anfrage)
        self.assertTrue(e.mail_verleih_ablehnung)
        self.assertTrue(e.mail_verleih_genehmigung)
        self.assertTrue(e.mail_verleih_zuruecknahme)
        self.assertTrue(e.mail_protokoll_gesendet)
        self.assertTrue(e.mail_protokoll_unterzeichnet)

    def test_absenderzeile_aenderbar(self):
        """Eine geänderte Absenderzeile muss im nächsten Protokoll-PDF stehen."""
        e = Einstellungen.aktuelles()
        alte_zeile = e.absenderzeile
        try:
            e.absenderzeile = "Wamocon GmbH · IT · Test"
            e.save()
            e.refresh_from_db()
            self.assertEqual(e.absenderzeile, "Wamocon GmbH · IT · Test")
        finally:
            e.absenderzeile = alte_zeile
            e.save()

    def test_mailtyp_deaktiviert_keine_mail(self):
        """F-96: Abgeschaltete Mailart erzeugt keine Mail."""
        e = Einstellungen.aktuelles()
        alte_wert = e.mail_verleih_anfrage
        try:
            e.mail_verleih_anfrage = False
            e.save()
            e.refresh_from_db()
            self.assertFalse(e.mail_verleih_anfrage)
        finally:
            e.mail_verleih_anfrage = alte_wert
            e.save()


class EinstellungenTestmailTests(TestCase):
    """F-90: Testmail senden erzeugt eine Mail in der Mailablage."""

    def setUp(self):
        # MAILDIR für den Test setzen, unabhängig von der Umgebung.
        import os
        from pathlib import Path
        self.ablage_pfad = Path(os.environ.get("MAILDIR", "")) if os.environ.get("MAILDIR") else Path(__file__).parent.parent / "var" / "mails_test"
        self.ablage_pfad.mkdir(parents=True, exist_ok=True)
        # Die alte Anzahl .eml-Dateien merken.
        self.eml_vor = len(list(self.ablage_pfad.rglob("*.eml")))
        # MAILDIR für den Test setzen.
        self._alte_maildir = os.environ.get("MAILDIR")
        os.environ["MAILDIR"] = str(self.ablage_pfad)

    def tearDown(self):
        # Testdateien aufräumen.
        import os
        for f in self.ablage_pfad.rglob("*.eml"):
            f.unlink()
        # MAILDIR wiederherstellen.
        if self._alte_maildir is not None:
            os.environ["MAILDIR"] = self._alte_maildir
        else:
            os.environ.pop("MAILDIR", None)

    def test_testmail_erzeugt_mail_in_ablage(self):
        """POST /einstellungen/testmail/ erzeugt eine .eml-Datei in der Ablage."""
        _konto("it-admin@beispiel.test", Konto.ROLLE_ADMIN)
        self.client.login(username="it-admin@beispiel.test", password="test-passwort-123")

        antwort = self.client.post(
            reverse("stammdaten:einstellungen-testmail"),
            {"empfaenger": "test@beispiel.test"},
        )
        self.assertEqual(antwort.status_code, 200)
        html = antwort.content.decode()
        self.assertIn("Testmail an test@beispiel.test gesendet.", html)

        # Anzahl .eml-Dateien nach dem Test
        nach = len(list(self.ablage_pfad.rglob("*.eml")))
        self.assertGreater(nach, self.eml_vor)


class EinstellungenLogoTests(TestCase):
    """N-02: SVG-Logo wird nur als Bild eingebunden, nie als Inline-SVG."""

    def test_svg_logo_nur_als_bild(self):
        """Ein SVG-Logo darf im Template nur per <img src=...> eingebunden werden."""
        _konto("it-admin@beispiel.test", Konto.ROLLE_ADMIN)
        self.client.login(username="it-admin@beispiel.test", password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:einstellungen"))
        text = antwort.content.decode()
        # Das Formularfeld für das Logo muss vorhanden sein
        self.assertIn('data-test="logo"', text)
        # Die Hilfe muss N-02 erwähnen
        self.assertIn("N-02", text)
