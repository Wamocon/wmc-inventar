"""Verleih und Leihen der Mitarbeiter nach der Prüfung vom 05.11.2026.

F-30 bis F-37, F-91 bis F-93, F-110, F-111. Die Tests laufen gegen die Beispieldaten
aus TESTSCHNITTSTELLE 2 und mit der Uhr der Anwendung (var/jetzt.txt, hier eine
eigene Datei), damit Fristen nicht vom Tag des Testlaufs abhängen.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from geraete import services
from geraete.models import Gerat, Leihe, Protokoll, Vorgang
from konten.models import Konto
from stammdaten.models import Einstellungen, Kategorie, Person

PASSWORT = "Beispiel-Passwort-2026"
HEUTE = date(2027, 3, 1)


@override_settings(DEBUG=True)
class VerleihTestCase(TestCase):
    """Beispieldaten, feste Uhr, Leihpool mit drei Smartphones."""

    @classmethod
    def setUpTestData(cls):
        with open("/dev/null", "w") as still:
            call_command("beispieldaten", verbosity=0, stdout=still)
        cls.admin = Konto.objects.get(email="it-admin@beispiel.test")
        cls.leser = Konto.objects.get(email="gf@beispiel.test")
        cls.anna_konto = Konto.objects.get(email="anna.becker@beispiel.test")
        cls.felix_konto = Konto.objects.get(email="felix.hoffmann@beispiel.test")
        cls.anna = cls.anna_konto.person
        cls.felix = cls.felix_konto.person
        cls.smartphone = Kategorie.objects.get(name="Smartphone")
        cls.notebook = Kategorie.objects.get(name="Notebook")
        cls.a = cls._pool("SN-A")
        cls.b = cls._pool("SN-B")
        cls.c = cls._pool("SN-C")

    @classmethod
    def _pool(cls, seriennummer, kategorie=None):
        return services.gerat_anlegen(
            kategorie=kategorie or cls.smartphone,
            hersteller="Samsung",
            modell="Galaxy",
            seriennummer=seriennummer,
            leihpool=True,
            zustand=Gerat.ZUSTAND_GUT,
            erzeugt_von=cls.admin,
        )

    def setUp(self):
        verzeichnis = tempfile.TemporaryDirectory()
        self.addCleanup(verzeichnis.cleanup)
        self.uhr = Path(verzeichnis.name) / "jetzt.txt"
        muster = mock.patch("konten.zeit.JETZT_DATEI", self.uhr)
        muster.start()
        self.addCleanup(muster.stop)
        self.stellen(HEUTE)
        mail.outbox.clear()

    def stellen(self, tag: date) -> None:
        self.uhr.write_text(f"{tag.isoformat()}T10:00", encoding="utf-8")

    def client_fuer(self, konto=None) -> Client:
        client = Client(HTTP_HOST="127.0.0.1")
        if konto is not None:
            client.force_login(konto)
        return client

    def anfragen(self, von, bis, person=None, gerat=None, kategorie=None) -> Leihe:
        return services.leihe_anfragen(
            person=person or self.anna,
            kat=kategorie or self.smartphone,
            beginn=von,
            ende=bis,
            zweck="Messe",
            gerat=gerat,
            erzeugt_von=self.anna_konto,
        )

    def genehmigt(self, von, bis, gerat, person=None) -> Leihe:
        leihe = self.anfragen(von, bis, person=person)
        return services.leihe_genehmigen(leihe, gerat=gerat, ausgefuehrt_von=self.admin)

    def ausgegeben(self, bis, gerat=None, person=None) -> Leihe:
        return services.leih_gerat_ausgeben(
            gerat=gerat or self.a,
            person=person or self.anna,
            rueckgabe_bis=bis,
            zweck="Messe",
            ausgefuehrt_von=self.admin,
        )


class DirektverleihTests(VerleihTestCase):
    """F-30: Protokoll wie F-21, Status zum selben Zeitpunkt."""

    def _verleih(self, unterschrift, bis=None):
        return self.client_fuer(self.admin).post(
            f"/geraete/{self.a.inventarnummer}/verleih/",
            {
                "person": self.anna.pk,
                "rueckgabe_bis": (bis or HEUTE + timedelta(days=10)).isoformat(),
                "zweck": "Messe",
                "unterschrift": unterschrift,
            },
        )

    def test_mit_signatur_erst_mit_der_signatur_ausgegeben(self):
        self.assertEqual(self._verleih("tool").status_code, 302)
        self.a.refresh_from_db()
        leihe = Leihe.objects.get(gerat=self.a)
        protokoll = leihe.protokolle.get()
        self.assertEqual(self.a.status, Gerat.STATUS_AUF_LAGER)
        self.assertTrue(self.a.reserviert)
        self.assertEqual(leihe.status, Leihe.STATUS_GENEHMIGT)
        self.assertEqual(protokoll.stand, Protokoll.STAND_BEARBEITER_OFFEN)
        self.assertEqual(protokoll.bearbeiter, self.admin.bezeichnung())
        self.assertFalse(self.a.vorgaenge.filter(typ=Vorgang.TYP_AUSGABE).exists())
        # Vor der Signatur kein Knopf „Verlängern“, dafür der Weg zum Protokoll.
        seite = self.client_fuer(self.admin).get("/verleih/").content.decode()
        self.assertIn(f'data-id="{leihe.nr}" data-stand="genehmigt"', seite)
        self.assertNotIn('data-test="verlaengern"', seite)
        self.assertIn(f"/protokolle/{protokoll.nr}/", seite)
        # Unter „Meine Leihen“ ist der Entwurf noch nicht zu sehen.
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/").content.decode()
        self.assertNotIn(leihe.nr, seite)

        antwort = self.client_fuer(self.admin).post(
            f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PASSWORT}
        )
        self.assertEqual(antwort.status_code, 302)
        self.a.refresh_from_db()
        leihe.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(self.a.person, self.anna)
        self.assertFalse(self.a.reserviert)
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)
        vorgang = self.a.vorgaenge.get(typ=Vorgang.TYP_AUSGABE)
        self.assertEqual(vorgang.leihgabe_an, self.anna)
        self.assertEqual(vorgang.zurueck_am, leihe.rueckgabe_bis)

    def test_papier_sofort_und_signatur_aendert_den_status_nicht(self):
        self._verleih("papier")
        self.a.refresh_from_db()
        leihe = Leihe.objects.get(gerat=self.a)
        protokoll = leihe.protokolle.get()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)
        self.assertEqual(protokoll.unterschrift_art, "papier")
        self.assertEqual(protokoll.stand, Protokoll.STAND_SCAN_OFFEN)
        self.assertEqual(protokoll.checkliste_unbeantwortet(), [])

        self.client_fuer(self.admin).post(
            f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PASSWORT}
        )
        self.a.refresh_from_db()
        leihe.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)
        self.assertEqual(self.a.vorgaenge.filter(typ=Vorgang.TYP_AUSGABE).count(), 1)

    def test_rueckgabedatum_muss_nach_heute_liegen(self):
        for bis in (HEUTE - timedelta(days=1), HEUTE):
            with self.subTest(bis=bis):
                antwort = self._verleih("papier", bis=bis)
                self.assertEqual(antwort.status_code, 200)
                self.assertContains(antwort, 'data-test="fehler"')
                self.assertContains(antwort, "muss nach heute liegen")
        self.assertFalse(Leihe.objects.exists())
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_AUF_LAGER)

    def test_verworfener_entwurf_aendert_nichts(self):
        self._verleih("tool")
        protokoll = Protokoll.objects.get(geraet=self.a)
        antwort = self.client_fuer(self.admin).post(f"/protokolle/{protokoll.nr}/abbrechen/")
        self.assertEqual(antwort.status_code, 302)
        self.a.refresh_from_db()
        self.assertFalse(Leihe.objects.filter(gerat=self.a).exists())
        self.assertFalse(self.a.reserviert)
        self.assertEqual(self.a.status, Gerat.STATUS_AUF_LAGER)

    def test_protokollseite_leihe_ohne_checkliste(self):
        self._verleih("tool")
        protokoll = Protokoll.objects.get(geraet=self.a)
        antwort = self.client_fuer(self.admin).get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(antwort, "Bei einer Leihe werden keine Zugänge ausgegeben.")
        self.assertContains(antwort, protokoll.leihe.nr)
        self.assertNotContains(antwort, 'data-test="checkliste-formular"')


class AnfrageTests(VerleihTestCase):
    """F-31: Kategorie, Zeitraum, Zweck; Anzeige der freien Geräte."""

    VON = HEUTE + timedelta(days=30)
    BIS = HEUTE + timedelta(days=40)

    def _frei(self, kategorie=None, von=VON, bis=BIS):
        return self.client_fuer(self.anna_konto).get(
            "/meine-geraete/leihe/frei/",
            {
                "kat": (kategorie or self.smartphone).pk,
                "beginn": von.isoformat(),
                "ende": bis.isoformat(),
            },
        ).json()

    def test_zaehlt_nur_was_im_zeitraum_frei_ist(self):
        self.assertEqual(self._frei()["frei"], 3)
        self.assertEqual(self._frei()["gesamt"], 3)
        # Eine genehmigte Leihe im Zeitraum, ein Gerät in Reparatur, eines ausgemustert.
        self.genehmigt(self.VON, self.BIS, self.a, person=self.felix)
        d = self._pool("SN-D")
        services.gerat_in_reparatur_geschickt(d, dienstleister="X", vorgangsnummer="1", notiz="", ausgefuehrt_von=self.admin)
        e = self._pool("SN-E")
        services.ausmustern(e, grund="verloren", datum=HEUTE, disposition="unbekannt", bestaetigt_gemeldt=True, ausgefuehrt_von=self.admin)
        stand = self._frei()
        self.assertEqual(stand["frei"], 2)
        self.assertEqual(stand["gesamt"], 4)
        self.assertIn("2 von 4", stand["text"])
        self.assertEqual(
            {g["id"] for g in stand["geraete"]}, {self.b.pk, self.c.pk}
        )

    def test_verliehenes_geraet_zaehlt_nur_ohne_ueberschneidung(self):
        self.ausgegeben(HEUTE + timedelta(days=35))
        self.assertEqual(self._frei()["frei"], 2)
        spaeter = self._frei(von=HEUTE + timedelta(days=36), bis=HEUTE + timedelta(days=40))
        self.assertEqual(spaeter["frei"], 3)

    def test_ueberfaellige_leihe_belegt_das_geraet_bis_heute(self):
        self.ausgegeben(HEUTE + timedelta(days=2))
        self.stellen(HEUTE + timedelta(days=20))
        stand = self._frei(von=HEUTE + timedelta(days=20), bis=HEUTE + timedelta(days=21))
        self.assertEqual(stand["frei"], 2)

    def test_keins_frei_sagt_die_seite_und_nennt_nur_die_kategorie(self):
        for g in (self.a, self.b, self.c):
            self.genehmigt(self.VON, self.BIS, g, person=self.felix)
        stand = self._frei()
        self.assertEqual(stand["frei"], 0)
        self.assertIn("kein Leihgerät der Kategorie Smartphone frei", stand["text"])
        self.assertEqual(stand["art"], "warning")

    def test_fehler_stehen_auf_der_seite_und_eingaben_bleiben(self):
        c = self.client_fuer(self.anna_konto)
        antwort = c.post("/meine-geraete/leihe/neu/", {
            "kat": self.smartphone.pk,
            "beginn": self.BIS.isoformat(),
            "ende": self.VON.isoformat(),
            "zweck": "Messe",
        })
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertContains(antwort, "Das Enddatum muss am oder nach dem Startdatum liegen.")
        self.assertContains(antwort, f'value="{self.BIS.isoformat()}"')
        self.assertContains(antwort, f'<option value="{self.smartphone.pk}" selected>')
        self.assertFalse(Leihe.objects.exists())

    def test_reserviertes_geraet_meldet_die_seite(self):
        self.genehmigt(self.VON, self.BIS, self.a, person=self.felix)
        antwort = self.client_fuer(self.anna_konto).post("/meine-geraete/leihe/neu/", {
            "kat": self.smartphone.pk,
            "beginn": self.VON.isoformat(),
            "ende": self.BIS.isoformat(),
            "zweck": "Messe",
            "gerat": self.a.pk,
        })
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertContains(antwort, "bereits für eine Leihe reserviert")

    def test_vergangener_beginn_abgelehnt(self):
        antwort = self.client_fuer(self.anna_konto).post("/meine-geraete/leihe/neu/", {
            "kat": self.smartphone.pk,
            "beginn": (HEUTE - timedelta(days=1)).isoformat(),
            "ende": self.BIS.isoformat(),
            "zweck": "Messe",
        })
        self.assertContains(antwort, "Das Startdatum darf nicht in der Vergangenheit liegen.")

    def test_auswahl_nur_kategorie_und_lesbar(self):
        n = self._pool("SN-N", kategorie=self.notebook)
        services.ausmustern(self.b, grund="verloren", datum=HEUTE, disposition="unbekannt", bestaetigt_gemeldt=True, ausgefuehrt_von=self.admin)
        stand = self._frei()
        texte = [g["text"] for g in stand["geraete"]]
        self.assertIn(f"{self.a.inventarnummer}, Samsung Galaxy", texte)
        self.assertNotIn(self.b.pk, [g["id"] for g in stand["geraete"]])
        self.assertNotIn(n.pk, [g["id"] for g in stand["geraete"]])

    def test_kategorien_nur_aus_dem_leihpool(self):
        antwort = self.client_fuer(self.anna_konto).get("/meine-geraete/leihe/neu/")
        self.assertContains(antwort, "Smartphone")
        self.assertNotContains(antwort, ">Tastatur<")

    def test_anfrage_reserviert_noch_nichts_und_mail_an_die_it_aus_den_einstellungen(self):
        einstellungen = Einstellungen.aktuelles()
        einstellungen.email_it = "ausleihe@beispiel.test"
        einstellungen.save()
        leihe = self.anfragen(self.VON, self.BIS, gerat=self.a)
        self.a.refresh_from_db()
        self.assertFalse(self.a.reserviert)
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)
        self.assertEqual(mail.outbox[-1].to, ["ausleihe@beispiel.test"])
        self.assertIn("/verleih/", mail.outbox[-1].body)

    def test_schalter_der_einstellungsseite_gilt_fuer_die_anfragemail(self):
        einstellungen = Einstellungen.aktuelles()
        einstellungen.mail_verleih_anfrage = False
        einstellungen.save()
        self.anfragen(self.VON, self.BIS)
        self.assertEqual(mail.outbox, [])

    def test_leser_mit_eigener_person_fragt_an(self):
        """Testschnittstelle 3, Erwin 30.10.: Leihanfrage mit eigener Person."""
        c = self.client_fuer(self.leser)
        antwort = c.get("/meine-geraete/leihe/neu/")
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="anfragen"')
        vorher = Leihe.objects.count()
        antwort = c.post("/meine-geraete/leihe/neu/", {
            "kat": self.smartphone.pk,
            "beginn": self.VON.isoformat(),
            "ende": self.BIS.isoformat(),
            "zweck": "Messe",
        })
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(Leihe.objects.count(), vorher + 1)
        self.assertEqual(Leihe.objects.order_by("-id").first().person_id, self.leser.person_id)


class EntscheidungTests(VerleihTestCase):
    """F-32, F-93: Genehmigen mit Gerät, Ablehnen mit Pflichtbegründung, Mail."""

    VON = HEUTE + timedelta(days=30)
    BIS = HEUTE + timedelta(days=40)

    def test_ablehnen_ueber_die_seite(self):
        leihe = self.anfragen(self.VON, self.BIS)
        mail.outbox.clear()
        c = self.client_fuer(self.admin)
        seite = c.get(f"/geraete/verleih/{leihe.id}/ablehnen/")
        self.assertContains(seite, 'name="begruendung"')
        antwort = c.post(f"/geraete/verleih/{leihe.id}/ablehnen/", {"begruendung": "Kein Bedarf"})
        self.assertEqual(antwort.status_code, 302)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ABGELEHNT)
        self.assertEqual(leihe.abgelehnt_bis, "Kein Bedarf")
        self.assertEqual(mail.outbox[-1].to, [self.anna.email])
        self.assertIn("Kein Bedarf", mail.outbox[-1].body)
        self.assertIn("/meine-geraete/", mail.outbox[-1].body)
        self.assertNotIn("/verleih/", mail.outbox[-1].body)
        # Der Mitarbeiter sieht die Begründung.
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/")
        self.assertContains(seite, "Begründung: Kein Bedarf")

    def test_ablehnen_ohne_begruendung(self):
        leihe = self.anfragen(self.VON, self.BIS)
        antwort = self.client_fuer(self.admin).post(f"/geraete/verleih/{leihe.id}/ablehnen/", {"begruendung": "  "})
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="fehler"')
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)

    def test_genehmigen_mail_mit_eigenem_link(self):
        leihe = self.anfragen(self.VON, self.BIS)
        mail.outbox.clear()
        self.client_fuer(self.admin).post(f"/geraete/verleih/{leihe.id}/genehmigen/", {"gerat": self.a.pk})
        leihe.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_GENEHMIGT)
        self.assertTrue(self.a.reserviert)
        self.assertEqual(mail.outbox[-1].to, [self.anna.email])
        self.assertIn("/meine-geraete/", mail.outbox[-1].body)
        self.assertNotIn("/verleih/", mail.outbox[-1].body)

    def test_ausgemustert_und_reparatur_nicht_waehl_und_nicht_genehmigbar(self):
        services.ausmustern(self.b, grund="verloren", datum=HEUTE, disposition="unbekannt", bestaetigt_gemeldt=True, ausgefuehrt_von=self.admin)
        services.gerat_in_reparatur_geschickt(self.c, dienstleister="X", vorgangsnummer="1", notiz="", ausgefuehrt_von=self.admin)
        leihe = self.anfragen(self.VON, self.BIS)
        c = self.client_fuer(self.admin)
        seite = c.get(f"/geraete/verleih/{leihe.id}/genehmigen/").content.decode()
        self.assertIn(self.a.inventarnummer, seite)
        self.assertNotIn(self.b.inventarnummer, seite)
        self.assertNotIn(self.c.inventarnummer, seite)
        for gerat in (self.b, self.c):
            antwort = c.post(f"/geraete/verleih/{leihe.id}/genehmigen/", {"gerat": gerat.pk})
            self.assertEqual(antwort.status_code, 200)
            self.assertContains(antwort, 'data-test="fehler"')
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)

    def test_kein_mail_an_deaktiviertes_konto(self):
        leihe = self.anfragen(self.VON, self.BIS)
        Konto.objects.filter(pk=self.anna_konto.pk).update(aktiv=False)
        mail.outbox.clear()
        services.leihe_genehmigen(leihe, gerat=self.a, ausgefuehrt_von=self.admin)
        self.assertEqual(mail.outbox, [])


class AusgabeAusLeiheTests(VerleihTestCase):
    """F-33: Aus der genehmigten Leihe, Zeitpunkt wie in F-21."""

    def setUp(self):
        super().setUp()
        self.leihe = self.genehmigt(HEUTE + timedelta(days=1), HEUTE + timedelta(days=10), self.a)

    def test_signatur_im_tool_wird_beachtet(self):
        c = self.client_fuer(self.admin)
        self.assertContains(c.get(f"/geraete/verleih/{self.leihe.id}/ausgeben/"), 'value="tool"')
        antwort = c.post(f"/geraete/verleih/{self.leihe.id}/ausgeben/", {"unterschrift": "tool"})
        self.assertEqual(antwort.status_code, 302)
        self.a.refresh_from_db()
        self.leihe.refresh_from_db()
        protokoll = self.leihe.protokolle.get()
        self.assertEqual(self.a.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(self.leihe.status, Leihe.STATUS_GENEHMIGT)
        self.assertEqual(protokoll.stand, Protokoll.STAND_BEARBEITER_OFFEN)
        # Zweite Ausgabe gibt es nicht, solange das Protokoll offen ist.
        antwort = c.post(f"/geraete/verleih/{self.leihe.id}/ausgeben/", {"unterschrift": "papier"})
        self.assertContains(antwort, "offenes Protokoll")
        # Mit der Signatur wird das Gerät verliehen.
        c.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PASSWORT})
        self.a.refresh_from_db()
        self.leihe.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(self.leihe.status, Leihe.STATUS_AUSGEGEBEN)
        self.assertEqual(self.a.vorgaenge.filter(typ=Vorgang.TYP_AUSGABE).count(), 1)

    def test_papier_sofort_mit_bezug_zur_leihe(self):
        self.client_fuer(self.admin).post(f"/geraete/verleih/{self.leihe.id}/ausgeben/", {"unterschrift": "papier"})
        self.a.refresh_from_db()
        self.leihe.refresh_from_db()
        protokoll = self.leihe.protokolle.get()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(protokoll.stand, Protokoll.STAND_SCAN_OFFEN)
        self.assertEqual(protokoll.bearbeiter, self.admin.bezeichnung())

    def test_verworfener_entwurf_laesst_die_genehmigung_stehen(self):
        c = self.client_fuer(self.admin)
        c.post(f"/geraete/verleih/{self.leihe.id}/ausgeben/", {"unterschrift": "tool"})
        protokoll = self.leihe.protokolle.get()
        c.post(f"/protokolle/{protokoll.nr}/abbrechen/")
        self.leihe.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(self.leihe.status, Leihe.STATUS_GENEHMIGT)
        self.assertTrue(self.a.reserviert)

    def test_spaetere_reservierung_stoert_die_ausgabe_nicht(self):
        spaeter = self.genehmigt(HEUTE + timedelta(days=20), HEUTE + timedelta(days=25), self.a, person=self.felix)
        services.leihe_ausgeben(self.leihe, ausgefuehrt_von=self.admin)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_VERLIEHEN)
        # Die andere Reservierung bleibt.
        self.assertTrue(self.a.reserviert)
        self.assertEqual(self.a.reserviert_bis, spaeter.ende)

    def test_frist_vorbei_keine_ausgabe(self):
        self.stellen(HEUTE + timedelta(days=11))
        with self.assertRaises(services.GeratFehler):
            services.leihe_ausgeben(self.leihe, ausgefuehrt_von=self.admin)


class DoppelbuchungTests(VerleihTestCase):
    """F-34: Auch eine ausgegebene Leihe und der Direktverleih belegen das Gerät."""

    def _genehmigen(self, von, bis):
        leihe = self.anfragen(von, bis, person=self.felix)
        services.leihe_genehmigen(leihe, gerat=self.a, ausgefuehrt_von=self.admin)
        return leihe

    def test_gegen_ausgegebene_leihe(self):
        von, bis = HEUTE + timedelta(days=60), HEUTE + timedelta(days=80)
        leihe = self.genehmigt(von, bis, self.a)
        services.leihe_ausgeben(leihe, ausgefuehrt_von=self.admin)
        for a, b in (
            (von + timedelta(days=9), von + timedelta(days=14)),
            (von - timedelta(days=5), von),
            (bis, bis + timedelta(days=5)),
            (von - timedelta(days=5), bis + timedelta(days=5)),
        ):
            with self.subTest(von=a, bis=b), self.assertRaises(services.GeratFehler):
                self._genehmigen(a, b)
        self.assertEqual(self._genehmigen(bis + timedelta(days=1), bis + timedelta(days=5)).status, Leihe.STATUS_GENEHMIGT)
        self.assertEqual(self._genehmigen(von - timedelta(days=5), von - timedelta(days=1)).status, Leihe.STATUS_GENEHMIGT)

    def test_gegen_direktverleih(self):
        self.ausgegeben(HEUTE + timedelta(days=30))
        with self.assertRaises(services.GeratFehler):
            self._genehmigen(HEUTE + timedelta(days=20), HEUTE + timedelta(days=25))
        leihe = self._genehmigen(HEUTE + timedelta(days=31), HEUTE + timedelta(days=35))
        self.assertEqual(leihe.status, Leihe.STATUS_GENEHMIGT)

    def test_gegen_genehmigte_leihe_mit_meldung_auf_der_seite(self):
        self.genehmigt(HEUTE + timedelta(days=30), HEUTE + timedelta(days=40), self.a)
        leihe = self.anfragen(HEUTE + timedelta(days=35), HEUTE + timedelta(days=45), person=self.felix)
        c = self.client_fuer(self.admin)
        seite = c.get(f"/geraete/verleih/{leihe.id}/genehmigen/")
        self.assertContains(seite, "(im Zeitraum belegt)")
        antwort = c.post(f"/geraete/verleih/{leihe.id}/genehmigen/", {"gerat": self.a.pk})
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertContains(antwort, "bereits für eine Leihe reserviert")


class VerlaengerungTests(VerleihTestCase):
    """F-35, F-111: Mitarbeiter fragt an, Admin gewährt ohne Folgereservierung."""

    def setUp(self):
        super().setUp()
        self.bis = HEUTE + timedelta(days=10)
        self.leihe = self.ausgegeben(self.bis)
        mail.outbox.clear()

    def _anfragen(self, konto, bis=None):
        return self.client_fuer(konto).post(
            f"/meine-geraete/leihe/{self.leihe.id}/verlaengern/",
            {"rueckgabe_bis_neu": (bis or self.bis + timedelta(days=7)).isoformat()},
        )

    def test_mitarbeiter_fragt_an_admin_gewaehrt(self):
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/")
        self.assertContains(seite, "Verlängerung anfragen")
        self.assertContains(seite, f'value="{(self.bis + timedelta(days=7)).isoformat()}"')

        self.assertEqual(self._anfragen(self.anna_konto).status_code, 302)
        self.leihe.refresh_from_db()
        gewuenscht = self.bis + timedelta(days=7)
        self.assertEqual(self.leihe.verlaengerung_bis, gewuenscht)
        self.assertEqual(self.leihe.rueckgabe_bis, self.bis)
        self.assertIn("/verleih/", mail.outbox[-1].body)
        self.assertEqual(mail.outbox[-1].to, [Einstellungen.aktuelles().email_it])
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/")
        self.assertContains(seite, f"Verlängerung bis {gewuenscht:%d.%m.%Y} angefragt")
        self.assertNotContains(seite, 'data-test="verlaengerung-anfragen"')
        # Die IT sieht den Wunsch und bekommt ihn vorbelegt.
        c = self.client_fuer(self.admin)
        self.assertContains(c.get("/verleih/"), f"Verlängerung bis {gewuenscht:%d.%m.%Y} angefragt")
        self.assertContains(c.get(f"/geraete/verleih/{self.leihe.id}/verlaengern/"), f'value="{gewuenscht.isoformat()}"')

        mail.outbox.clear()
        antwort = c.post(
            f"/geraete/verleih/{self.leihe.id}/verlaengern/",
            {"rueckgabe_bis_neu": gewuenscht.isoformat()},
        )
        self.assertEqual(antwort.status_code, 302)
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.rueckgabe_bis, gewuenscht)
        self.assertIsNone(self.leihe.verlaengerung_bis)
        self.assertEqual(mail.outbox[-1].to, [self.anna.email])
        self.assertIn(f"{gewuenscht:%d.%m.%Y}", mail.outbox[-1].body)
        self.assertIn("/meine-geraete/", mail.outbox[-1].body)

    def test_folgereservierung_auch_mitten_im_zeitraum(self):
        von = self.bis + timedelta(days=5)
        self.genehmigt(von, von + timedelta(days=5), self.a, person=self.felix)
        # Zieldatum hinter der Reservierung: früher wurde nur dieser eine Tag geprüft.
        antwort = self.client_fuer(self.admin).post(
            f"/geraete/verleih/{self.leihe.id}/verlaengern/",
            {"rueckgabe_bis_neu": (von + timedelta(days=20)).isoformat()},
        )
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertContains(antwort, f"Ab {von:%d.%m.%Y}")
        self.leihe.refresh_from_db()
        self.assertEqual(self.leihe.rueckgabe_bis, self.bis)
        # Bis zum Tag davor geht es.
        leihe = services.leihe_verlaengern(self.leihe, von - timedelta(days=1), self.admin)
        self.assertEqual(leihe.rueckgabe_bis, von - timedelta(days=1))

    def test_rechte(self):
        self.assertEqual(self._anfragen(self.felix_konto).status_code, 403)
        self.assertEqual(self._anfragen(self.leser).status_code, 403)
        self.assertEqual(self.client_fuer(self.anna_konto).get(f"/meine-geraete/leihe/{self.leihe.id}/verlaengern/").status_code, 405)
        self.assertEqual(self.client_fuer(self.anna_konto).post("/meine-geraete/leihe/99999/verlaengern/", {}).status_code, 404)
        self.assertEqual(self.client_fuer(self.anna_konto).get(f"/geraete/verleih/{self.leihe.id}/verlaengern/").status_code, 403)
        self.leihe.refresh_from_db()
        self.assertIsNone(self.leihe.verlaengerung_bis)

    def test_ungueltiges_datum_meldet_die_seite(self):
        antwort = self.client_fuer(self.anna_konto).post(
            f"/meine-geraete/leihe/{self.leihe.id}/verlaengern/",
            {"rueckgabe_bis_neu": self.bis.isoformat()},
            follow=True,
        )
        self.assertContains(antwort, 'data-test="fehler"')
        self.leihe.refresh_from_db()
        self.assertIsNone(self.leihe.verlaengerung_bis)

    def test_ueberfaellig_nur_nach_heute(self):
        self.stellen(self.bis + timedelta(days=20))
        with self.assertRaises(services.GeratFehler):
            services.leihe_verlaengern(self.leihe, self.bis + timedelta(days=5), self.admin)
        leihe = services.leihe_verlaengern(self.leihe, self.bis + timedelta(days=25), self.admin)
        self.assertFalse(leihe.ist_ueberfaellig)


class UeberfaelligTests(VerleihTestCase):
    """F-36: Liste mit Symbol und Text, nach der Uhr der Anwendung."""

    def setUp(self):
        super().setUp()
        self.bis = HEUTE + timedelta(days=5)
        self.leihe = self.ausgegeben(self.bis)

    def test_liste_und_export(self):
        c = self.client_fuer(self.admin)
        self.assertContains(c.get("/verleih/"), f'data-id="{self.leihe.nr}" data-stand="ausgegeben"')
        self.stellen(self.bis + timedelta(days=1))
        # Die Uhr springt um Tage, die Sitzung ist damit vorbei (F-05, Testschnittstelle 1.2).
        c = self.client_fuer(self.admin)
        seite = c.get("/verleih/")
        self.assertContains(seite, f'data-id="{self.leihe.nr}" data-stand="ueberfaellig"')
        self.assertContains(seite, 'data-test="symbol-ueberfaellig"')
        self.assertContains(seite, "überfällig</span>")
        self.assertContains(c.get("/verleih/?format=csv"), "überfällig")

    def test_grenztag_noch_nicht_ueberfaellig(self):
        self.stellen(self.bis)
        self.assertFalse(services.leihen_ueberfaellig())
        self.stellen(self.bis + timedelta(days=1))
        self.assertEqual(len(services.leihen_ueberfaellig()), 1)

    def test_meine_leihen(self):
        self.stellen(self.bis + timedelta(days=1))
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/")
        self.assertContains(seite, f'data-id="{self.leihe.nr}" data-stand="ueberfaellig"')
        self.assertContains(seite, 'data-test="symbol-ueberfaellig"')

    def test_entwurf_ist_nicht_ueberfaellig(self):
        leihe = services.leih_gerat_ausgeben(
            gerat=self.b, person=self.anna, rueckgabe_bis=self.bis, zweck="x",
            ausgefuehrt_von=self.admin, unterschrift="tool",
        )
        self.stellen(self.bis + timedelta(days=1))
        self.assertNotIn(leihe.pk, [l.pk for l in services.leihen_ueberfaellig()])


class ZurueckziehenTests(VerleihTestCase):
    """F-37: Weg in der Oberfläche, solange die Leihe nicht ausgegeben ist."""

    VON = HEUTE + timedelta(days=30)
    BIS = HEUTE + timedelta(days=40)

    def test_knopf_und_wirkung(self):
        leihe = self.genehmigt(self.VON, self.BIS, self.a)
        c = self.client_fuer(self.anna_konto)
        self.assertContains(c.get("/meine-geraete/"), f'/meine-geraete/leihe/{leihe.id}/zurueckziehen/')
        antwort = c.post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {})
        self.assertEqual(antwort.status_code, 302)
        leihe.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)
        self.assertFalse(self.a.reserviert)
        # Danach wieder frei.
        self.assertTrue(services.leihe_verfuegbarkeit(self.smartphone, self.VON, self.BIS)["frei"])

    def test_reservierung_einer_anderen_leihe_bleibt(self):
        leihe = self.genehmigt(self.VON, self.BIS, self.a)
        andere = self.genehmigt(self.BIS + timedelta(days=1), self.BIS + timedelta(days=2), self.a, person=self.felix)
        services.leihe_zurueckziehen(andere, ausgefuehrt_von=self.felix_konto)
        self.a.refresh_from_db()
        self.assertTrue(self.a.reserviert)
        self.assertEqual(self.a.reserviert_bis, leihe.ende)

    def test_ausgegeben_kein_knopf_und_abgewiesen(self):
        leihe = self.ausgegeben(self.BIS)
        c = self.client_fuer(self.anna_konto)
        self.assertNotContains(c.get("/meine-geraete/"), "zurueckziehen/")
        antwort = c.post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {})
        self.assertContains(antwort, 'data-test="fehler"')
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)

    def test_rechte(self):
        leihe = self.anfragen(self.VON, self.BIS)
        self.assertEqual(self.client_fuer(self.felix_konto).post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {}).status_code, 403)
        self.assertEqual(self.client_fuer(self.leser).post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {}).status_code, 403)
        self.assertEqual(self.client_fuer(self.admin).post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {}).status_code, 403)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ANGEFRAGT)

    def test_admin_zieht_die_eigene_anfrage_zurueck(self):
        leihe = self.anfragen(self.VON, self.BIS, person=self.admin.person)
        antwort = self.client_fuer(self.admin).post(f"/meine-geraete/leihe/{leihe.id}/zurueckziehen/", {})
        self.assertEqual(antwort.status_code, 302)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEZOGEN)


class RueckgabeUeberDasGeraetTests(VerleihTestCase):
    """F-92, F-111: Die Rückgabe am Gerät schließt die Leihe ab."""

    def setUp(self):
        super().setUp()
        self.bis = HEUTE + timedelta(days=5)
        self.leihe = self.ausgegeben(self.bis)

    def _rueckgabe(self):
        return self.client_fuer(self.admin).post(
            f"/geraete/{self.a.inventarnummer}/rueckgeben/",
            {"zustand_rueckgabe": Gerat.ZUSTAND_GUT, "zubehoer_komplett": "ja", "ziel": "lager"},
        )

    def test_rueckgabe_schliesst_die_leihe_und_die_erinnerung_endet(self):
        self.stellen(self.bis + timedelta(days=3))
        self.assertEqual(self._rueckgabe().status_code, 302)
        self.a.refresh_from_db()
        self.leihe.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(self.leihe.status, Leihe.STATUS_ZURUECKGEGEBEN)
        self.assertEqual(self.leihe.stand_wert, "zurueckgegeben")
        self.assertEqual(services.leihen_ueberfaellig(), [])
        mail.outbox.clear()
        for tage in range(4, 8):
            call_command("tageslauf", "--stichtag", (self.bis + timedelta(days=tage)).isoformat(), stdout=open("/dev/null", "w"))
        self.assertEqual([m.subject for m in mail.outbox if "überfällig" in m.subject], [])

    def test_ohne_rueckgabe_jeden_tag_eine_mail(self):
        mail.outbox.clear()
        for tage in (1, 2):
            call_command("tageslauf", "--stichtag", (self.bis + timedelta(days=tage)).isoformat(), stdout=open("/dev/null", "w"))
            call_command("tageslauf", "--stichtag", (self.bis + timedelta(days=tage)).isoformat(), stdout=open("/dev/null", "w"))
        ueberfaellig = [m for m in mail.outbox if "überfällig" in m.subject]
        self.assertEqual(len(ueberfaellig), 2)
        self.assertIn(self.anna.email, ueberfaellig[0].to)
        self.assertIn(Einstellungen.aktuelles().email_it, ueberfaellig[0].to)
        self.assertIn("/meine-geraete/", ueberfaellig[0].body)

    def test_verlust_beendet_die_leihe(self):
        services.ausmustern(
            self.a, grund="verloren", datum=HEUTE, disposition="unbekannt",
            bestaetigt_gemeldt=True, ausgefuehrt_von=self.admin,
        )
        self.leihe.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Gerat.STATUS_AUSGEMUSTERT)
        self.assertEqual(self.leihe.status, Leihe.STATUS_VERLOREN)

    def test_ruecknahme_in_der_verleihliste(self):
        seite = self.client_fuer(self.admin).get("/verleih/")
        self.assertContains(seite, f'/geraete/{self.a.inventarnummer}/rueckgeben/')

    def test_ruecknahmeprotokoll_hat_bezug_zur_leihe(self):
        self._rueckgabe()
        protokoll = Protokoll.objects.get(geraet=self.a, art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(protokoll.leihe, self.leihe)


class ErinnerungsmailTests(VerleihTestCase):
    """F-91, F-96: Vortag, Link ins Tool, keine Mail an deaktivierte Konten."""

    def _lauf(self, tag):
        mail.outbox.clear()
        call_command("tageslauf", "--stichtag", tag.isoformat(), stdout=open("/dev/null", "w"))
        return [m for m in mail.outbox if "Leihe" in m.subject]

    def test_vortag_mit_eigenem_link(self):
        bis = HEUTE + timedelta(days=5)
        self.ausgegeben(bis)
        self.assertEqual(self._lauf(bis - timedelta(days=2)), [])
        mails = self._lauf(bis - timedelta(days=1))
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0].to, [self.anna.email])
        self.assertIn("/meine-geraete/", mails[0].body)
        self.assertNotIn("/verleih/", mails[0].body)
        self.assertEqual(self._lauf(bis), [])

    def test_deaktiviertes_konto_keine_mail_die_it_bleibt(self):
        bis = HEUTE + timedelta(days=5)
        self.ausgegeben(bis)
        Konto.objects.filter(pk=self.anna_konto.pk).update(aktiv=False)
        self.assertEqual(self._lauf(bis - timedelta(days=1)), [])
        mails = self._lauf(bis + timedelta(days=1))
        self.assertEqual(mails[0].to, [Einstellungen.aktuelles().email_it])

    def test_entwurf_bekommt_keine_erinnerung(self):
        bis = HEUTE + timedelta(days=5)
        services.leih_gerat_ausgeben(
            gerat=self.a, person=self.anna, rueckgabe_bis=bis, zweck="x",
            ausgefuehrt_von=self.admin, unterschrift="tool",
        )
        self.assertEqual(self._lauf(bis - timedelta(days=1)), [])
        self.assertEqual(self._lauf(bis + timedelta(days=1)), [])


class MeineGeraeteTests(VerleihTestCase):
    """F-110, F-111: Datum TT.MM.JJJJ, PDF-Link führt zu einem Dokument, Leihnummer."""

    def test_datum_und_leihe_bis(self):
        leihe = self.ausgegeben(HEUTE + timedelta(days=5))
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/").content.decode()
        ausgabe = leihe.gerat.vorgaenge.get(typ=Vorgang.TYP_AUSGABE).zeitpunkt
        self.assertIn(f"Ausgabe: {ausgabe:%d.%m.%Y}", seite)
        self.assertIn(f"Leihe bis {leihe.rueckgabe_bis:%d.%m.%Y}", seite)

    def test_data_id_ist_die_leihnummer(self):
        leihe = self.anfragen(HEUTE + timedelta(days=5), HEUTE + timedelta(days=6))
        seite = self.client_fuer(self.anna_konto).get("/meine-geraete/")
        self.assertContains(seite, f'data-test="zeile" data-id="{leihe.nr}" data-stand="angefragt"')
        seite = self.client_fuer(self.admin).get("/verleih/")
        self.assertContains(seite, f'data-test="zeile" data-id="{leihe.nr}" data-stand="angefragt"')

    def test_leihprotokoll_pdf_ohne_checkliste(self):
        leihe = self.ausgegeben(HEUTE + timedelta(days=5))
        protokoll = leihe.protokolle.get()
        c = self.client_fuer(self.anna_konto)
        self.assertContains(c.get("/meine-geraete/"), f"/protokolle/{protokoll.nr}/pdf/")
        antwort = c.get(f"/protokolle/{protokoll.nr}/pdf/")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")

    def test_papierausgabe_ohne_checkliste_kein_toter_link(self):
        services.gerat_ausgeben(self.b, self.anna, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(geraet=self.b)
        c = self.client_fuer(self.anna_konto)
        seite = c.get("/meine-geraete/")
        self.assertNotContains(seite, f"/protokolle/{protokoll.nr}/pdf/")
        self.assertContains(seite, "Protokoll noch offen")

    def test_papierausgabe_mit_scan_liefert_den_scan(self):
        services.gerat_ausgeben(self.b, self.anna, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(geraet=self.b)
        from geraete.protokoll import scan_hochladen
        scan = ContentFile(b"%PDF-1.4 unterschrieben", name="scan.pdf")
        scan_hochladen(protokoll, scan, self.admin)
        self.addCleanup(protokoll.scan_datei.delete, save=False)
        c = self.client_fuer(self.anna_konto)
        self.assertContains(c.get("/meine-geraete/"), f"/protokolle/{protokoll.nr}/pdf/")
        antwort = c.get(f"/protokolle/{protokoll.nr}/pdf/")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertTrue(antwort.content.startswith(b"%PDF"))

    def test_kein_fremdes_geraet_ohne_person(self):
        konto = Konto(email="ohneperson@beispiel.test", rolle=Konto.ROLLE_MITARBEITER)
        konto.set_password(PASSWORT)
        konto.save()
        seite = self.client_fuer(konto).get("/meine-geraete/")
        self.assertNotContains(seite, self.a.inventarnummer)

    def test_alte_adresse_alle_geraete_gibt_es_nicht_mehr(self):
        self.assertEqual(self.client_fuer(self.anna_konto).get("/meine-geraete/alle/").status_code, 404)
