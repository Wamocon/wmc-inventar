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


class RuecknahmeBleibtTests(Grundlage):
    """F-141, F-51, N-03."""

    def _ruecknahme(self, **werte):
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, ausgefuehrt_von=self.admin, **werte)
        return gerat, Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)

    def test_ruecknahme_laesst_sich_nicht_verwerfen(self):
        _gerat, protokoll = self._ruecknahme(zustand_rueckgabe=2)
        self.assertNotContains(self.client.get(f"/protokolle/{protokoll.nr}/"), 'data-test="abbrechen"')
        self.client.post(f"/protokolle/{protokoll.nr}/abbrechen/")
        self.assertTrue(Protokoll.objects.filter(pk=protokoll.pk).exists())

    def test_pdf_nennt_was_festgestellt_wurde(self):
        from . import pdf as pdf_modul
        import io
        import pypdfium2 as pdfium
        gerat = self._gerat("SCHLECHT")
        services.gerat_ausgeben(gerat, self.anna, zustand=1, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=4, zubesehoer_komplett=False, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        dokument = pdfium.PdfDocument(io.BytesIO(pdf_modul.pdf_bauen(protokoll)))
        text = "\n".join(s.get_textpage().get_text_bounded() for s in dokument)
        self.assertNotIn("keine Mängel", text)
        self.assertNotIn("Keine. Die Hardware", text)
        self.assertIn("Zubehör nicht komplett", text)
        self.assertIn("Zustand schlechter als bei Ausgabe", text)


class SignaturInhaltTests(Grundlage):
    """F-135, F-130."""

    def test_der_unterzeichner_steht_im_eingefrorenen_inhalt(self):
        zweiter = konto_erstellen("it.zwei", "admin", "it-zwei@beispiel.test")
        zweiter.person = Person.objects.create(vorname="Zweite", nachname="Admin", email=zweiter.email)
        zweiter.save()
        protokoll = self._entwurf(self._gerat())
        self._checkliste(protokoll)
        self.client.force_login(zweiter)
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        protokoll.refresh_from_db()
        self.assertIn("Zweite Admin", protokoll.html_eingefroren)
        self.assertNotIn(self.admin.bezeichnung(), protokoll.html_eingefroren)

    def test_texte_gelten_ab_der_anlage(self):
        from stammdaten.models import Einstellungen
        e = Einstellungen.aktuelles()
        e.nutzungsbedingungen_ausgabe = "Alter Text"
        e.nutzungsbedingungen_version = "1.0"
        e.save()
        protokoll = self._entwurf(self._gerat())
        e.nutzungsbedingungen_ausgabe = "Neuer Text"
        e.nutzungsbedingungen_version = "2.0"
        e.save()
        self._checkliste(protokoll)
        from . import pdf as pdf_modul
        html = pdf_modul._render_inhalt(Protokoll.objects.get(pk=protokoll.pk))
        self.assertIn("Alter Text", html)
        self.assertNotIn("Neuer Text", html)
        self.assertContains(self.client.get(f"/protokolle/{protokoll.nr}/"), "Textversion 1.0")

    def test_person_ohne_anrede_wird_nicht_geraten(self):
        marta = Person.objects.create(anrede="", vorname="Marta", nachname="Albrecht", email="marta@beispiel.test")
        services.gerat_ausgeben(self._gerat(), marta, ausgefuehrt_von=self.admin, unterschrift="tool")
        from . import pdf as pdf_modul
        html = pdf_modul._render_inhalt(Protokoll.objects.get(person=marta))
        self.assertIn("Guten Tag Marta Albrecht", html)
        self.assertNotIn("Sehr geehrter Herr", html)


class VersandTests(Grundlage):
    """F-139, F-96."""

    def _abgeschlossen(self, senden_scheitert=False):
        from .models import SignaturCode
        from .siegel import SIEGEL_P12, testsiegel_anlegen
        if not SIEGEL_P12.exists():
            testsiegel_anlegen()
        protokoll = self._entwurf(self._gerat())
        self._checkliste(protokoll)
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        protokoll.refresh_from_db()
        self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/code-senden/")
        code = SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).latest("id").code
        token = protokoll.gegenzeichnung_token
        if senden_scheitert:
            with mock.patch("django.core.mail.message.EmailMessage.send", side_effect=OSError("kein Server")):
                antwort = self.client.post(f"/signieren/{token}/", {"code": code})
        else:
            antwort = self.client.post(f"/signieren/{token}/", {"code": code})
        protokoll.refresh_from_db()
        return protokoll, antwort

    def test_gescheiterter_versand_bleibt_sichtbar_und_laesst_sich_wiederholen(self):
        protokoll, antwort = self._abgeschlossen(senden_scheitert=True)
        self.assertEqual(protokoll.stand, Protokoll.STAND_ABGESCHLOSSEN)
        self.assertTrue(protokoll.pdf_versand_offen)
        self.assertContains(antwort, "Die IT sendet Ihnen das versiegelte PDF zu")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(f"/protokolle/{protokoll.nr}/"), 'data-test="pdf-senden"')
        mail.outbox.clear()
        self.client.post(f"/protokolle/{protokoll.nr}/pdf-senden/")
        protokoll.refresh_from_db()
        self.assertFalse(protokoll.pdf_versand_offen)
        self.assertEqual({m.to[0] for m in mail.outbox}, {self.anna.email, self.admin.email})

    def test_fertiges_protokoll_und_code_nennen_den_link(self):
        protokoll, _antwort = self._abgeschlossen()
        code_mail = [m for m in mail.outbox if "Einmalcode:" in m.body][0]
        self.assertIn(settings.BASIS_URL, code_mail.body)
        fertig = [m for m in mail.outbox if m.attachments]
        an_anna = [m for m in fertig if m.to == [self.anna.email]][0]
        an_it = [m for m in fertig if m.to == [self.admin.email]][0]
        self.assertIn(f"{settings.BASIS_URL}/meine-geraete/", an_anna.body)
        self.assertIn(f"{settings.BASIS_URL}/protokolle/{protokoll.nr}/", an_it.body)

    def test_scan_geht_an_beide_und_traegt_den_namen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        services.gerat_ausgeben(self._gerat(), self.anna, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        mail.outbox.clear()
        self.client.post(f"/protokolle/{protokoll.nr}/scan/", {"scan": SimpleUploadedFile("x.pdf", b"%PDF-1.7\n", content_type="application/pdf")})
        self.assertEqual({m.to[0] for m in mail.outbox}, {self.anna.email, self.admin.email})
        antwort = self.client.get(f"/protokolle/{protokoll.nr}/pdf/")
        self.assertIn("WMC_Ausgabeprotokoll_Becker_Anna_", antwort["Content-Disposition"])

    def test_meldung_nur_wenn_eine_mail_hinausgeht(self):
        from stammdaten.models import Einstellungen
        e = Einstellungen.aktuelles()
        e.mail_protokoll_gesendet = False
        e.save()
        protokoll = self._entwurf(self._gerat())
        self._checkliste(protokoll)
        antwort = self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW}, follow=True)
        self.assertContains(antwort, "es ging keine Mail hinaus")
        self.assertNotContains(antwort, "Mail mit Link gesendet")


