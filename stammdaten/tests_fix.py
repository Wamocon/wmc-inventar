"""Tests zu den Prüfbefunden: Stammdaten, Einstellungen, Raumplan, Konten, Mails.

F-02, F-03, F-04, F-53, F-60 bis F-69, F-90, F-94 bis F-96, F-120 bis F-122, N-02.
Sie schreiben fest, was im Browser nachgestellt wurde.
"""
import io
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone as tz
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from geraete import services
from geraete.models import Gerat, Leihe, Protokoll
from konten import views as konten_views
from konten.forms import KontoForm
from konten.mail import EinstellungenSmtpBackend, aktive_empfaenger, konto_deaktiviert
from konten.models import Konto
from stammdaten.firma import firmendaten
from stammdaten.models import (
    Ausstattungsprofil,
    Einstellungen,
    Kategorie,
    Ort,
    Person,
    Plan,
    Profilposition,
)
from stammdaten.uploads import dateityp_erkennen

PW = "test-passwort-123"


def konto(email, rolle=Konto.ROLLE_ADMIN, person=None):
    k = Konto(email=email, rolle=rolle, aktiv=True, person=person)
    k.set_password(PW)
    k.save()
    return k


def png(breite=40, hoehe=20):
    puffer = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (200, 200, 200)).save(puffer, "PNG")
    return puffer.getvalue()


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script>x()</script></svg>'


class Grundlage(TestCase):
    def setUp(self):
        self.admin = konto("admin@beispiel.test")
        self.leser = konto("leser@beispiel.test", Konto.ROLLE_LESER)
        self.anna = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker",
            email="anna.becker@beispiel.test", eintritt=date(2024, 1, 1),
        )
        self.ma = konto("anna.becker@beispiel.test", Konto.ROLLE_MITARBEITER, self.anna)
        self.kat = Kategorie.objects.create(name="Monitor")

    def als(self, wer):
        self.client.force_login(wer)

    def geraet(self, kategorie=None, nr=[0], **k):
        nr[0] += 1
        return services.gerat_anlegen(
            kategorie=kategorie or self.kat, hersteller="H", modell="M",
            seriennummer=f"S-{nr[0]}", erzeugt_von=self.admin, **k,
        )


class BeispieldatenTests(TestCase):
    """TESTSCHNITTSTELLE 2."""

    def setUp(self):
        ablage = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ablage, ignore_errors=True)
        with override_settings(DEBUG=True, MEDIA_ROOT=ablage):
            call_command("beispieldaten", stdout=io.StringIO())

    def test_feste_personen_und_notizen(self):
        self.assertEqual(Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ, feste_person__isnull=False).count(), 13)
        self.assertEqual(Ort.objects.get(kennung="WMC-WP-09").feste_person.nachname, "Klein")
        self.assertEqual(Ort.objects.get(kennung="WMC-WP-14").notiz, "Gäste")
        self.assertEqual(Ort.objects.get(kennung="WMC-WP-15").notiz, "Studio-Arbeitsplatz")

    def test_personen(self):
        self.assertTrue(Person.objects.filter(email="paul.schroeder@beispiel.test").exists())
        self.assertTrue(Person.objects.filter(email="murat.yilmaz@beispiel.test").exists())
        self.assertEqual(Person.objects.get(vorname="Felix").eintritt, date(2025, 9, 15))
        self.assertEqual(Person.objects.get(vorname="Anna").eintritt, date(2024, 1, 1))
        self.assertEqual(Person.objects.get(vorname="Anna").anrede, Person.ANREDE_FRAU)
        self.assertEqual(Person.objects.get(vorname="Tobias").anrede, Person.ANREDE_HERR)
        self.assertEqual(Person.objects.get(vorname="Tobias").email, "it-admin@beispiel.test")
        self.assertEqual(set(Person.objects.values_list("anrede", flat=True)), {"h", "f"})

    def test_einstellungen(self):
        e = Einstellungen.aktuelles()
        self.assertEqual(e.firmenname, "WAMOCON GmbH")
        self.assertEqual(e.absenderzeile, "WAMOCON GmbH · Mergenthalerallee 77 · 65760 Eschborn")
        self.assertEqual(e.telefon, "+49 6196 0000000")
        self.assertEqual(e.email_it, "it-admin@beispiel.test")
        self.assertEqual(e.smtp_absender, "inventar@beispiel.test")
        self.assertFalse(e.logo)
        self.assertIn("\n\n", e.unterzeichnung_ausgabe)

    def test_seriennummer_pflicht(self):
        ohne = {"Tastatur", "Maus", "Headset", "Notebook-Ständer", "Powerbank", "USB-Hub", "Sonstiges"}
        for k in Kategorie.objects.all():
            self.assertEqual(k.seriennummer_pflicht, k.name not in ohne, k.name)


