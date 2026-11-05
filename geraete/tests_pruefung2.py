"""Befunde der zweiten Prüfung (Stand b98a05b)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test import TestCase

from konten import zeit
from konten.models import Konto
from stammdaten.models import Kategorie, Ort, Person

from . import kennzahlen, services
from .models import Gerat, Leihe, Protokoll
from .tests import konto_erstellen

PW = "test-passwort-123"
HEUTE = date(2036, 3, 2)


class Grundlage(TestCase):
    def setUp(self):
        self.kat = Kategorie.objects.create(name="Maus")
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER")
        self.anna = Person.objects.create(anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker", email="anna@beispiel.test")
        self.felix = Person.objects.create(anrede=Person.ANREDE_HERR, vorname="Felix", nachname="Hoffmann", email="felix@beispiel.test")
        self.admin = konto_erstellen("it.admin", "admin", "it-admin@beispiel.test")
        self.client.force_login(self.admin)

    def _gerat(self, sn="SN-1", **werte):
        return services.gerat_anlegen(
            kategorie=self.kat, hersteller="Logi", modell="M1", seriennummer=sn, ort=self.lager,
            erzeugt_von=self.admin, **werte,
        )

    def _entwurf(self, *geraete):
        return services.geraete_ausgeben(list(geraete), self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")

    def _checkliste(self, protokoll):
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            protokoll.checkliste[schluessel] = 0
        protokoll.save()


class EntwurfSperrtTests(Grundlage):
    """F-21, F-30: Ein offener Entwurf sperrt das Gerät, die Signatur überschreibt nichts."""

    def test_ausmustern_und_reparatur_sind_gesperrt(self):
        gerat = self._gerat()
        self._entwurf(gerat)
        gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="X", ausgefuehrt_von=self.admin)
        with self.assertRaises(services.GeratFehler):
            services.gerat_in_reparatur_geschickt(gerat, dienstleister="X", vorgangsnummer="1", notiz="n", ausgefuehrt_von=self.admin)

    def test_auch_das_zweite_geraet_eines_sammelentwurfs(self):
        a, b = self._gerat("A", leihpool=True), self._gerat("B", leihpool=True)
        self._entwurf(a, b)
        b.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.leih_gerat_ausgeben(b, self.felix, HEUTE, "Messe", self.admin)
        leihe = Leihe.objects.create(person=self.felix, kat=self.kat, beginn=HEUTE, ende=HEUTE + timedelta(days=3), rueckgabe_bis=HEUTE + timedelta(days=3), status=Leihe.STATUS_ANGEFRAGT)
        with self.assertRaises(services.GeratFehler):
            services.leihe_genehmigen(leihe, b, self.admin)

    def test_signatur_ueberschreibt_kein_anderes_schicksal(self):
        gerat = self._gerat()
        protokoll = self._entwurf(gerat)
        self._checkliste(protokoll)
        Gerat.objects.filter(pk=gerat.pk).update(status=Gerat.STATUS_AUSGEMUSTERT)
        antwort = self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW}, follow=True)
        protokoll.refresh_from_db()
        gerat.refresh_from_db()
        self.assertIsNone(protokoll.bearbeiter_signiert_am)
        self.assertEqual(gerat.status, Gerat.STATUS_AUSGEMUSTERT)
        self.assertContains(antwort, "steht nicht mehr auf Lager")

    def test_ruecknahme_sperrt_die_neue_ausgabe_nicht(self):
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=2, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        self.assertTrue(Protokoll.objects.filter(art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN).exists())
        self.assertEqual(services.ausgabe_sperrgrund(gerat), "")

    def test_meldung_sagt_nichts_von_ausgegeben(self):
        gerat = self._gerat()
        antwort = self.client.post(
            f"/geraete/{gerat.inventarnummer}/ausgeben/",
            {"ziel_person": self.anna.pk, "zustand": 2, "zubehoer_komplett": "ja", "unterschrift": "tool"},
            follow=True,
        )
        self.assertContains(antwort, "wird mit Ihrer Signatur ausgegeben")
        self.assertNotContains(antwort, "Gerät ausgegeben.")


class ReservierungTests(Grundlage):
    """F-20, Kapitel 4: Eine Reservierung gilt für ihren Zeitraum."""

    def _genehmigt(self, gerat, von, bis):
        leihe = Leihe.objects.create(person=self.anna, kat=self.kat, beginn=von, ende=bis, rueckgabe_bis=bis, status=Leihe.STATUS_ANGEFRAGT)
        return services.leihe_genehmigen(leihe, gerat, self.admin) or leihe

    def test_abgelaufene_reservierung_sperrt_nicht(self):
        gerat = self._gerat(leihpool=True)
        gestern = zeit.jetzt_wie_im_entwicklungsmodus().date() - timedelta(days=1)
        self._genehmigt(gerat, gestern - timedelta(days=3), gestern)
        gerat.refresh_from_db()
        self.assertTrue(gerat.reserviert)
        self.assertFalse(gerat.reserviert_aktiv)
        self.assertEqual(services.ausgabe_sperrgrund(gerat), "")
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-ausgabe"')

    def test_laufende_reservierung_sperrt_und_der_knopf_fehlt(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        self._genehmigt(gerat, heute, heute + timedelta(days=5))
        gerat.refresh_from_db()
        self.assertIn("reserviert", services.ausgabe_sperrgrund(gerat))
        self.assertNotContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-ausgabe"')

    def test_direktverleih_vor_einer_spaeteren_reservierung(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        self._genehmigt(gerat, heute + timedelta(days=20), heute + timedelta(days=25))
        gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.leih_gerat_ausgeben(gerat, self.felix, heute + timedelta(days=21), "zu lang", self.admin)
        leihe = services.leih_gerat_ausgeben(gerat, self.felix, heute + timedelta(days=5), "kurz", self.admin)
        self.assertEqual(leihe.status, Leihe.STATUS_AUSGEGEBEN)

    def test_die_it_kann_eine_genehmigte_leihe_beenden(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = self._genehmigt(gerat, heute, heute + timedelta(days=5))
        services.leihe_ablehnen(leihe, "Gerät wird gebraucht", self.admin)
        gerat.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ABGELEHNT)
        self.assertEqual(services.ausgabe_sperrgrund(gerat), "")


class VerleihAngabenTests(Grundlage):
    """F-30: Protokoll wie bei F-21, auch beim Verleih."""

    def test_direktverleih_traegt_zustand_zubehoer_bemerkung(self):
        gerat = self._gerat(leihpool=True)
        bis = zeit.jetzt_wie_im_entwicklungsmodus().date() + timedelta(days=5)
        self.client.post(f"/geraete/{gerat.inventarnummer}/verleih/", {
            "person": self.anna.pk, "rueckgabe_bis": bis.isoformat(), "zweck": "Messe", "unterschrift": "papier",
            "zustand": 3, "zubehoer_komplett": "nein", "anmerkung": "Kratzer",
        })
        protokoll = Protokoll.objects.get(leihe__isnull=False)
        position = protokoll.positionen[0]
        self.assertEqual(position["zustand_ausgabe"], 3)
        self.assertIs(position["zubehoer_komplett"], False)
        self.assertEqual(position["bemerkung"], "Kratzer")
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_VERLIEHEN)
        self.assertEqual(gerat.zustand, 3)

    def test_dialog_hat_die_felder(self):
        gerat = self._gerat(leihpool=True)
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/verleih/")
        for marke in ("ausgabe-zustand", "zubehoer-komplett", "anmerkung", "foto-datei"):
            self.assertContains(antwort, f'data-test="{marke}"')


class VerlaengerungTests(Grundlage):
    """F-35: Was nicht gewährt werden kann, lässt sich ablehnen."""

    def test_ablehnen_raeumt_die_anfrage_weg_und_sagt_es_der_person(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = services.leih_gerat_ausgeben(gerat, self.anna, heute + timedelta(days=5), "Messe", self.admin)
        Leihe.objects.filter(pk=leihe.pk).update(verlaengerung_bis=heute + timedelta(days=9))
        mail.outbox.clear()
        seite = self.client.get(f"/geraete/verleih/{leihe.pk}/verlaengern/")
        self.assertContains(seite, 'data-test="verlaengerung-ablehnen"')
        self.client.post(f"/geraete/verleih/{leihe.pk}/verlaengern/", {"aktion": "ablehnen"})
        leihe.refresh_from_db()
        self.assertIsNone(leihe.verlaengerung_bis)
        self.assertEqual(mail.outbox[-1].to, [self.anna.email])
        self.assertIn("abgelehnt", mail.outbox[-1].subject)


class UebersichtTests(Grundlage):
    """F-36, F-133."""

    def test_ueberfaellig_mit_symbol_und_text(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = services.leih_gerat_ausgeben(gerat, self.anna, heute + timedelta(days=5), "Messe", self.admin)
        Leihe.objects.filter(pk=leihe.pk).update(rueckgabe_bis=heute - timedelta(days=2))
        antwort = self.client.get("/")
        self.assertContains(antwort, 'data-test="markierung-ueberfaellig"')
        self.assertContains(antwort, "überfällig</span>")

    def test_in_klaerung_nur_bei_ruecknahmen_und_mit_namen(self):
        gerat = self._gerat()
        self._entwurf(gerat)
        self.assertEqual(kennzahlen.offene_punkte_in_klaerung(), [])
        zweites = self._gerat("B")
        services.gerat_ausgeben(zweites, self.anna, ausgefuehrt_von=self.admin)
        zweites.refresh_from_db()
        services.gerat_rueckgeben(zweites, zustand_rueckgabe=2, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(kennzahlen.offene_punkte_in_klaerung(), [])
        protokoll.offboarding["ssh_api"] = {"status": "in_klaerung", "datum": "", "kuerzel": "", "bemerkung": ""}
        protokoll.save()
        zeile = kennzahlen.offene_punkte_in_klaerung()[0]
        self.assertEqual(zeile["punkte"], ["SSH-Schlüssel und API-Token widerrufen"])
        self.assertContains(self.client.get("/"), "In Klärung: SSH-Schlüssel")


class AnmeldungTests(TestCase):
    """F-01, F-04, F-05."""

    def setUp(self):
        self.konto = konto_erstellen("anna.k", "admin", "anna.k@beispiel.test")

    def _anmelden(self, email, passwort):
        return self.client.post("/anmelden/", {"email": email, "passwort": passwort})

    def test_meldung_ist_immer_dieselbe(self):
        vorhanden = self._anmelden(self.konto.email, "falsch").content.decode()
        unbekannt = self._anmelden("niemand@beispiel.test", "falsch").content.decode()
        Konto.objects.filter(pk=self.konto.pk).update(aktiv=False)
        deaktiviert = self._anmelden(self.konto.email, "falsch").content.decode()
        from konten.views import NEUTRAL
        for seite in (vorhanden, unbekannt, deaktiviert):
            self.assertIn(NEUTRAL, seite.replace("&amp;", "&"))

    def test_leeres_formular_bekommt_eine_meldung(self):
        from konten.views import NEUTRAL
        self.assertContains(self.client.post("/anmelden/", {}), NEUTRAL)

    def test_kurzes_passwort_ergibt_eine_meldung(self):
        self.client.force_login(self.konto)
        antwort = self.client.post("/konto/passwort/", {
            "altes_passwort": PW, "neues_passwort": "kurz", "neues_passwort_wiederholung": "kurz",
        })
        self.assertEqual(antwort.content.decode().count("mindestens 12 Zeichen lang"), 1)

    def test_sitzung_endet_nach_acht_stunden_der_anwendungsuhr(self):
        self.client.force_login(self.konto)
        self.assertEqual(self.client.get("/geraete/").status_code, 200)
        spaeter = zeit.jetzt_aware() + timedelta(hours=8, minutes=1)
        with mock.patch("inventar.middleware.jetzt_aware", return_value=spaeter):
            self.assertEqual(self.client.get("/geraete/").status_code, 302)

    def test_aktivitaet_verlaengert_die_sitzung(self):
        self.client.force_login(self.konto)
        self.client.get("/geraete/")
        jetzt = zeit.jetzt_aware()
        for stunden in (7, 14, 21):
            with mock.patch("inventar.middleware.jetzt_aware", return_value=jetzt + timedelta(hours=stunden)):
                self.assertEqual(self.client.get("/geraete/").status_code, 200)