class AnhangTests(Grundlage):
    """Kapitel 3.1, Kapitel 6, Dialog anhang."""

    def _hochladen(self, gerat, roh=b"%PDF-1.7\nRechnung", name="rechnung.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(f"/geraete/{gerat.inventarnummer}/anhang/", {"datei": SimpleUploadedFile(name, roh)}, follow=True)

    def test_anhang_am_geraet(self):
        gerat = self._gerat()
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/"), 'data-name="anhang"')
        antwort = self._hochladen(gerat)
        self.assertContains(antwort, "rechnung.pdf")
        anhang = gerat.anhaenge.get()
        offen = self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/{anhang.pk}/")
        self.assertEqual(offen["Content-Type"], "application/pdf")
        self.assertTrue(gerat.vorgaenge.filter(notiz__contains="rechnung.pdf").exists())

    def test_falscher_inhalt_wird_abgelehnt(self):
        gerat = self._gerat()
        antwort = self._hochladen(gerat, b"<html>", "rechnung.pdf")
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertEqual(gerat.anhaenge.count(), 0)

    def test_rollen(self):
        gerat = self._gerat()
        self._hochladen(gerat)
        anhang = gerat.anhaenge.get()
        leser = konto_erstellen("leser.k", "leser", "leser@beispiel.test")
        self.client.force_login(leser)
        self.assertEqual(self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/{anhang.pk}/").status_code, 200)
        self.assertEqual(self._hochladen(gerat).status_code, 403)
        mitarbeiter = konto_erstellen("anna.m", "mitarbeiter", "anna.m@beispiel.test")
        self.client.force_login(mitarbeiter)
        self.assertEqual(self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/{anhang.pk}/").status_code, 403)

    def test_ausgemustert_bleibt_zu(self):
        gerat = self._gerat()
        services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="X", ausgefuehrt_von=self.admin)
        self._hochladen(gerat)
        self.assertEqual(gerat.anhaenge.count(), 0)


class HistorieUndReparaturTests(Grundlage):
    """F-40, F-42, F-88, F-89."""

    def test_aenderungen_in_worten(self):
        gerat = self._gerat(kaufpreis_netto="1234.56", garantie_bis=date(2028, 2, 1))
        services.gerat_bearbeiten(gerat, werte={"garantie_bis": date(2029, 3, 3), "zustand": 3}, erzeugt_von=self.admin)
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(seite, "01.02.2028 → 03.03.2029")
        self.assertNotContains(seite, "garantie_bis:")
        self.assertNotContains(seite, ": (leer) → (leer)")

    def test_geprueft_nennt_das_konto(self):
        gerat = self._gerat()
        services.gerat_pruefen(gerat, self.admin)
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), f"von {self.admin.bezeichnung()}")

    def test_nicht_ermittelbar_steht_im_detail(self):
        gerat = self._gerat(kaufdatum_nicht_ermittelbar=True)
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), "nicht ermittelbar")

    def test_rueckgabe_in_reparatur_mit_nachtrag(self):
        gerat = self._gerat()
        services.gerat_in_reparatur_geschickt(gerat, dienstleister="AltFirma", vorgangsnummer="1", notiz="n", ausgefuehrt_von=self.admin)
        services.gerat_reparatur_fertig(gerat, zustand=2, ziel="lager", kosten=12, beleg="B-7", ausgefuehrt_von=self.admin)
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=3, ziel="reparatur", ausgefuehrt_von=self.admin)
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(seite, "Dienstleister und Vorgangsnummer noch nicht erfasst")
        self.assertContains(seite, "Kosten: 12,00")
        self.assertContains(seite, "Beleg: B-7")
        self.assertContains(seite, 'data-test="verbleib">In Reparatur')
        self.assertContains(seite, 'data-test="aktion-reparatur-angaben"')
        self.client.post(f"/geraete/{gerat.inventarnummer}/reparatur/start/", {"dienstleister": "NeuFirma", "vorgangsnummer": "VG-9", "notiz": "Display"})
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(seite, "NeuFirma")

    def test_abschlussdialog_kennt_zustand_und_zuordnung(self):
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, zustand=3, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_in_reparatur_geschickt(gerat, dienstleister="X", vorgangsnummer="1", notiz="n", ausgefuehrt_von=self.admin)
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/reparatur/fertig/")
        self.assertContains(seite, '<option value="3" selected>')
        self.assertContains(seite, "Anna Becker")

    def test_umzug_auf_denselben_ort_ist_keiner(self):
        platz = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WP-1")
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, platz, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_umziehen(gerat, platz, ausgefuehrt_von=self.admin)