class KontenTests(Grundlage):
    """F-02, F-03, F-04."""

    def anlegen(self, **daten):
        self.als(self.admin)
        return self.client.post("/konten/neu/", {"rolle": Konto.ROLLE_LESER, "aktiv": "on", **daten}, follow=True)

    def test_einladung_auch_mit_passwort(self):
        self.anlegen(email="neu@beispiel.test", passwort="Zwoelf-Zeichen")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["neu@beispiel.test"])
        self.assertIn("/passwort-setzen/", mail.outbox[0].body)
        self.assertTrue(Konto.objects.get(email="neu@beispiel.test").check_password("Zwoelf-Zeichen"))

    def test_mindestlaenge_beim_anlegen_und_aendern(self):
        antwort = self.anlegen(email="kurz@beispiel.test", passwort="x")
        self.assertContains(antwort, "mindestens 12 Zeichen")
        self.assertFalse(Konto.objects.filter(email="kurz@beispiel.test").exists())
        antwort = self.client.post(
            f"/konten/{self.leser.pk}/",
            {"email": self.leser.email, "rolle": Konto.ROLLE_LESER, "aktiv": "on", "passwort": "x"},
            follow=True,
        )
        self.assertContains(antwort, "mindestens 12 Zeichen")

    def test_mitarbeiter_ohne_person(self):
        antwort = self.anlegen(email="o@beispiel.test", rolle=Konto.ROLLE_MITARBEITER)
        self.assertContains(antwort, "braucht eine Person")
        self.assertFalse(Konto.objects.filter(email="o@beispiel.test").exists())
        form = KontoForm(
            {"email": self.leser.email, "rolle": Konto.ROLLE_MITARBEITER, "aktiv": "on"},
            instance=self.leser,
        )
        self.assertFalse(form.is_valid())

    def test_doppelte_email_ohne_gross_und_klein(self):
        antwort = self.anlegen(email="ADMIN@beispiel.test")
        self.assertContains(antwort, "schon ein Konto")

    def test_inaktives_konto_keine_einladung(self):
        self.anlegen(email="still@beispiel.test", aktiv="")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Konto.objects.get(email="still@beispiel.test").aktiv)

    def _zeit(self, wann):
        return mock.patch("konten.views.jetzt_wie_im_entwicklungsmodus", return_value=wann)

    def test_fristen(self):
        t0 = datetime(2026, 11, 5, 10, 0, tzinfo=tz.utc)
        for erzeuger, frist in (
            (konten_views._token_vergessen, timedelta(hours=1)),
            (konten_views._token_einladung, timedelta(hours=72)),
        ):
            with self._zeit(t0):
                token = erzeuger.make_token(self.ma)
            with self._zeit(t0 + frist - timedelta(minutes=1)):
                self.assertEqual(self.client.get(f"/passwort-setzen/{token}/").status_code, 200)
            with self._zeit(t0 + frist + timedelta(minutes=1)):
                self.assertEqual(self.client.get(f"/passwort-setzen/{token}/").status_code, 400)

    def test_link_der_einladung_gilt_nicht_als_ruecksetzlink(self):
        token = konten_views._token_einladung.make_token(self.ma)
        self.assertFalse(konten_views._token_vergessen.check_token(self.ma, token))

    def test_link_nur_einmal_und_nicht_fuer_deaktivierte(self):
        token = konten_views._token_vergessen.make_token(self.ma)
        pfad = f"/passwort-setzen/{token}/"
        daten = {"passwort": "Zwoelf-Zeichen", "passwort_wiederholung": "Zwoelf-Zeichen"}
        self.assertEqual(self.client.post(pfad, daten).status_code, 302)
        self.assertEqual(self.client.get(pfad).status_code, 400)
        token = konten_views._token_vergessen.make_token(Konto.objects.get(pk=self.ma.pk))
        Konto.objects.filter(pk=self.ma.pk).update(aktiv=False)
        self.assertEqual(self.client.get(f"/passwort-setzen/{token}/").status_code, 400)


class KategorieTests(Grundlage):
    """F-120."""

    def test_loeschen(self):
        frei = Kategorie.objects.create(name="Frei")
        self.als(self.admin)
        self.assertContains(self.client.get(f"/kategorien/{frei.pk}/loeschen/"), 'data-name="loeschen"')
        self.assertContains(self.client.post(f"/kategorien/{frei.pk}/loeschen/", follow=True), "gelöscht")
        self.assertFalse(Kategorie.objects.filter(pk=frei.pk).exists())

    def test_mit_geraeten_oder_im_profil_nicht_loeschbar(self):
        self.geraet()
        im_profil = Kategorie.objects.create(name="Im Profil")
        p = Ausstattungsprofil.objects.create(name="P")
        Profilposition.objects.create(profil=p, kategorie=im_profil, anzahl=1)
        self.als(self.admin)
        for k in (self.kat, im_profil):
            antwort = self.client.post(f"/kategorien/{k.pk}/loeschen/", follow=True)
            self.assertContains(antwort, "nicht löschbar")
            self.assertTrue(Kategorie.objects.filter(pk=k.pk).exists())

    def test_rechte(self):
        for wer in (self.leser, self.ma):
            self.als(wer)
            self.assertEqual(self.client.post(f"/kategorien/{self.kat.pk}/loeschen/").status_code, 403)
        self.assertTrue(Kategorie.objects.filter(pk=self.kat.pk).exists())


class PersonenTests(Grundlage):
    """F-53, F-64, F-121."""

    def formular(self, **neu):
        daten = {
            "anrede": "f", "vorname": "Anna", "nachname": "Becker",
            "email": "anna.becker@beispiel.test", "eintritt": "2024-01-01",
            "austritt": "", "anschrift": "", "aktiv": "on",
        }
        daten.update(neu)
        return daten

    def test_datumsfeld_behaelt_wert(self):
        self.als(self.admin)
        self.assertContains(self.client.get(f"/personen/{self.anna.pk}/aendern/"), 'value="2024-01-01"')

    def test_detail_zeigt_anrede_datum_platz_geraete(self):
        Ort.objects.create(kennung="WMC-WP-01", feste_person=self.anna)
        g = self.geraet()
        services.gerat_ausgeben(g, self.anna, ausgefuehrt_von=self.admin)
        self.als(self.leser)
        antwort = self.client.get(f"/personen/{self.anna.pk}/")
        for text in ("Frau", "01.01.2024", "WMC-WP-01", g.inventarnummer):
            self.assertContains(antwort, text)
        self.assertContains(self.client.get("/personen/"), "WMC-WP-01")

    def test_warnung_beim_aendern(self):
        g = self.geraet()
        services.gerat_ausgeben(g, self.anna, ausgefuehrt_von=self.admin)
        self.als(self.admin)
        pfad = f"/personen/{self.anna.pk}/aendern/"
        antwort = self.client.post(pfad, self.formular(austritt="2099-11-30"))
        self.assertContains(antwort, 'data-test="warnung"')
        self.assertContains(antwort, g.inventarnummer)
        self.anna.refresh_from_db()
        self.assertIsNone(self.anna.austritt)
        self.client.post(pfad, self.formular(austritt="2099-11-30", austritt_bestaetigt="1"))
        self.anna.refresh_from_db()
        self.assertEqual(self.anna.austritt, date(2099, 11, 30))
        self.assertTrue(self.anna.aktiv)

    def test_ohne_geraete_keine_warnung(self):
        self.als(self.admin)
        antwort = self.client.post(f"/personen/{self.anna.pk}/aendern/", self.formular(austritt="2099-11-30"))
        self.assertEqual(antwort.status_code, 302)

    def test_warnung_nennt_reparatur_nicht_ausgemustert(self):
        g = self.geraet()
        services.gerat_ausgeben(g, self.anna, ausgefuehrt_von=self.admin)
        Gerat.objects.filter(pk=g.pk).update(status=Gerat.STATUS_IN_REPARATUR)
        self.als(self.admin)
        pfad = f"/personen/{self.anna.pk}/austritt/eintragen/"
        self.assertContains(self.client.get(pfad), g.inventarnummer)
        Gerat.objects.filter(pk=g.pk).update(status=Gerat.STATUS_AUSGEMUSTERT)
        self.assertNotContains(self.client.get(pfad), g.inventarnummer)

    def test_austritt_person_bleibt_aktiv_meldung_deutsch(self):
        self.als(self.admin)
        antwort = self.client.post(
            f"/personen/{self.anna.pk}/austritt/speichern/", {"austrittsdatum": "2099-11-30"}, follow=True
        )
        self.assertContains(antwort, "Austritt am 30.11.2099 eingetragen")
        self.anna.refresh_from_db()
        self.assertTrue(self.anna.aktiv)

    def test_austritt_unsinniges_datum(self):
        self.als(self.admin)
        antwort = self.client.post(
            f"/personen/{self.anna.pk}/austritt/speichern/", {"austrittsdatum": "2099-13-45"}, follow=True
        )
        self.assertContains(antwort, "gültiges Austrittsdatum")

    def test_tageslauf_person_am_austrittstag_konto_danach(self):
        Person.objects.filter(pk=self.anna.pk).update(austritt=date(2026, 11, 20))
        for stichtag, person_aktiv, konto_aktiv in (
            ("2026-11-19", True, True), ("2026-11-20", False, True), ("2026-11-21", False, False),
        ):
            call_command("tageslauf", stichtag=stichtag, stdout=io.StringIO())
            self.anna.refresh_from_db()
            self.ma.refresh_from_db()
            self.assertEqual(self.anna.aktiv, person_aktiv, stichtag)
            self.assertEqual(self.ma.aktiv, konto_aktiv, stichtag)


