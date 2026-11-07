"""Tests für M7 Teil 2: Mails und Tageslauf (A-0906).

TESTSCHNITTSTELLE 1: tageslauf --stichtag
F-91: Leihe endet morgen → Mail an die Person, zweiter Lauf keine
F-92: Leihe überfällig → Mail an Person und IT, zwei Stichtage je eine
F-94: Sammelmail an die IT am Montag
F-95: Unterschriften in derselben Sammelmail
F-140: Erinnerung Gegenzeichnung am dritten Tag
F-53: Konto am Tag nach Austritt deaktiviert, danach keine Mails
F-93: Neue Leihanfrage → Mail an it-admin@beispiel.test
F-32: Entscheidung → Mail an die Person
F-101: Zählerstand für das Delta
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from konten.models import Konto
from stammdaten.models import Einstellungen, Kategorie, Person, Ort, Zaehlerstand
from geraete import services
from geraete.models import Gerat, Leihe, Protokoll


def _einrichtungen_anlegen():
    """Minimale Testdaten: Einstellungen."""
    einstellungen = Einstellungen.aktuelles()
    einstellungen.email_it = "it-admin@beispiel.test"
    einstellungen.absenderzeile = "Wamocon GmbH · IT"
    einstellungen.save()
    return einstellungen


def _stammdaten_erstellen():
    """Person, Kategorie, Ort anlegen."""
    person = Person.objects.create(
        anrede=Person.ANREDE_FRAU,
        vorname="Test",
        nachname="Person",
        email="test.person@beispiel.test",
    )
    kategorie = Kategorie.objects.create(name="Laptop")
    ort = Ort.objects.create(kennung="WMC-WP-01", typ=Ort.TYP_ARBEITSPLATZ)
    return person, kategorie, ort


class TageslaufF91Tests(TestCase):
    """F-91: Leihe endet morgen → Mail an die Person."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.person, self.kategorie, self.ort = _stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            leihpool=True,
            person=self.person,
        )
        self.gerat.status = Gerat.STATUS_VERLIEHEN
        self.gerat.save()

    def test_leihe_endet_morgen_mail_an_person(self):
        """F-91: Leihe endet morgen → Mail an die Person."""
        stichtag = date(2026, 11, 2)
        morgen = stichtag + timedelta(days=1)
        Leihe.objects.create(
            nr="L-001",
            person=self.person,
            gerat=self.gerat,
            kat=self.kategorie,
            beginn=stichtag - timedelta(days=5),
            ende=morgen,
            rueckgabe_bis=morgen,
            status=Leihe.STATUS_AUSGEGEBEN,
            zeitpunkt=morgen,
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("test.person@beispiel.test", mail.outbox[0].to)
        self.assertIn("endet morgen", mail.outbox[0].subject.lower())

    def test_leihe_endet_morgen_zweiter_lauf_keine_mail(self):
        """F-91: Zweiter Lauf für denselben Stichtag → keine Mail."""
        stichtag = date(2026, 11, 2)
        morgen = stichtag + timedelta(days=1)
        Leihe.objects.create(
            nr="L-002",
            person=self.person,
            gerat=self.gerat,
            kat=self.kategorie,
            beginn=stichtag - timedelta(days=5),
            ende=morgen,
            rueckgabe_bis=morgen,
            status=Leihe.STATUS_AUSGEGEBEN,
            zeitpunkt=morgen,
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.assertGreater(len(mail.outbox), 0)
        mail.outbox.clear()
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.assertEqual(len(mail.outbox), 0)


class TageslaufF92Tests(TestCase):
    """F-92: Leihe überfällig → Mail an Person und IT."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.person, self.kategorie, self.ort = _stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="U2723QE",
            leihpool=True,
            person=self.person,
        )
        self.gerat.status = Gerat.STATUS_VERLIEHEN
        self.gerat.save()

    def test_ueberfaellig_mail_person_und_it(self):
        """F-92: Überfällige Leihe → Mail an Person und IT."""
        stichtag = date(2026, 11, 3)
        Leihe.objects.create(
            nr="L-101",
            person=self.person,
            gerat=self.gerat,
            kat=self.kategorie,
            beginn=stichtag - timedelta(days=10),
            ende=stichtag - timedelta(days=3),
            rueckgabe_bis=stichtag - timedelta(days=3),
            status=Leihe.STATUS_AUSGEGEBEN,
            zeitpunkt=stichtag - timedelta(days=3),
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.assertGreaterEqual(len(mail.outbox), 1)
        mails_an_person = [
            m for m in mail.outbox if "test.person@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_person), 1)
        mails_an_it = [
            m for m in mail.outbox if "it-admin@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_it), 1)

    def test_ueberfaellig_zwei_stichtage_je_eine_mail(self):
        """F-92: Überfällige Leihe → an zwei Stichtagen je eine Mail."""
        stichtag1 = date(2026, 11, 3)
        stichtag2 = date(2026, 11, 4)
        Leihe.objects.create(
            nr="L-102",
            person=self.person,
            gerat=self.gerat,
            kat=self.kategorie,
            beginn=stichtag1 - timedelta(days=10),
            ende=stichtag1 - timedelta(days=5),
            rueckgabe_bis=stichtag1 - timedelta(days=5),
            status=Leihe.STATUS_AUSGEGEBEN,
            zeitpunkt=stichtag1 - timedelta(days=5),
        )
        call_command("tageslauf", stichtag=stichtag1.isoformat())
        self.assertGreater(len(mail.outbox), 0)
        mail.outbox.clear()
        call_command("tageslauf", stichtag=stichtag2.isoformat())
        self.assertGreater(len(mail.outbox), 0)


class TageslaufF94Tests(TestCase):
    """F-94: Sammelmail an die IT am Montag."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.kategorie = Kategorie.objects.create(name="Server")
        self.ort = Ort.objects.create(kennung="WMC-RA-01", typ=Ort.TYP_RAUM)

    def test_montag_sammelmail_garantie(self):
        """F-94: Montag → Sammelmail an die IT mit Garantie."""
        stichtag = date(2026, 11, 9)
        self.assertEqual(stichtag.weekday(), 0)
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="PowerEdge R750",
            ort=self.ort,
            garantie_bis=stichtag + timedelta(days=15),
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        mails_an_it = [
            m for m in mail.outbox if "it-admin@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_it), 1)
        text = " ".join(str(m.message()) for m in mails_an_it)
        self.assertIn("Garantie", text)

    def test_dienstag_keine_sammelmail(self):
        """F-94: Dienstag → keine Sammelmail."""
        stichtag = date(2026, 11, 10)
        self.assertEqual(stichtag.weekday(), 1)
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="PowerEdge R750",
            ort=self.ort,
            garantie_bis=stichtag + timedelta(days=15),
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        mails_an_it = [
            m for m in mail.outbox if "it-admin@beispiel.test" in m.to
        ]
        self.assertEqual(len(mails_an_it), 0)


class TageslaufF140Tests(TestCase):
    """F-140: Erinnerung Gegenzeichnung am dritten Tag."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.person, self.kategorie, self.ort = _stammdaten_erstellen()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Lenovo",
            modell="ThinkPad X1",
            person=self.person,
        )

    def test_erinnerung_am_dritten_tag(self):
        """F-140: Link am 02.11. → Erinnerung am 05.11."""
        versanddatum = date(2026, 11, 2)
        stichtag = date(2026, 11, 5)
        self.assertEqual(stichtag - timedelta(days=3), versanddatum)
        Protokoll.objects.create(
            nr="P-201",
            person=self.person,
            geraet=self.gerat,
            datum=versanddatum,
            stand=Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
            gegenzeichnung_token="test-token-abc",
            gegenzeichnung_token_erstellt=versanddatum,
            gegenzeichnung_empfaenger="test.person@beispiel.test",
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        mails_an_person = [
            m for m in mail.outbox if "test.person@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_person), 1)
        self.assertIn("Erinnerung", mail.outbox[0].subject)

    def test_keine_erinnerung_am_zweiten_tag(self):
        """F-140: Am zweiten Tag → keine Erinnerung."""
        versanddatum = date(2026, 11, 2)
        stichtag = date(2026, 11, 4)
        Protokoll.objects.create(
            nr="P-202",
            person=self.person,
            geraet=self.gerat,
            datum=versanddatum,
            stand=Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
            gegenzeichnung_token="test-token-def",
            gegenzeichnung_token_erstellt=versanddatum,
            gegenzeichnung_empfaenger="test.person@beispiel.test",
        )
        call_command("tageslauf", stichtag=stichtag.isoformat())
        mails_an_person = [
            m for m in mail.outbox if "test.person@beispiel.test" in m.to
        ]
        self.assertEqual(len(mails_an_person), 0)


class TageslaufF53Tests(TestCase):
    """F-53: Konto am Tag nach dem Austritt deaktiviert."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU,
            vorname="Diana",
            nachname="Krause",
            email="diana.krause@beispiel.test",
        )

    def test_konto_deaktiviert_am_tag_nach_austritt(self):
        """F-53: Austritt 02.11. → Konto ab 03.11. deaktiviert."""
        self.person.austritt = date(2026, 11, 2)
        self.person.save()
        self.konto = Konto.objects.create_konto(
            email="diana.krause@beispiel.test",
            password="test12345678",
            rolle=Konto.ROLLE_MITARBEITER,
            person=self.person,
        )
        self.assertTrue(self.konto.aktiv)
        stichtag = date(2026, 11, 3)
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.konto.refresh_from_db()
        self.assertFalse(self.konto.aktiv)

    def test_konto_am_austrittstag_noch_aktiv(self):
        """F-53: Am Austrittstag selbst noch aktiv."""
        self.person.austritt = date(2026, 11, 2)
        self.person.save()
        self.konto = Konto.objects.create_konto(
            email="diana.krause2@beispiel.test",
            password="test12345678",
            rolle=Konto.ROLLE_MITARBEITER,
            person=self.person,
        )
        self.assertTrue(self.konto.aktiv)
        stichtag = date(2026, 11, 2)
        call_command("tageslauf", stichtag=stichtag.isoformat())
        self.konto.refresh_from_db()
        self.assertTrue(self.konto.aktiv)


class LeihanfrageMailTests(TestCase):
    """F-93: Neue Leihanfrage → sofort Mail an die IT.
    F-32: Entscheidung → sofort Mail an die Person.
    """

    def setUp(self):
        _einrichtungen_anlegen()
        self.person = Person.objects.create(
            anrede=Person.ANREDE_HERR,
            vorname="Erik",
            nachname="Wagner",
            email="erik.wagner@beispiel.test",
        )
        self.kategorie = Kategorie.objects.create(name="Drucker")
        self.ort = Ort.objects.create(kennung="WMC-WP-04", typ=Ort.TYP_ARBEITSPLATZ)

    def test_anfrage_mail_an_it(self):
        """F-93: Neue Leihanfrage → Mail an it-admin@beispiel.test."""
        leihe = Leihe.objects.create(
            nr="L-301",
            person=self.person,
            kat=self.kategorie,
            beginn=date(2026, 11, 10),
            ende=date(2026, 11, 12),
            rueckgabe_bis=date(2026, 11, 12),
            status=Leihe.STATUS_ANGEFRAGT,
            zweck="Projekt X",
        )
        mail.outbox.clear()
        services._mail_anfrage_an_it(leihe)
        mails_an_it = [
            m for m in mail.outbox if "it-admin@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_it), 1)
        self.assertIn("Leihanfrage", mails_an_it[0].subject)

    def test_entscheidung_genehmigt_mail_an_person(self):
        """F-32: Genehmigung → Mail an die Person."""
        leihe = Leihe.objects.create(
            nr="L-302",
            person=self.person,
            kat=self.kategorie,
            beginn=date(2026, 11, 10),
            ende=date(2026, 11, 12),
            rueckgabe_bis=date(2026, 11, 12),
            status=Leihe.STATUS_GENEHMIGT,
        )
        mail.outbox.clear()
        services._mail_entscheidung_an_person(leihe, genehmigt=True)
        mails_an_person = [
            m for m in mail.outbox if "erik.wagner@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_person), 1)
        self.assertIn("genehmigt", mails_an_person[0].subject.lower())

    def test_entscheidung_abgelehnt_mail_an_person(self):
        """F-32: Ablehnung → Mail an die Person mit Begründung."""
        leihe = Leihe.objects.create(
            nr="L-303",
            person=self.person,
            kat=self.kategorie,
            beginn=date(2026, 11, 10),
            ende=date(2026, 11, 12),
            rueckgabe_bis=date(2026, 11, 12),
            status=Leihe.STATUS_ABGELEHNT,
        )
        mail.outbox.clear()
        services._mail_entscheidung_an_person(
            leihe, genehmigt=False, begruendung="Kein Gerät verfügbar"
        )
        mails_an_person = [
            m for m in mail.outbox if "erik.wagner@beispiel.test" in m.to
        ]
        self.assertGreaterEqual(len(mails_an_person), 1)
        self.assertIn("abgelehnt", mails_an_person[0].subject.lower())
        self.assertIn("Kein Gerät verfügbar", str(mails_an_person[0].message()))


class ZaehlerstandTests(TestCase):
    """F-101: Zählerstand für das Delta."""

    def setUp(self):
        _einrichtungen_anlegen()
        self.person, self.kategorie, self.ort = _stammdaten_erstellen()

    def test_zaehlerstand_wird_angelegt(self):
        """F-101: tageslauf legt einen Zaehlerstand an."""
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )
        stichtag = date(2026, 11, 2)
        call_command("tageslauf", stichtag=stichtag.isoformat())
        zaehlerstand = Zaehlerstand.objects.filter(stichtag=stichtag).first()
        self.assertIsNotNone(zaehlerstand)
        self.assertIn("in-benutzung", zaehlerstand.kennzahlen)
        self.assertEqual(zaehlerstand.kennzahlen["in-benutzung"]["ist"], 1)

    def test_delta_zum_vortag(self):
        """F-101: Delta zwischen zwei aufeinanderfolgenden Tagen."""
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="HP",
            modell="EliteBook 840",
            person=self.person,
        )
        stichtag1 = date(2026, 11, 2)
        stichtag2 = date(2026, 11, 3)
        call_command("tageslauf", stichtag=stichtag1.isoformat())
        services.gerat_anlegen(
            kategorie=self.kategorie,
            hersteller="Dell",
            modell="Latitude 5540",
            person=self.person,
        )
        call_command("tageslauf", stichtag=stichtag2.isoformat())
        from konten.management.commands.tageslauf import delta_zum_vortag
        delta = delta_zum_vortag(stichtag2)
        self.assertIsNotNone(delta)
        self.assertEqual(delta["in-benutzung"], 1)