class AusmusterungReservierungTests(Grundlage):
    """F-55, Kapitel 4."""

    def _reserviert(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = Leihe.objects.create(person=self.anna, kat=self.kat, beginn=heute, ende=heute + timedelta(days=5), rueckgabe_bis=heute + timedelta(days=5), status=Leihe.STATUS_ANGEFRAGT)
        services.leihe_genehmigen(leihe, gerat, self.admin)
        gerat.refresh_from_db()
        return gerat, leihe

    def test_reserviertes_geraet_nicht_einfach_ausmustern(self):
        gerat, _leihe = self._reserviert()
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="X", ausgefuehrt_von=self.admin)

    def test_verlust_beendet_die_reservierung_und_sagt_es_der_person(self):
        gerat, leihe = self._reserviert()
        mail.outbox.clear()
        services.ausmustern(gerat, grund="gestohlen", datum=date(2026, 1, 1), disposition="unbekannt", bestaetigt_gemeldt=True, ausgefuehrt_von=self.admin)
        leihe.refresh_from_db()
        gerat.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ABGELEHNT)
        self.assertFalse(gerat.reserviert)
        self.assertEqual(mail.outbox[-1].to, [self.anna.email])

    def test_datum_nicht_in_der_zukunft(self):
        gerat = self._gerat()
        morgen = zeit.jetzt_wie_im_entwicklungsmodus().date() + timedelta(days=1)
        antwort = self.client.post(f"/geraete/{gerat.inventarnummer}/ausmustern/", {"grund": "defekt", "datum": morgen.isoformat(), "disposition": "X"})
        self.assertEqual(antwort.status_code, 200)
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_datenloeschung_nur_bei_datentraegern(self):
        gerat = self._gerat()
        self.assertNotContains(self.client.get(f"/geraete/{gerat.inventarnummer}/ausmustern/"), "Datenlöschung")


