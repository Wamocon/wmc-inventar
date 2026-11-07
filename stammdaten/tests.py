"""Tests für Stammdaten: Kategorien (F-120), Personen (F-121), Orte (F-60).

A-0097: Kategorie anlegen zeigt die Kategorie in der Liste mit Meldung;
die fehlenden Templates kategorie_anlegen.html / kategorie_aendern.html
funktionieren (TemplateDoesNotExist war der Bug).

A-0099: Offboarding (F-52), Austritt (F-53).
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import Kategorie, Person, Ort, Ausstattungsprofil
from konten.models import Konto
from geraete import services
from geraete.models import Gerat


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
        self.assertIn('data-test="liste"', text)
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


# --- F-52 (A-0099): Offboarding -------------------------------------------------

class OffboardingTests(TestCase):
    """Offboarding-Ansicht und „Alle zurücknehmen“ (F-52, A-0099)."""

    def setUp(self):
        self.kat = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        self.admin = konto_erstellen("offboarding.admin")
        self.mitarbeiter = konto_erstellen("offboarding.mitarbeiter", admin=False)

    def test_offboarding_zeig_geraete(self):
        g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g1, self.person, ausgefuehrt_von=self.admin)
        g2 = services.gerat_anlegen(kategorie=self.kat, hersteller="Dell", modell="XPS")
        services.gerat_ausgeben(g2, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/personen/{self.person.pk}/offboarding/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="offboarding-geraete"', text)
        self.assertIn(g1.inventarnummer, text)
        self.assertIn(g2.inventarnummer, text)

    def test_alle_zuruecknehmen(self):
        g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g1, self.person, ausgefuehrt_von=self.admin)
        g2 = services.gerat_anlegen(kategorie=self.kat, hersteller="Dell", modell="XPS")
        services.gerat_ausgeben(g2, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(f"/personen/{self.person.pk}/offboarding/zuruecknehmen/")
        self.assertEqual(antwort.status_code, 302)
        g1.refresh_from_db()
        g2.refresh_from_db()
        self.assertEqual(g1.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(g2.status, Gerat.STATUS_AUF_LAGER)
        self.assertIsNone(g1.person)
        self.assertIsNone(g2.person)

    def test_mitarbeiter_kann_nicht_zuruecknehmen(self):
        g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g1, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.post(f"/personen/{self.person.pk}/offboarding/zuruecknehmen/")
        self.assertEqual(antwort.status_code, 403)
        g1.refresh_from_db()
        self.assertEqual(g1.status, Gerat.STATUS_IN_BENUTZUNG)

    def test_offboarding_ohne_geraete(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/personen/{self.person.pk}/offboarding/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn("Keine Geräte zugeordnet.", text)


# --- F-53 (A-0099): Austritt -----------------------------------------------------

class AustrittTests(TestCase):
    """Austritt eintragen (F-53, A-0099)."""

    def setUp(self):
        self.kat = Kategorie.objects.create(name="Notebook")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Erika", nachname="Muster",
            email="e.muster@wamocon.de",
        )
        self.admin = konto_erstellen("austritt.admin")
        self.mitarbeiter = konto_erstellen("austritt.mitarbeiter", admin=False)

    def test_austritt_mit_geraeten_zeigt_warnung(self):
        g1 = services.gerat_anlegen(kategorie=self.kat, hersteller="Lenovo", modell="T14")
        services.gerat_ausgeben(g1, self.person, ausgefuehrt_von=self.admin)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/personen/{self.person.pk}/austritt/eintragen/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertIn('data-test="warnung"', text)
        self.assertIn(g1.inventarnummer, text)

    def test_austritt_ohne_geraete_zeigt_keine_warnung(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.get(f"/personen/{self.person.pk}/austritt/eintragen/")
        self.assertEqual(antwort.status_code, 200)
        text = antwort.content.decode()
        self.assertNotIn('data-test="warnung"', text)

    def test_austritt_speichern_mit_datum(self):
        datum = date(2026, 11, 1)
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/personen/{self.person.pk}/austritt/speichern/",
            {"austrittsdatum": datum.isoformat()},
        )
        self.assertEqual(antwort.status_code, 302)
        self.person.refresh_from_db()
        self.assertEqual(self.person.austritt, datum)
        # F-53: Die Person bleibt aktiv, bis der Austrittstag da ist.
        self.assertEqual(self.person.aktiv, datum > date.today())

    def test_austritt_speichern_ohne_datum(self):
        self.client.login(username=self.admin.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/personen/{self.person.pk}/austritt/speichern/",
            {"austrittsdatum": ""},
        )
        self.assertEqual(antwort.status_code, 302)
        self.person.refresh_from_db()
        self.assertIsNone(self.person.austritt)
        self.assertTrue(self.person.aktiv)

    def test_mitarbeiter_kann_nicht_austritt_speichern(self):
        datum = date(2026, 11, 1)
        self.client.login(username=self.mitarbeiter.email, password="test-passwort-123")
        antwort = self.client.post(
            f"/personen/{self.person.pk}/austritt/speichern/",
            {"austrittsdatum": datum.isoformat()},
        )
        self.assertEqual(antwort.status_code, 403)
        self.person.refresh_from_db()
        self.assertIsNone(self.person.austritt)
        self.assertTrue(self.person.aktiv)


class ExportTests(TestCase):
    """F-103 (A-0910): Export für Personen, Orte, Kategorien, Verleih."""

    def setUp(self):
        self.admin = konto_erstellen("admin@example.com", admin=True)
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Test",
            nachname="Person",
            email="test.person@example.com",
        )
        self.kategorie = Kategorie.objects.create(name="Laptop")
        self.ort = Ort.objects.create(
            name="Raum 1",
            typ=Ort.TYP_ARBEITSPLATZ,
        )
        self.client.login(username=self.admin.email, password="test-passwort-123")

    def test_personen_export_csv(self):
        antwort = self.client.get("/personen/?format=csv")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("text/csv", antwort["Content-Type"])
        self.assertIn("Person", antwort.content.decode())

    def test_personen_export_xlsx(self):
        antwort = self.client.get("/personen/?format=xlsx")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("spreadsheet", antwort["Content-Type"])

    def test_orte_export_csv(self):
        antwort = self.client.get("/orte/?format=csv")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("text/csv", antwort["Content-Type"])
        self.assertIn("Raum 1", antwort.content.decode())

    def test_kategorien_export_csv(self):
        antwort = self.client.get("/kategorien/?format=csv")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("text/csv", antwort["Content-Type"])
        self.assertIn("Laptop", antwort.content.decode())

    def test_personen_seite_hat_export_buttons(self):
        antwort = self.client.get("/personen/")
        html = antwort.content.decode()
        self.assertIn('data-test="export-xlsx"', html)
        self.assertIn('data-test="export-csv"', html)

    def test_orte_seite_hat_export_buttons(self):
        antwort = self.client.get("/orte/")
        html = antwort.content.decode()
        self.assertIn('data-test="export-xlsx"', html)
        self.assertIn('data-test="export-csv"', html)

    def test_kategorien_seite_hat_export_buttons(self):
        antwort = self.client.get("/kategorien/")
        html = antwort.content.decode()
        self.assertIn('data-test="export-xlsx"', html)
        self.assertIn('data-test="export-csv"', html)