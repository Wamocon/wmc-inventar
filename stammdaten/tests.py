"""Tests für Stammdaten: Kategorien (F-120), Personen (F-121), Orte (F-60).

A-0097: Kategorie anlegen zeigt die Kategorie in der Liste mit Meldung;
die fehlenden Templates kategorie_anlegen.html / kategorie_aendern.html
funktionieren (TemplateDoesNotExist war der Bug).
"""
from django.test import TestCase
from django.urls import reverse

from .models import Kategorie, Person, Ort, Ausstattungsprofil
from konten.models import Konto


def konto_erstellen(email: str, admin: bool = True) -> Konto:
    rolle = Konto.ROLLE_ADMIN if admin else Konto.ROLLE_MITARBEITER
    konto = Konto(email=email, rolle=rolle)
    konto.set_password("test-passwort-123")
    konto.save()
    return konto


class KategorieAnlegenTests(TestCase):
    """A-0097: Kategorie anlegen (F-120)."""

    def setUp(self):
        self.admin = konto_erstellen("kategorie.admin")

    def test_anlegen_zeigt_liste_mit_meldung(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            reverse("stammdaten:kategorien-anlegen"),
            {"name": "Grafikkarte"},
        )
        self.assertEqual(antwort.status_code, 302)
        liste = self.client.get(reverse("stammdaten:kategorien-liste"))
        text = liste.content.decode()
        self.assertIn('data-test="kategorien-liste"', text)
        self.assertIn("Grafikkarte", text)

    def test_anlegen_seite_oeffnet(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:kategorien-anlegen"))
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn("Neue Kategorie", text)

    def test_aendern_seite_oeffnet(self):
        kat = Kategorie.objects.create(name="Tastatur")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(
            reverse("stammdaten:kategorien-aendern", kwargs={"pk": kat.pk})
        )
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn("Kategorie ändern", text)
        self.assertIn("Tastatur", text)

    def test_aendern_name(self):
        kat = Kategorie.objects.create(name="Tastatur")
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            reverse("stammdaten:kategorien-aendern", kwargs={"pk": kat.pk}),
            {"name": "Gaming-Tastatur"},
        )
        self.assertEqual(antwort.status_code, 302)
        kat.refresh_from_db()
        self.assertEqual(kat.name, "Gaming-Tastatur")

    def test_leser_kann_nicht_anlegen(self):
        les = konto_erstellen("kategorie.leser", admin=False)
        self.client.login(username=les.email, password="test-passwort-123")
        antwort = self.client.get(reverse("stammdaten:kategorien-anlegen"))
        self.assertEqual(antwort.status_code, 403)