class ImportUndUebersichtTests(Grundlage):
    """F-80, F-87, F-101, F-102, F-103."""

    def test_bedarfsanalyse_ist_gesperrt(self):
        from . import import_parser
        self.assertTrue(import_parser.blatt_gesperrt("Bedarfsanalyse Monitore"))
        self.assertFalse(import_parser.blatt_gesperrt("Inventar"))

    def test_kommentar_ergaenzt_die_notiz(self):
        from . import import_parser
        gerat = self._gerat(notiz="Alt")
        w = import_parser.Zeilenwerte(notiz="Standortwechsel")
        self.assertEqual(import_parser.ergaenzungen(gerat, w)["notiz"], "Alt; Standortwechsel")
        w = import_parser.Zeilenwerte(notiz="Alt")
        self.assertNotIn("notiz", import_parser.ergaenzungen(gerat, w))

    def test_delta_folgt_der_angezeigten_zahl(self):
        from stammdaten.models import Zaehlerstand
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin)
        stand = {k["data_id"]: {"ist": k["ist"], "gesamt": k["gesamt"]} for k in kennzahlen.kennzahlen(heute)}
        Zaehlerstand.objects.create(stichtag=heute - timedelta(days=1), kennzahlen=stand)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=2, ausgefuehrt_von=self.admin)
        delta = kennzahlen.delta_zum_vortag(heute)
        self.assertEqual(delta["in-benutzung"], -1)

    def test_leser_landet_nicht_auf_der_genehmigung(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        Leihe.objects.create(nr="L-0001", person=self.anna, kat=self.kat, gerat=gerat, beginn=heute, ende=heute + timedelta(days=5), rueckgabe_bis=heute + timedelta(days=5), status=Leihe.STATUS_ANGEFRAGT)
        self.client.force_login(konto_erstellen("leser.k", "leser", "leser@beispiel.test"))
        self.assertNotContains(self.client.get("/"), "/genehmigen/")

    def test_formel_bleibt_text(self):
        from . import export
        self.assertEqual(export._wert_zelle("=1+1"), "'=1+1")
        self.assertEqual(export._wert_zelle("-12,50"), "-12,50")

    def test_export_von_konten_und_profilen(self):
        self.assertEqual(self.client.get("/konten/?format=csv")["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("spreadsheetml", self.client.get("/profile/?format=xlsx")["Content-Type"])
        self.assertContains(self.client.get("/arbeitsplaetze/bedarf/"), 'data-test="export-xlsx"')

    def test_am_eigenen_arbeitsplatz(self):
        platz = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WP-A", feste_person=self.anna)
        gerat = self._gerat("AM-PLATZ")
        services.gerat_ausgeben(gerat, platz, ausgefuehrt_von=self.admin)
        eigenes = self._gerat("EIGEN")
        services.gerat_ausgeben(eigenes, self.anna, ausgefuehrt_von=self.admin)
        konto = konto_erstellen("anna.m", "mitarbeiter", "anna.m@beispiel.test")
        konto.person = self.anna
        konto.save()
        self.client.force_login(konto)
        seite = self.client.get("/meine-geraete/")
        self.assertContains(seite, 'data-test="am-arbeitsplatz"')
        self.assertContains(seite, gerat.inventarnummer)
        self.assertContains(seite, 'data-test="meine-modell"')


class StartdatenPersonTests(TestCase):
    """N-11."""

    def test_admin_bekommt_eine_person(self):
        import os
        from io import StringIO
        from django.core.management import call_command
        with mock.patch.dict(os.environ, {"ADMIN_EMAIL": "it@beispiel.test", "ADMIN_PASSWORT": "Ein-langes-Passwort-2026", "ADMIN_VORNAME": "Tobias", "ADMIN_NACHNAME": "Klein"}):
            call_command("startdaten", stdout=StringIO())
        self.assertEqual(Konto.objects.get(email="it@beispiel.test").bezeichnung(), "Tobias Klein")