class ProfilTests(Grundlage):
    """F-61."""

    def post(self, pfad, name="Test", zeilen=(), bestand=0):
        daten = {
            "name": name,
            "positionen-TOTAL_FORMS": str(max(len(zeilen), 1)),
            "positionen-INITIAL_FORMS": str(bestand),
            "positionen-MIN_NUM_FORMS": "0",
            "positionen-MAX_NUM_FORMS": "1000",
        }
        for i, z in enumerate(zeilen):
            for k, v in z.items():
                daten[f"positionen-{i}-{k}"] = v
        return self.client.post(pfad, daten, follow=True)

    def test_anlegen_und_aendern(self):
        self.als(self.admin)
        self.post("/profile/neu/", zeilen=[{"kategorie": self.kat.pk, "anzahl": 2}])
        p = Ausstattungsprofil.objects.get(name="Test")
        pos = p.positionen.get()
        self.assertEqual(pos.anzahl, 2)
        self.assertContains(self.client.get("/profile/"), "2 × Monitor")
        self.post(
            f"/profile/{p.pk}/aendern/", name="Neu", bestand=1,
            zeilen=[{"id": pos.pk, "kategorie": self.kat.pk, "anzahl": 3}],
        )
        p.refresh_from_db()
        self.assertEqual((p.name, p.positionen.get().anzahl), ("Neu", 3))
        self.post(
            f"/profile/{p.pk}/aendern/", name="Neu", bestand=1,
            zeilen=[{"id": pos.pk, "kategorie": self.kat.pk, "anzahl": 3, "DELETE": "on"}],
        )
        self.assertEqual(p.positionen.count(), 0)

    def test_negativ(self):
        self.als(self.admin)
        self.post("/profile/neu/", zeilen=[{"kategorie": self.kat.pk, "anzahl": 0}])
        self.assertFalse(Ausstattungsprofil.objects.exists())
        self.post("/profile/neu/", zeilen=[
            {"kategorie": self.kat.pk, "anzahl": 1}, {"kategorie": self.kat.pk, "anzahl": 1},
        ])
        self.assertFalse(Ausstattungsprofil.objects.exists())

    def test_rechte(self):
        p = Ausstattungsprofil.objects.create(name="P")
        self.als(self.leser)
        antwort = self.client.get("/profile/")
        self.assertEqual(antwort.status_code, 200)
        self.assertNotContains(antwort, "aktion-bearbeiten")
        for pfad in ("/profile/neu/", f"/profile/{p.pk}/aendern/"):
            self.assertEqual(self.client.get(pfad).status_code, 403)
        self.als(self.ma)
        self.assertEqual(self.client.get("/profile/").status_code, 403)


class OrtFormularTests(Grundlage):
    """F-60."""

    def anlegen(self, **neu):
        self.als(self.admin)
        daten = {"typ": "arbeitsplatz", "kennung": "WMC-WP-99", "standort": "Eschborn", **neu}
        return self.client.post("/orte/neu/", daten, follow=True)

    def test_kennung(self):
        Ort.objects.create(kennung="WMC-WP-16")
        self.assertContains(self.anlegen(kennung="wmc-wp-16"), "gibt es schon")
        self.assertContains(self.anlegen(kennung="WMC WP 1"), "nur Buchstaben")
        self.assertEqual(Ort.objects.count(), 1)

    def test_raumplan_ist_eine_auswahl(self):
        plan = Plan.objects.create(standort="Eschborn", etage="1. OG")
        self.als(self.admin)
        self.assertContains(self.client.get("/orte/neu/"), f'<option value="{plan.pk}">Eschborn, 1. OG</option>', html=True)
        self.anlegen(plan_id=plan.pk)
        self.assertEqual(Ort.objects.get(kennung="WMC-WP-99").plan_id, plan.pk)
        self.anlegen(kennung="WMC-WP-98")
        self.assertIsNone(Ort.objects.get(kennung="WMC-WP-98").plan_id)

    def test_raum_hat_weder_person_noch_profil(self):
        self.anlegen(kennung="RAUM-1", typ="raum", feste_person=self.anna.pk)
        self.assertIsNone(Ort.objects.get(kennung="RAUM-1").feste_person)


