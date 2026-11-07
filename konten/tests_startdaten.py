"""N-11: Startdaten für den Betrieb."""
import os
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from konten.models import Konto
from stammdaten.models import Kategorie, Ort


class StartdatenTests(TestCase):
    def _lauf(self, **umgebung):
        with mock.patch.dict(os.environ, umgebung):
            call_command("startdaten", stdout=StringIO())

    def test_legt_alles_an_und_laesst_sich_wiederholen(self):
        self._lauf(ADMIN_EMAIL="it@beispiel.test", ADMIN_PASSWORT="Ein-langes-Passwort-2026")
        kategorien = Kategorie.objects.count()
        self.assertGreaterEqual(kategorien, 21)
        self.assertTrue(Kategorie.objects.get(name="Notebook").hat_datentraeger)
        self.assertEqual(Ort.objects.filter(typ=Ort.TYP_LAGER).count(), 1)
        konto = Konto.objects.get(email="it@beispiel.test")
        self.assertTrue(konto.ist_admin)
        self.assertTrue(konto.check_password("Ein-langes-Passwort-2026"))
        self._lauf(ADMIN_EMAIL="zweite@beispiel.test", ADMIN_PASSWORT="Ein-langes-Passwort-2026")
        self.assertEqual(Kategorie.objects.count(), kategorien)
        self.assertEqual(Konto.objects.count(), 1)

    def test_ohne_angaben_kein_konto(self):
        with mock.patch.dict(os.environ, {"ADMIN_EMAIL": "", "ADMIN_PASSWORT": ""}):
            with self.assertRaises(CommandError):
                call_command("startdaten", stdout=StringIO())
        self.assertEqual(Konto.objects.count(), 0)

    def test_schwaches_passwort_wird_abgelehnt(self):
        with mock.patch.dict(os.environ, {"ADMIN_EMAIL": "it@beispiel.test", "ADMIN_PASSWORT": "kurz"}):
            with self.assertRaises(CommandError):
                call_command("startdaten", stdout=StringIO())
        self.assertEqual(Konto.objects.count(), 0)