class ArbeitsplatzTests(Grundlage):
    """F-62 bis F-66, F-68, F-69."""

    def setUp(self):
        super().setUp()
        self.plan = Plan.objects.create(standort="Eschborn", etage="1. OG")
        self.profil = Ausstattungsprofil.objects.create(name="Standard")
        self.headset = Kategorie.objects.create(name="Headset")
        Profilposition.objects.create(profil=self.profil, kategorie=self.headset, anzahl=1)
        Profilposition.objects.create(profil=self.profil, kategorie=self.kat, anzahl=2)
        self.ort = Ort.objects.create(
            kennung="WMC-WP-01", raum="Großraumbüro", standort="Eschborn", profil=self.profil,
            feste_person=self.anna, plan_id=self.plan.id, position_x=50.1, position_y=55.6,
        )
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-EG", name="IT-Lager")
        self.raum = Ort.objects.create(
            typ=Ort.TYP_RAUM, kennung="ACADEMY", name="Academy-Technik", raum="Academy-Raum",
            standort="Eschborn", plan_id=self.plan.id, position_x=77.4, position_y=36.9,
        )

    def test_bedarf_seite_und_lagerbestand(self):
        # Zurückgegeben ohne Ort, am Lagerort, am Platz auf Lager (zählt nicht)
        self.geraet(self.headset)
        g = self.geraet(self.headset)
        Gerat.objects.filter(pk=g.pk).update(ort=self.lager)
        g = self.geraet(self.headset)
        Gerat.objects.filter(pk=g.pk).update(ort=self.ort)
        self.als(self.leser)
        for pfad in ("/arbeitsplaetze/bedarf/", "/arbeitsplaetze/liste/"):
            antwort = self.client.get(pfad)
            self.assertEqual(antwort.status_code, 200)
            self.assertContains(antwort, 'data-test="bedarfsliste"')
            self.assertContains(antwort, 'data-id="Headset"')
            self.assertContains(antwort, '<b data-test="lager">2</b>', html=True)
            self.assertContains(antwort, '<b data-test="fehlt">1</b>', html=True)

    def test_soll_ist_zaehlt_auf_lager_nicht(self):
        g = self.geraet(self.headset)
        Gerat.objects.filter(pk=g.pk).update(ort=self.ort)
        fehlend = dict(services.soll_ist_abgleich(self.ort)["fehlend"])
        self.assertEqual(fehlend[self.headset], 1)

    def test_texte_in_liste_detail_plan_popup(self):
        self.als(self.admin)
        for pfad in ("/arbeitsplaetze/liste/", "/arbeitsplaetze/WMC-WP-01/", "/arbeitsplaetze/WMC-WP-01/popup/"):
            self.assertContains(self.client.get(pfad), "fehlt: 1 × Headset")
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertContains(antwort, 'data-soll-ist="unvollstaendig"')
        self.assertContains(antwort, 'aria-label="Arbeitsplatz WMC-WP-01, unvollständig, fehlt: 1 × Headset, fehlt: 2 × Monitor"')
        self.assertNotContains(antwort, "fehlt etwas")
        self.assertContains(self.client.get("/arbeitsplaetze/?ansicht=liste"), "Anna Becker")

    def test_mehr_als_soll_ist_nicht_unvollstaendig(self):
        for k in (self.headset, self.kat, self.kat, self.kat):
            services.gerat_ausgeben(self.geraet(k), self.ort, ausgefuehrt_von=self.admin)
        self.als(self.admin)
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertContains(antwort, 'data-soll-ist="mehr"')
        self.assertNotContains(antwort, "Unvollständige Plätze")
        self.assertContains(antwort, "1 von 1 Arbeitsplätzen")

    def test_popup_zeigt_raum_und_etage_und_aktionen(self):
        self.als(self.admin)
        antwort = self.client.get("/arbeitsplaetze/WMC-WP-01/popup/")
        for text in ("Großraumbüro", "1. OG", "Anna Becker", "Standard", "Fehlendes vom Lager ausgeben", "Etiketten für den Platz"):
            self.assertContains(antwort, text)
        self.als(self.leser)
        antwort = self.client.get("/arbeitsplaetze/WMC-WP-01/popup/")
        self.assertNotContains(antwort, "Fehlendes vom Lager ausgeben")
        self.assertNotContains(antwort, "Etiketten für den Platz")

    def test_popup_etiketten_auch_wenn_nichts_fehlt(self):
        for k in (self.headset, self.kat, self.kat):
            services.gerat_ausgeben(self.geraet(k), self.ort, ausgefuehrt_von=self.admin)
        self.als(self.admin)
        antwort = self.client.get("/arbeitsplaetze/WMC-WP-01/popup/")
        self.assertContains(antwort, "Etiketten für den Platz")
        self.assertNotContains(antwort, "Fehlendes vom Lager ausgeben")

    def test_fehlendes_ausgeben(self):
        frei = self.geraet(self.headset)
        m1, m2, m3 = self.geraet(), self.geraet(), self.geraet()
        Gerat.objects.filter(pk=m3.pk).update(ort=self.lager)
        pfad = "/arbeitsplaetze/WMC-WP-01/ausgeben/"
        self.als(self.admin)
        antwort = self.client.get(pfad)
        self.assertContains(antwort, frei.inventarnummer)
        self.assertContains(antwort, "checked", count=3)
        # Mehr als fehlen und fremdes Gerät: nichts passiert
        antwort = self.client.post(pfad, {"gerat": [m1.pk, m2.pk, m3.pk]}, follow=True)
        self.assertContains(antwort, "fehlen nur 2")
        antwort = self.client.post(pfad, {"gerat": [999999]}, follow=True)
        self.assertContains(antwort, "nicht mehr frei")
        antwort = self.client.post(pfad, {}, follow=True)
        self.assertContains(antwort, "mindestens ein Gerät")
        self.assertEqual(Gerat.objects.filter(ort=self.ort).count(), 0)
        antwort = self.client.post(pfad, {"gerat": [frei.pk, m1.pk]}, follow=True)
        self.assertContains(antwort, "2 Gerät(e) an WMC-WP-01 ausgegeben")
        frei.refresh_from_db()
        self.assertEqual((frei.status, frei.ort_id, frei.person_id), (Gerat.STATUS_IN_BENUTZUNG, self.ort.pk, None))
        self.assertEqual(frei.protokolle.count(), 0)

    def test_fehlendes_ausgeben_rechte(self):
        pfad = "/arbeitsplaetze/WMC-WP-01/ausgeben/"
        for wer in (self.leser, self.ma):
            self.als(wer)
            self.assertEqual(self.client.get(pfad).status_code, 403)
            self.assertEqual(self.client.post(pfad, {"gerat": [1]}).status_code, 403)

    def test_raum_flaeche_und_popup(self):
        services.gerat_ausgeben(self.geraet(), self.raum, ausgefuehrt_von=self.admin)
        self.als(self.leser)
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertContains(antwort, "1 Gerät")
        self.assertContains(antwort, 'data-pfad="/arbeitsplaetze/raum/ACADEMY/popup/"', count=2)
        self.assertNotContains(antwort, f"/orte/{self.raum.pk}/aendern/")
        antwort = self.client.get("/arbeitsplaetze/raum/ACADEMY/popup/")
        self.assertNotContains(antwort, "Feste Person")
        self.assertNotContains(antwort, "Profil:")
        self.assertContains(antwort, "Monitor")

    def test_ohne_position_nennt_raeume_und_orte_ohne_plan(self):
        Ort.objects.create(typ=Ort.TYP_RAUM, kennung="RAUM-OHNE", name="R", standort="Eschborn", plan_id=self.plan.id)
        Ort.objects.create(kennung="WMC-WP-99", standort="Eschborn")
        Ort.objects.create(kennung="ANDERSWO", standort="Frankfurt")
        self.als(self.admin)
        antwort = self.client.get("/arbeitsplaetze/")
        self.assertContains(antwort, "Ohne Position (2)")
        self.assertContains(antwort, "RAUM-OHNE")
        self.assertContains(antwort, "WMC-WP-99")
        self.assertNotContains(antwort, "ANDERSWO")

    def test_im_raumplan_zeigen(self):
        plan2 = Plan.objects.create(standort="Frankfurt", etage="2. OG")
        eg = Ort.objects.create(kennung="WMC-EG-01", plan_id=plan2.id, position_x=10, position_y=10)
        am_plan2 = self.geraet()
        services.gerat_ausgeben(am_plan2, eg, ausgefuehrt_von=self.admin)
        notebook = self.geraet()
        services.gerat_ausgeben(notebook, self.anna, ausgefuehrt_von=self.admin)
        lager = self.geraet()
        Gerat.objects.filter(pk=lager.pk).update(ort=self.lager)
        self.als(self.admin)
        marke = 'data-test="aktion-im-raumplan"'
        self.assertContains(self.client.get(f"/geraete/{am_plan2.inventarnummer}/"), "hervorheben=WMC-EG-01")
        self.assertContains(self.client.get(f"/geraete/{notebook.inventarnummer}/"), "hervorheben=WMC-WP-01")
        self.assertNotContains(self.client.get(f"/geraete/{lager.inventarnummer}/"), marke)
        for wert in ("WMC-EG-01", "Eschborn|WMC-EG-01"):
            antwort = self.client.get("/arbeitsplaetze/", {"hervorheben": wert})
            self.assertContains(antwort, 'data-hervorheben="WMC-EG-01"')
            self.assertContains(antwort, f'data-id="{plan2.pk}"')

    def test_liste_nach_kategorie_mit_name_und_nummer(self):
        g = self.geraet(self.headset)
        self.als(self.admin)
        for wert in ("Headset", self.headset.pk):
            self.assertContains(self.client.get("/geraete/", {"kategorie": wert}), g.inventarnummer)
        self.assertNotContains(self.client.get("/geraete/", {"kategorie": "Monitor"}), g.inventarnummer)


class AblageTest(Grundlage):
    """Eigene DATEIABLAGE, damit die Tests die laufende Instanz nicht berühren."""

    def setUp(self):
        super().setUp()
        self.ablage = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ablage, ignore_errors=True)
        ueberschrieben = override_settings(MEDIA_ROOT=self.ablage)
        ueberschrieben.enable()
        self.addCleanup(ueberschrieben.disable)


class PlanHochladenTests(AblageTest):
    """F-67, N-02."""

    def setUp(self):
        super().setUp()
        self.plan = Plan.objects.create(standort="Eschborn", etage="1. OG")
        self.plan2 = Plan.objects.create(standort="Eschborn", etage="EG")
        self.als(self.admin)

    def hochladen(self, plan, name, inhalt):
        datei = SimpleUploadedFile(name, inhalt)
        return self.client.post(f"/arbeitsplaetze/plan/{plan.pk}/bearbeiten/", {"grundriss": datei}, follow=True)

    def test_inhalt_entscheidet_und_alter_plan_bleibt(self):
        self.assertContains(self.hochladen(self.plan, "gut.png", png()), "Grundriss gespeichert")
        self.plan.refresh_from_db()
        alt = self.plan.grundriss.name
        for name, inhalt in (
            ("falsch.png", b"kein Bild"),
            ("html.png", b"<html><script>x</script></html>"),
            ("kaputt.png", b"\x89PNG\r\n\x1a\n" + b"kaputt"),
            ("html.svg", b"<html></html>"),
            ("doctype.svg", b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>'),
            ("falsch.pdf", b"kein PDF"),
            ("programm.exe", png()),
        ):
            antwort = self.hochladen(self.plan, name, inhalt)
            self.assertContains(antwort, "Grundriss nicht gespeichert", msg_prefix=name)
            self.plan.refresh_from_db()
            self.assertEqual(self.plan.grundriss.name, alt, name)
            self.assertEqual(self.plan.grundriss.read(), png(), name)
            self.plan.grundriss.close()

    def test_groesse(self):
        antwort = self.hochladen(self.plan, "gross.png", b"\x89PNG\r\n\x1a\n" + b"\0" * (10 * 1024 * 1024))
        self.assertContains(antwort, "größer als 10 MB")

    def test_jeder_plan_hat_seine_datei(self):
        self.hochladen(self.plan, "a.png", png(40, 20))
        self.hochladen(self.plan2, "b.png", png(80, 20))
        self.plan.refresh_from_db()
        self.plan2.refresh_from_db()
        self.assertNotEqual(self.plan.grundriss.name, self.plan2.grundriss.name)
        self.assertEqual(self.plan.grundriss.read(), png(40, 20))
        self.plan.grundriss.close()

    def test_alte_gemeinsame_datei_wird_nicht_geloescht(self):
        self.hochladen(self.plan, "a.png", png())
        self.plan.refresh_from_db()
        Plan.objects.filter(pk=self.plan2.pk).update(grundriss=self.plan.grundriss.name)
        self.plan2.refresh_from_db()
        self.hochladen(self.plan2, "b.png", png(80, 20))
        self.assertTrue(self.plan.grundriss.storage.exists(self.plan.grundriss.name))

    def test_svg_kopfzeile(self):
        self.assertContains(self.hochladen(self.plan, "s.svg", SVG), "Grundriss gespeichert")
        antwort = self.client.get(f"/arbeitsplaetze/plan/{self.plan.pk}/grundriss/")
        self.assertEqual(antwort["Content-Type"], "image/svg+xml")
        self.assertIn("script-src 'none'", antwort["Content-Security-Policy"])

    def test_png_ohne_svg_regel(self):
        self.hochladen(self.plan, "a.png", png())
        antwort = self.client.get(f"/arbeitsplaetze/plan/{self.plan.pk}/grundriss/")
        self.assertEqual(antwort["Content-Type"], "image/png")
        self.assertNotIn("script-src 'none'", antwort["Content-Security-Policy"])

    def test_position(self):
        ort = Ort.objects.create(kennung="WMC-WP-01", plan_id=self.plan.pk)
        pfad = f"/arbeitsplaetze/plan/{self.plan.pk}/bearbeiten/"
        antwort = self.client.post(pfad, {"ort": ort.pk, "x": "12.34", "y": "0"}, follow=True)
        self.assertContains(antwort, "Position von WMC-WP-01 gespeichert")
        ort.refresh_from_db()
        self.assertEqual((ort.position_x, ort.position_y), (12.3, 0.0))
        self.assertIsNone(ort.aktualisiert_am, "Eine Position ist keine Prüfung (F-89)")
        # x = 0 bleibt auf dem Plan, nicht unter „ohne Position“
        self.assertContains(antwort, 'data-test="platz"')
        for x, y in (("150", "5"), ("5", "-5"), ("abc", "5"), ("nan", "5")):
            antwort = self.client.post(pfad, {"ort": ort.pk, "x": x, "y": y}, follow=True)
            self.assertContains(antwort, "data-test=\"fehler\"")
            ort.refresh_from_db()
            self.assertEqual(ort.position_x, 12.3)

    def test_ort_ohne_plan_wird_beim_setzen_zugeordnet(self):
        ort = Ort.objects.create(kennung="WMC-WP-02", standort="Eschborn")
        self.client.post(f"/arbeitsplaetze/plan/{self.plan.pk}/bearbeiten/", {"ort": ort.pk, "x": "1", "y": "2"})
        ort.refresh_from_db()
        self.assertEqual(ort.plan_id, self.plan.pk)

    def test_ort_eines_anderen_plans_wird_abgelehnt(self):
        ort = Ort.objects.create(kennung="WMC-WP-03", plan_id=self.plan2.pk)
        antwort = self.client.post(
            f"/arbeitsplaetze/plan/{self.plan.pk}/bearbeiten/", {"ort": ort.pk, "x": "1", "y": "2"}, follow=True
        )
        self.assertContains(antwort, "ungültig")

    def test_plan_anlegen(self):
        antwort = self.client.post("/arbeitsplaetze/plan/neu/", {"standort": "Eschborn", "etage": "2. OG", "name": "Oben"}, follow=True)
        self.assertContains(antwort, "angelegt")
        antwort = self.client.post("/arbeitsplaetze/plan/neu/", {"standort": "Eschborn", "etage": "2. OG"}, follow=True)
        self.assertContains(antwort, "gibt es schon einen Plan")
        self.assertEqual(Plan.objects.filter(etage="2. OG").count(), 1)

    def test_plan_rechte(self):
        for wer in (self.leser, self.ma):
            self.als(wer)
            self.assertEqual(self.client.get("/arbeitsplaetze/plan/neu/").status_code, 403)
            self.assertEqual(self.client.post(f"/arbeitsplaetze/plan/{self.plan.pk}/bearbeiten/", {"ort": 1, "x": 1, "y": 1}).status_code, 403)


class EinstellungenTests(AblageTest):
    """F-90, F-122, N-02."""

    def formular(self, **neu):
        daten = {
            "firmenname": "Testfirma", "absenderzeile": "", "telefon": "", "email_it": "",
            "nutzungsbedingungen_version": "1", "erklaerungen_version": "1", "unterzeichnung_version": "1",
            "erklaerungen_ruecknahme_version": "1", "unterzeichnung_ruecknahme_version": "1",
            "etikettenformat": "a4", "frist_leihe_tage": 1, "frist_garantie_tage": 30,
            "frist_unterschrift_tage": 3, "frist_gegenzeichnung_tage": 3, "smtp_port": 587,
        }
        daten.update(neu)
        return daten

    def speichern(self, **neu):
        self.als(self.admin)
        return self.client.post("/einstellungen/", self.formular(**neu), follow=True)

    def test_testmail_formular_ist_nicht_geschachtelt(self):
        self.als(self.admin)
        html = self.client.get("/einstellungen/").content.decode()
        testmail = html.index('id="testmail-formular"')
        haupt = html.index('data-test="einstellungen-formular"')
        self.assertLess(testmail, haupt)
        self.assertEqual(html.count("</form>", testmail, haupt), 1)
        self.assertIn('form="testmail-formular"', html)

    def test_speichern_und_passwort_bleibt(self):
        self.assertContains(self.speichern(smtp_passwort="geheim", smtp_server="s"), "Einstellungen gespeichert")
        e = Einstellungen.aktuelles()
        self.assertEqual((e.firmenname, e.smtp_passwort, e.smtp_server), ("Testfirma", "geheim", "s"))
        self.speichern()
        e.refresh_from_db()
        self.assertEqual(e.smtp_passwort, "geheim")
        self.assertNotContains(self.client.get("/einstellungen/"), "geheim")

    def test_alle_mailarten_sind_schaltbar(self):
        self.speichern()
        e = Einstellungen.aktuelles()
        for name in (
            "mail_leihe_endet_morgen", "mail_leihe_ueberfaellig", "mail_verleih_anfrage",
            "mail_verleih_genehmigung", "mail_verleih_ablehnung", "mail_garantie_sammelmail",
            "mail_unterzeichen_sammelmail", "mail_protokoll_gesendet",
            "mail_gegenzeichnung_erinnerung", "mail_protokoll_unterzeichnet",
        ):
            self.assertFalse(getattr(e, name), name)
        self.speichern(mail_leihe_endet_morgen="on")
        e.refresh_from_db()
        self.assertTrue(e.mail_leihe_endet_morgen)

    def test_fehler_behaelt_eingaben(self):
        antwort = self.speichern(firmenname="", telefon="+49 1")
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertContains(antwort, "+49 1")
        self.assertEqual(Einstellungen.aktuelles().telefon, "")

    def test_logo(self):
        for name, inhalt, text in (
            ("html.png", b"<html></html>", "Inhalt der Datei"),
            ("logo.jpg", png(), "muss eine PNG"),
            ("gross.png", b"\x89PNG\r\n\x1a\n" + b"\0" * (10 * 1024 * 1024), "größer als 10 MB"),
        ):
            antwort = self.speichern(logo=SimpleUploadedFile(name, inhalt))
            self.assertContains(antwort, text, msg_prefix=name)
            self.assertFalse(Einstellungen.aktuelles().logo, name)
        self.speichern(logo=SimpleUploadedFile("l.png", png()))
        e = Einstellungen.aktuelles()
        self.assertEqual(e.logo.read(), png())
        e.logo.close()
        antwort = self.client.get("/einstellungen/logo/")
        self.assertEqual(antwort["Content-Type"], "image/png")
        self.speichern(logo=SimpleUploadedFile("l.svg", SVG))
        antwort = self.client.get("/einstellungen/logo/")
        self.assertEqual(antwort["Content-Type"], "image/svg+xml")
        self.assertIn("script-src 'none'", antwort["Content-Security-Policy"])
        self.assertContains(self.client.get("/einstellungen/"), '<img class="logo-vorschau"')
        self.als(self.leser)
        self.assertEqual(self.client.get("/einstellungen/logo/").status_code, 403)

    def test_firmendaten(self):
        self.speichern(telefon="+49 1", absenderzeile="Zeile", email_it="it@beispiel.test")
        daten = firmendaten()
        self.assertEqual(
            (daten["firmenname"], daten["absenderzeile"], daten["telefon"], daten["email_it"], daten["logo_pfad"]),
            ("Testfirma", "Zeile", "+49 1", "it@beispiel.test", ""),
        )
        self.speichern(logo=SimpleUploadedFile("l.png", png()))
        self.assertTrue(firmendaten()["logo_pfad"].endswith("logo/logo.png"))

    def test_testmail(self):
        self.speichern(smtp_absender="pruef@beispiel.test")
        antwort = self.client.post("/einstellungen/testmail/", {"empfaenger": "a@beispiel.test"}, follow=True)
        self.assertContains(antwort, "Testmail an a@beispiel.test gesendet")
        self.assertEqual(mail.outbox[0].from_email, "pruef@beispiel.test")
        antwort = self.client.post("/einstellungen/testmail/", {"empfaenger": "kein"}, follow=True)
        self.assertContains(antwort, "gültige E-Mail-Adresse")
        self.assertEqual(len(mail.outbox), 1)
        with mock.patch("stammdaten.views._testmail_senden", side_effect=ConnectionRefusedError("verweigert")):
            antwort = self.client.post("/einstellungen/testmail/", {"empfaenger": "a@beispiel.test"}, follow=True)
        self.assertContains(antwort, "Testmail fehlgeschlagen: verweigert")

    def test_smtp_werte_aus_den_einstellungen(self):
        e = Einstellungen.aktuelles()
        e.smtp_server, e.smtp_port, e.smtp_benutzer, e.smtp_passwort, e.smtp_tls = "mail.test", 2525, "u", "p", True
        e.save()
        b = EinstellungenSmtpBackend()
        self.assertEqual((b.host, b.port, b.username, b.password, b.use_tls, b.use_ssl), ("mail.test", 2525, "u", "p", True, False))
        e.smtp_port = 465
        e.save()
        b = EinstellungenSmtpBackend()
        self.assertEqual((b.use_tls, b.use_ssl), (False, True))
        e.smtp_tls = False
        e.save()
        b = EinstellungenSmtpBackend()
        self.assertEqual((b.use_tls, b.use_ssl), (False, False))

    def test_rechte(self):
        for wer in (self.leser, self.ma):
            self.als(wer)
            self.assertEqual(self.client.post("/einstellungen/", self.formular()).status_code, 403)
            self.assertEqual(self.client.post("/einstellungen/testmail/", {"empfaenger": "a@beispiel.test"}).status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


class DateitypTests(TestCase):
    def test_erkennung(self):
        self.assertEqual(dateityp_erkennen(png()), "png")
        self.assertEqual(dateityp_erkennen(SVG), "svg")
        self.assertEqual(dateityp_erkennen(b"%PDF-1.7"), "pdf")
        self.assertEqual(dateityp_erkennen(b"\xff\xd8\xff kaputt"), "")
        self.assertEqual(dateityp_erkennen(b"MZ"), "")


class MailTests(Grundlage):
    """F-94, F-95, F-96."""

    def setUp(self):
        super().setUp()
        self.felix = Person.objects.create(vorname="Felix", nachname="Hoffmann", email="felix.hoffmann@beispiel.test")
        self.felix_konto = konto("felix.hoffmann@beispiel.test", Konto.ROLLE_MITARBEITER, self.felix)
        self.jonas = Person.objects.create(vorname="Jonas", nachname="Weber", email="jonas.weber@beispiel.test")
        e = Einstellungen.aktuelles()
        e.email_it = "admin@beispiel.test"
        e.smtp_absender = "absender@beispiel.test"
        e.absenderzeile = "Testzeile"
        e.save()
        self.e = e
        self.notebook = Kategorie.objects.create(name="Notebook")

    def leihe(self, person, bis, status=Leihe.STATUS_AUSGEGEBEN, nr=[0]):
        nr[0] += 1
        g = self.geraet(self.notebook, leihpool=True)
        return Leihe.objects.create(
            nr=f"L-{nr[0]:04d}", person=person, gerat=g, kat=self.notebook, beginn=bis - timedelta(days=5),
            ende=bis, rueckgabe_bis=bis, status=status, zeitpunkt=bis,
        )

    def lauf(self, stichtag):
        call_command("tageslauf", stichtag=stichtag, stdout=io.StringIO())

    def test_konto_deaktiviert(self):
        self.assertFalse(konto_deaktiviert("jonas.weber@beispiel.test"))
        self.assertFalse(konto_deaktiviert("felix.hoffmann@beispiel.test"))
        Konto.objects.filter(pk=self.felix_konto.pk).update(aktiv=False)
        self.assertTrue(konto_deaktiviert("FELIX.hoffmann@beispiel.test"))
        self.assertEqual(aktive_empfaenger(["felix.hoffmann@beispiel.test", "", "jonas.weber@beispiel.test"]), ["jonas.weber@beispiel.test"])

    def test_keine_erinnerung_an_deaktivierte_konten(self):
        Konto.objects.filter(pk=self.felix_konto.pk).update(aktiv=False)
        self.leihe(self.felix, date(2026, 11, 3))
        self.leihe(self.anna, date(2026, 11, 3))
        self.lauf("2026-11-02")
        self.assertEqual([m.to for m in mail.outbox], [["anna.becker@beispiel.test"]])
        self.assertEqual(mail.outbox[0].from_email, "absender@beispiel.test")
        self.assertIn("http://", mail.outbox[0].body)
        self.assertIn("/meine-geraete/", mail.outbox[0].body)
        self.assertNotIn("/verleih/", mail.outbox[0].body)
        self.assertIn("Testzeile", mail.outbox[0].body)

    def test_ueberfaellig_an_it_auch_ohne_aktives_konto(self):
        Konto.objects.filter(pk=self.felix_konto.pk).update(aktiv=False)
        self.leihe(self.felix, date(2026, 11, 1))
        self.lauf("2026-11-03")
        self.assertEqual(mail.outbox[0].to, ["admin@beispiel.test"])
        self.assertIn("Felix Hoffmann", mail.outbox[0].body)
        self.assertIn("/meine-geraete/", mail.outbox[0].body)
        self.assertIn("/verleih/", mail.outbox[0].body)

    def test_entscheidung_und_anfrage(self):
        leihe = self.leihe(self.anna, date(2026, 11, 3))
        services._mail_entscheidung_an_person(leihe, genehmigt=True)
        services._mail_entscheidung_an_person(leihe, genehmigt=False, begruendung="Nein")
        for m in mail.outbox:
            self.assertIn("/meine-geraete/", m.body)
            self.assertNotIn("/verleih/", m.body)
            self.assertEqual(m.from_email, "absender@beispiel.test")
        mail.outbox.clear()
        Konto.objects.filter(pk=self.ma.pk).update(aktiv=False)
        services._mail_entscheidung_an_person(leihe, genehmigt=True)
        self.assertEqual(len(mail.outbox), 0)
        services._mail_anfrage_an_it(leihe)
        self.assertEqual(mail.outbox[0].to, ["admin@beispiel.test"])
        self.assertIn("/verleih/", mail.outbox[0].body)

    def test_schalter_anfrage(self):
        leihe = self.leihe(self.anna, date(2026, 11, 3))
        self.e.mail_verleih_anfrage = False
        self.e.save()
        services._mail_anfrage_an_it(leihe)
        self.assertEqual(len(mail.outbox), 0)

    def test_sammelmail_alle_offenen_staende_und_frist(self):
        def proto(nr, stand, datum, **k):
            Protokoll.objects.create(nr=nr, person=self.felix, geraet=self.geraet(self.notebook), datum=datum, stand=stand, **k)

        alt = date(2026, 11, 3)
        proto("UP-1", Protokoll.STAND_BEARBEITER_OFFEN, alt)
        proto("UP-2", Protokoll.STAND_SCAN_OFFEN, alt)
        proto("UP-3", Protokoll.STAND_GEGENZEICHNUNG_OFFEN, alt, gegenzeichnung_token="a", gegenzeichnung_token_erstellt=datetime(2026, 11, 3, 9, tzinfo=tz.utc))
        proto("UP-4", Protokoll.STAND_SCAN_OFFEN, date(2026, 11, 6))
        proto("UP-5", Protokoll.STAND_ENTWURF, alt)
        self.lauf("2026-11-09")
        sammel = [m for m in mail.outbox if "Sammelmail" in m.subject][0]
        for nr in ("UP-1", "UP-2", "UP-3"):
            self.assertIn(nr, sammel.body)
        self.assertNotIn("UP-4", sammel.body)
        self.assertNotIn("UP-5", sammel.body)
        self.assertIn("(3)", sammel.body)
        self.assertEqual(sammel.to, ["admin@beispiel.test"])

    def test_fristen_aus_den_einstellungen(self):
        self.e.frist_garantie_tage = 45
        self.e.frist_leihe_tage = 2
        self.e.save()
        g = self.geraet(self.notebook, garantie_bis=date(2026, 12, 20))
        self.leihe(self.anna, date(2026, 11, 11))
        self.lauf("2026-11-09")
        sammel = [m for m in mail.outbox if "Sammelmail" in m.subject][0]
        self.assertIn(g.inventarnummer, sammel.body)
        self.assertTrue([m for m in mail.outbox if "endet in 2 Tagen" in m.subject])

    def test_gegenzeichnung_absolut_absender_und_schalter(self):
        p = Protokoll.objects.create(nr="UP-7", person=self.felix, geraet=self.geraet(self.notebook), datum=date(2026, 11, 3))
        services._mail_gegenzeichnen_link(p, "tok", "felix.hoffmann@beispiel.test")
        self.assertRegex(mail.outbox[0].body, r"Link: https?://[^/]+/signieren/tok/")
        self.assertEqual(mail.outbox[0].from_email, "absender@beispiel.test")
        self.assertNotIn("Wamocon", mail.outbox[0].body)
        self.e.mail_protokoll_gesendet = False
        self.e.save()
        services._mail_gegenzeichnen_link(p, "tok", "felix.hoffmann@beispiel.test")
        self.assertEqual(len(mail.outbox), 1)

    def test_ausnahmen_gehen_an_deaktivierte_konten(self):
        Konto.objects.filter(pk=self.felix_konto.pk).update(aktiv=False)
        p = Protokoll.objects.create(nr="UP-8", person=self.felix, geraet=self.geraet(self.notebook), datum=date(2026, 11, 3), gegenzeichnung_empfaenger=self.felix.email)
        services._mail_gegenzeichnen_link(p, "tok", self.felix.email)
        services.protokoll_code_senden(p)
        services._mail_anhang(p, b"%PDF", "a.pdf", self.felix.email)
        self.assertEqual([m.to for m in mail.outbox], [[self.felix.email]] * 3)

    def test_kein_fester_absender_mehr_im_code(self):
        from pathlib import Path
        import geraete

        quelle = Path(geraete.__file__).parent / "services.py"
        self.assertNotIn("it@wamocon.de", quelle.read_text(encoding="utf-8"))
