"""Protokoll nach FRM-001 und FRM-002: Signatur, Einfrieren, Prüfprotokoll, Mail, Fotos, Scan.

Jeder Fall entspricht einem Befund der Prüfung vom 05.11. Geprüft wird über die
Ansichten, soweit es geht, und am Text des erzeugten PDF.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from stammdaten.models import Einstellungen, Kategorie, Ort, Person

from . import pdf as pdf_modul
from . import services
from .models import Gerat, Protokoll, SignaturAufzeichnung, SignaturCode

PW = "test-passwort-123"


def _pdf_text(inhalt: bytes) -> str:
    import pypdfium2 as pdfium
    dokument = pdfium.PdfDocument(io.BytesIO(inhalt))
    return "\n".join(seite.get_textpage().get_text_bounded() for seite in dokument)


def _siegel_bereit() -> None:
    from .siegel import SIEGEL_P12, testsiegel_anlegen
    if not SIEGEL_P12.exists():
        testsiegel_anlegen()


def _jpeg(breite: int = 3000, hoehe: int = 2000) -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (200, 30, 30)).save(puffer, format="JPEG")
    return puffer.getvalue()


class Grundlage(TestCase):
    """Eine Ausgabe auf dem Tool-Weg, Checkliste noch offen."""

    def setUp(self):
        from .tests import konto_erstellen
        self.medien = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.medien, ignore_errors=True)
        ueberschreiben = override_settings(MEDIA_ROOT=self.medien)
        ueberschreiben.enable()
        self.addCleanup(ueberschreiben.disable)

        self.kat = Kategorie.objects.create(name="Notebook")
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="WMC-L-01")
        self.platz = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WMC-A-01")
        self.person = Person.objects.create(
            anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker",
            email="a.becker@beispiel.test",
        )
        self.admin = konto_erstellen("it.admin", "admin", "it-admin@beispiel.test")
        self.zweiter = konto_erstellen("it.zwei", "admin", "it-zwei@beispiel.test")
        self.zweiter.set_password("anderes-passwort-456")
        self.zweiter.save()
        self.gerat = services.gerat_anlegen(
            kategorie=self.kat, hersteller="Lenovo", modell="ThinkPad T14",
            seriennummer="SN-1", ort=self.lager, erzeugt_von=self.admin,
        )
        self.client.force_login(self.admin)

    def _ausgabe(self, **werte) -> Protokoll:
        services.gerat_ausgeben(
            self.gerat, self.person, ausgefuehrt_von=self.admin,
            unterschrift="tool", zustand=2, zubehoer_komplett=False,
            anmerkung="Netzteil fehlt", **werte,
        )
        return Protokoll.objects.filter(geraet=self.gerat).latest("id")

    def _checkliste_fertig(self, protokoll: Protokoll) -> None:
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            protokoll.checkliste[schluessel] = 0
        protokoll.save()

    def _signieren(self, protokoll: Protokoll, passwort: str = PW) -> Protokoll:
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": passwort})
        protokoll.refresh_from_db()
        return protokoll

    def _gegenzeichnen(self, protokoll: Protokoll):
        self.client.logout()
        self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/code-senden/")
        code = SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).latest("id").code
        antwort = self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/", {"code": code})
        protokoll.refresh_from_db()
        return antwort


class SignaturTests(Grundlage):
    """F-135, N-05."""

    def test_kein_passwort_gespeichert(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self._signieren(protokoll)
        namen = [f.name for f in Protokoll._meta.get_fields()]
        self.assertNotIn("bearbeiter_signatur", namen)
        for wert in Protokoll.objects.filter(pk=protokoll.pk).values().first().values():
            self.assertNotIn(PW[:6], str(wert))

    def test_es_zaehlt_das_passwort_des_angemeldeten_kontos(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self.client.force_login(self.zweiter)
        self._signieren(protokoll, PW)
        self.assertIsNone(protokoll.bearbeiter_signiert_am)
        self._signieren(protokoll, "anderes-passwort-456")
        self.assertEqual(protokoll.bearbeiter_signiert_von, self.zweiter)
        self.assertEqual(protokoll.bearbeiter, self.zweiter.bezeichnung())

    def test_fehlversuche_zaehlen_und_sperren(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        for _ in range(5):
            self._signieren(protokoll, "falsch")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.ist_gesperrt())
        self._signieren(protokoll, PW)
        self.assertIsNone(protokoll.bearbeiter_signiert_am)

    def test_zweite_signatur_abgelehnt(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self._signieren(protokoll)
        zeitpunkt = protokoll.bearbeiter_signiert_am
        self._signieren(protokoll)
        self.assertEqual(protokoll.bearbeiter_signiert_am, zeitpunkt)
        self.assertEqual(protokoll.aufzeichnungen.count(), 1)

    def test_person_ohne_email_scheitert_nicht(self):
        self.person.email = None
        self.person.save()
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        antwort = self.client.post(
            f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW}, follow=True,
        )
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)
        self.assertEqual(mail.outbox, [])
        self.assertContains(antwort, "keine E-Mail hinterlegt")

    def test_status_gilt_erst_ab_signatur(self):
        protokoll = self._ausgabe()
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        self._checkliste_fertig(protokoll)
        self._signieren(protokoll)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(self.gerat.person, self.person)

    def test_ruecknahme_aendert_den_status_bei_signatur_nicht(self):
        self.gerat.status = Gerat.STATUS_AUF_LAGER
        self.gerat.save()
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN,
            unterschrift_art="tool",
        )
        for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE:
            protokoll.offboarding[schluessel] = {"status": "nicht_zutreffend"}
        protokoll.save()
        self._signieren(protokoll)
        self.assertEqual(protokoll.stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertIsNone(self.gerat.person)


class ChecklisteTests(Grundlage):
    """F-132, F-133, TESTSCHNITTSTELLE Kapitel 4."""

    def test_ruecknahme_verlangt_keine_checkliste(self):
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN,
        )
        self.assertEqual(protokoll.checkliste_unbeantwortet(), [])
        self.assertTrue(protokoll.offboarding_unbeantwortet())

    def test_leihe_verlangt_keine_checkliste(self):
        from .models import Leihe
        leihe = Leihe.objects.create(person=self.person, gerat=self.gerat, kat=self.kat)
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            stand=Protokoll.STAND_BEARBEITER_OFFEN, leihe=leihe,
        )
        self.assertEqual(protokoll.checkliste_unbeantwortet(), [])

    def test_seite_nimmt_die_werte_der_testschnittstelle(self):
        protokoll = self._ausgabe()
        daten = {}
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            daten[f"checkliste.{schluessel}"] = "ausgegeben"
            daten[f"checkliste.{schluessel}.bemerkung"] = "Kennung abc"
        self.client.post(f"/protokolle/{protokoll.nr}/checkliste/", daten)
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.checkliste_unbeantwortet(), [])
        schluessel = Protokoll.CHECKLISTE_PUNKTE[0][0]
        self.assertEqual(protokoll.checkliste[schluessel], 1)
        self.assertEqual(protokoll.checkliste_bemerkung[schluessel], "Kennung abc")

    def test_zeile_hat_die_marker(self):
        protokoll = self._ausgabe()
        antwort = self.client.get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(antwort, 'data-test="checkpunkt" data-liste="zugaenge" data-nr="1"')

    def test_ruecknahme_seite_hat_die_marker(self):
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN,
        )
        antwort = self.client.get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(antwort, 'data-test="checkpunkt" data-liste="offboarding" data-nr="1"')


class PdfTests(Grundlage):
    """F-130, F-131, F-133, F-137, FRM-001, FRM-002."""

    def _text(self, protokoll: Protokoll) -> str:
        return _pdf_text(pdf_modul.pdf_bauen(protokoll))

    def test_absender_und_firmendaten_aus_den_einstellungen(self):
        e = Einstellungen.aktuelles()
        e.firmenname = "Muster AG"
        e.absenderzeile = "Muster AG, Teststraße 1, 12345 Musterstadt"
        e.telefon = "+49 111 222"
        e.email_it = "it@muster.test"
        e.save()
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        text = self._text(protokoll)
        for wert in ("Muster AG, Teststraße 1", "+49 111 222", "it@muster.test"):
            self.assertIn(wert, text)
        self.assertNotIn("Wamocon GmbH", text)

    def test_platzhalter_firmenname_wird_ersetzt(self):
        e = Einstellungen.aktuelles()
        e.firmenname = "Muster AG"
        e.nutzungsbedingungen_ausgabe = "Die {Firmenname} stellt bereit.\n\nZweiter Absatz."
        e.save()
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        text = self._text(protokoll)
        self.assertIn("Die Muster AG stellt bereit.", text)
        self.assertNotIn("{Firmenname}", text)

    def test_anrede_je_person(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self.assertIn("Sehr geehrte Frau Becker", self._text(protokoll))
        self.person.anrede = Person.ANREDE_HERR
        self.person.save()
        protokoll = Protokoll.objects.get(pk=protokoll.pk)
        self.assertIn("Sehr geehrter Herr Becker", self._text(protokoll))

    def test_dialogwerte_stehen_im_pdf(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        text = self._text(protokoll)
        self.assertIn("Netzteil fehlt", text)
        self.assertIn("Ausgabeprotokoll Hardware (Onboarding)", text)
        self.assertIn("WMC-IT-FRM-001", text)

    def test_leihe_hat_keine_checkliste_und_den_festen_satz(self):
        from .models import Leihe
        leihe = Leihe.objects.create(
            person=self.person, gerat=self.gerat, kat=self.kat, nr="L-2026-0007", zweck="Messe",
        )
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            stand=Protokoll.STAND_BEARBEITER_OFFEN, leihe=leihe,
        )
        text = self._text(protokoll)
        self.assertIn("Ausgabeprotokoll Hardware (Leihe)", text)
        self.assertIn("Bei einer Leihe werden keine Zugänge ausgegeben.", text)
        self.assertIn("L-2026-0007", text)
        self.assertIn("Messe", text)

    def test_ruecknahme_mit_maengeln_und_klaerung(self):
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN,
            positionen=[services.position_aus_gerat(
                self.gerat, zustand_rueckgabe=3, zubehoer_komplett=False, bemerkung="Displaykratzer",
            )],
        )
        erster = Protokoll.OFFBOARDING_PUNKTE[0][0]
        for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE:
            protokoll.offboarding[schluessel] = {"status": "nicht_zutreffend"}
        protokoll.offboarding[erster] = {"status": "in_klaerung", "bemerkung": ""}
        protokoll.save()
        text = self._text(protokoll)
        self.assertIn("Rücknahmeprotokoll Hardware (Rückgabe)", text)
        self.assertIn("WMC-IT-FRM-002", text)
        self.assertIn("Displaykratzer", text)
        self.assertIn("in Klärung", text)
        self.assertNotIn("Keine. Die Hardware wurde vollständig", text)

    def test_ruecknahme_ohne_maengel_hat_den_satz(self):
        protokoll = services._protokoll_erstellen(
            person=self.person, gerat=self.gerat, erzeugt_von=self.admin,
            art=Protokoll.ART_RUECKNAHME, stand=Protokoll.STAND_BEARBEITER_OFFEN,
        )
        for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE:
            protokoll.offboarding[schluessel] = {"status": "erledigt"}
        protokoll.save()
        self.assertIn("Keine. Die Hardware wurde vollständig", self._text(protokoll))

    def test_fusszeile_mit_seite_x_von_y(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        text = self._text(protokoll)
        self.assertIn("Version 1.1", text)
        self.assertRegex(text, r"Seite 1 von \d")

    def test_signatur_friert_den_inhalt_ein(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self._signieren(protokoll)
        self.assertTrue(protokoll.html_eingefroren)
        self.gerat.hersteller = "Andere Firma"
        self.gerat.save()
        self.person.nachname = "Neuername"
        self.person.save()
        e = Einstellungen.aktuelles()
        e.absenderzeile = "Neue Zeile nach der Signatur"
        e.save()
        text = self._text(Protokoll.objects.get(pk=protokoll.pk))
        self.assertIn("Lenovo", text)
        self.assertIn("Becker", text)
        self.assertNotIn("Andere Firma", text)
        self.assertNotIn("Neue Zeile nach der Signatur", text)
        # Nach der Signatur kommt nur noch der Vermerk dazu.
        self.assertIn("Elektronisch signiert", text)

    def test_pruefprotokoll_ist_die_letzte_seite(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self._signieren(protokoll)
        inhalt = pdf_modul.pdf_fertig_bauen(protokoll, versiegeln=False)
        import pypdfium2 as pdfium
        dokument = pdfium.PdfDocument(io.BytesIO(inhalt))
        letzte = dokument[len(dokument) - 1].get_textpage().get_text_bounded()
        aufzeichnung = protokoll.aufzeichnungen.get()
        self.assertIn("Prüfprotokoll", letzte)
        self.assertIn(self.admin.email, letzte)
        self.assertIn(aufzeichnung.nachweisnummer, letzte)
        self.assertRegex(aufzeichnung.nachweisnummer, r"^SIG-\d{4}-\d{4}$")
        self.assertIn("127.0.0.1", letzte)
        self.assertEqual(len(aufzeichnung.hashwert), 64)
        self.assertIn(aufzeichnung.hashwert[:20], letzte.replace("\r\n", "").replace("\n", ""))

    def test_dateiname_nach_f139(self):
        protokoll = self._ausgabe()
        name = pdf_modul.dateiname_protokoll(protokoll)
        self.assertRegex(name, r"^WMC_Ausgabeprotokoll_Becker_Anna_\d{2}\.\d{2}\.\d{4}\.pdf$")


class GegenzeichnungTests(Grundlage):
    """F-136, F-138, F-139, F-140, F-141."""

    def _signiert(self) -> Protokoll:
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        return self._signieren(protokoll)

    def test_mail_hat_einen_vollen_link(self):
        protokoll = self._signiert()
        self.assertEqual(len(mail.outbox), 1)
        from django.conf import settings
        self.assertIn(f"{settings.BASIS_URL}/signieren/{protokoll.gegenzeichnung_token}/", mail.outbox[0].body)
        self.assertIn("Sehr geehrte Frau Becker", mail.outbox[0].body)

    def test_absender_kommt_aus_den_einstellungen_der_umgebung(self):
        from django.conf import settings
        self._signiert()
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)

    def test_code_steht_nur_in_der_code_mail(self):
        protokoll = self._signiert()
        self.assertNotIn("Einmalcode:", mail.outbox[0].body)
        self.client.logout()
        self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/code-senden/")
        code = SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).latest("id")
        self.assertEqual(len(code.code), 6)
        self.assertIn(code.code, mail.outbox[-1].body)

    def test_link_neu_senden_ohne_code_und_mit_anderer_adresse(self):
        protokoll = self._signiert()
        alter_token = protokoll.gegenzeichnung_token
        self.client.post(f"/protokolle/{protokoll.nr}/link-neu-senden/", {"empfaenger": "privat@beispiel.test"})
        protokoll.refresh_from_db()
        self.assertNotEqual(protokoll.gegenzeichnung_token, alter_token)
        self.assertEqual(protokoll.gegenzeichnung_empfaenger, "privat@beispiel.test")
        letzte = mail.outbox[-1]
        self.assertEqual(letzte.to, ["privat@beispiel.test"])
        self.assertNotIn("Einmalcode:", letzte.body)
        self.client.logout()
        self.assertEqual(self.client.get(f"/signieren/{alter_token}/").status_code, 404)

    def test_adresse_steht_im_pruefprotokoll(self):
        protokoll = self._signiert()
        self.client.post(f"/protokolle/{protokoll.nr}/link-neu-senden/", {"empfaenger": "privat@beispiel.test"})
        protokoll.refresh_from_db()
        self._gegenzeichnen(protokoll)
        aufzeichnung = protokoll.aufzeichnungen.get(art=SignaturAufzeichnung.KIND_GEGENZEICHNUNG)
        self.assertEqual(aufzeichnung.email, "privat@beispiel.test")
        self.assertIn("privat@beispiel.test", aufzeichnung.identifikationsmerkmal)

    def test_abgeschlossen_mit_siegel_und_zwei_mails(self):
        _siegel_bereit()
        protokoll = self._signiert()
        mail.outbox.clear()
        self._gegenzeichnen(protokoll)
        self.assertEqual(protokoll.stand, Protokoll.STAND_ABGESCHLOSSEN)
        self.assertTrue(bytes(protokoll.pdf_siegel).startswith(b"%PDF"))
        anhang_mails = [m for m in mail.outbox if m.attachments]
        self.assertEqual({m.to[0] for m in anhang_mails}, {"a.becker@beispiel.test", self.admin.email})
        self.assertIn(pdf_modul.dateiname_protokoll(protokoll), [a[0] for a in anhang_mails[0].attachments])

    def test_ohne_siegel_kein_abschluss(self):
        """F-138: Geht das Siegel nicht, bleibt das Protokoll offen."""
        protokoll = self._signiert()
        with mock.patch("geraete.siegel.siegel_anwenden", return_value=None):
            antwort = self._gegenzeichnen(protokoll)
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(protokoll.stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)
        self.assertIsNone(protokoll.gegenzeichnung_signiert_am)
        self.assertFalse(protokoll.pdf_siegel)
        self.assertEqual(protokoll.aufzeichnungen.filter(art=SignaturAufzeichnung.KIND_GEGENZEICHNUNG).count(), 0)

    def test_x_forwarded_for_zaehlt_ohne_proxy_nicht(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        self.client.post(
            f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW},
            HTTP_X_FORWARDED_FOR="203.0.113.9",
        )
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.bearbeiter_ip, "127.0.0.1")

    def test_pdf_nur_solange_der_link_gilt(self):
        from django.utils import timezone
        from datetime import timedelta
        protokoll = self._signiert()
        self.client.logout()
        self.assertEqual(self.client.get(f"/signieren/{protokoll.gegenzeichnung_token}/pdf/").status_code, 200)
        protokoll.gegenzeichnung_token_erstellt = timezone.now() - timedelta(days=15)
        protokoll.save()
        self.assertEqual(self.client.get(f"/signieren/{protokoll.gegenzeichnung_token}/pdf/").status_code, 410)
        self.assertEqual(self.client.get(f"/signieren/{protokoll.gegenzeichnung_token}/").status_code, 410)

    def test_unbekannter_link_hat_einen_rahmen(self):
        self.client.logout()
        antwort = self.client.get("/signieren/unbekannt/", follow=True)
        self.assertEqual(antwort.status_code, 404)
        self.assertContains(antwort, 'data-test="signieren-hinweis"', status_code=404)

    def test_korrektur_ersetzt_das_alte_protokoll(self):
        protokoll = self._signiert()
        alter_token = protokoll.gegenzeichnung_token
        self.client.post(f"/protokolle/{protokoll.nr}/korrigieren/")
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.stand, Protokoll.STAND_ERSETZT)
        self.assertEqual(protokoll.gegenzeichnung_token, "")
        neu = protokoll.korrekturen.get()
        self.assertEqual(neu.stand, Protokoll.STAND_BEARBEITER_OFFEN)
        self.assertNotEqual(neu.nr, protokoll.nr)
        self.assertEqual(neu.positionen, protokoll.positionen)
        self.assertEqual(neu.html_eingefroren, "")
        self.client.logout()
        self.assertEqual(self.client.get(f"/signieren/{alter_token}/").status_code, 404)

    def test_neue_fassung_laesst_das_geraet_in_ruhe(self):
        protokoll = self._signiert()
        vorgaenge = self.gerat.vorgaenge.count()
        self.client.post(f"/protokolle/{protokoll.nr}/korrigieren/")
        neu = Protokoll.objects.get(korrigiert_zu_protokoll=protokoll)
        self._signieren(neu)
        self.assertEqual(neu.stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)
        self.assertEqual(self.gerat.vorgaenge.count(), vorgaenge)

    def test_ersetztes_protokoll_laesst_sich_nicht_erneut_korrigieren(self):
        protokoll = self._signiert()
        self.client.post(f"/protokolle/{protokoll.nr}/korrigieren/")
        self.client.post(f"/protokolle/{protokoll.nr}/korrigieren/")
        self.assertEqual(protokoll.korrekturen.count(), 1)

    def test_abgeschlossenes_pdf_ist_das_siegel(self):
        _siegel_bereit()
        protokoll = self._signiert()
        self._gegenzeichnen(protokoll)
        self.client.force_login(self.admin)
        antwort = self.client.get(f"/protokolle/{protokoll.nr}/pdf/")
        self.assertEqual(antwort.content, bytes(protokoll.pdf_siegel))


class FotoUndScanTests(Grundlage):
    """F-22, F-134, N-02."""

    def _foto(self, protokoll, roh, name="foto.jpg", typ="image/jpeg", follow=True):
        return self.client.post(
            f"/protokolle/{protokoll.nr}/foto/",
            {"foto": SimpleUploadedFile(name, roh, content_type=typ)},
            follow=follow,
        )

    def test_echtes_foto_wird_verkleinert_und_steht_im_pdf(self):
        protokoll = self._ausgabe()
        self._checkliste_fertig(protokoll)
        ohne = len(pdf_modul.pdf_bauen(protokoll))
        self._foto(protokoll, _jpeg())
        protokoll.refresh_from_db()
        self.assertEqual(len(protokoll.anhaenge), 1)
        from django.core.files.storage import default_storage
        with default_storage.open(protokoll.anhaenge[0]["pfad"]) as handle:
            bild = Image.open(handle)
            self.assertLessEqual(max(bild.size), 1600)
        mit = pdf_modul.pdf_bauen(Protokoll.objects.get(pk=protokoll.pk))
        self.assertGreater(len(mit), ohne)
        self.assertIn("Ausgabe", _pdf_text(mit))

    def test_textdatei_als_jpg_wird_abgelehnt(self):
        protokoll = self._ausgabe()
        antwort = self._foto(protokoll, b"kein Bild, nur Text")
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.anhaenge, [])
        self.assertContains(antwort, "Fotoformat nicht erlaubt")

    def test_kaputtes_jpg_wird_abgelehnt(self):
        protokoll = self._ausgabe()
        antwort = self._foto(protokoll, b"\xff\xd8\xff" + b"kaputt" * 100)
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.anhaenge, [])
        self.assertContains(antwort, "kein lesbares Bild")

    def test_zu_grosses_foto_wird_abgelehnt(self):
        protokoll = self._ausgabe()
        antwort = self._foto(protokoll, b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024 + 10))
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.anhaenge, [])
        self.assertContains(antwort, "größer als 10 MB")

    def _scan(self, roh, name="scan.pdf", typ="application/pdf"):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.filter(geraet=self.gerat).latest("id")
        antwort = self.client.post(
            f"/protokolle/{protokoll.nr}/scan/",
            {"scan": SimpleUploadedFile(name, roh, content_type=typ)},
            follow=True,
        )
        protokoll.refresh_from_db()
        return protokoll, antwort

    def test_scan_schliesst_ab_und_ist_abrufbar(self):
        protokoll, _ = self._scan(b"%PDF-1.7\n%Beispiel\n")
        self.assertEqual(protokoll.stand, Protokoll.STAND_ABGESCHLOSSEN)
        antwort = self.client.get(f"/protokolle/{protokoll.nr}/pdf/")
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertEqual(antwort.content, b"%PDF-1.7\n%Beispiel\n")

    def test_scan_mit_falschem_inhalt_wird_abgelehnt(self):
        protokoll, antwort = self._scan(b"<html>kein Scan</html>")
        self.assertEqual(protokoll.stand, Protokoll.STAND_SCAN_OFFEN)
        self.assertContains(antwort, "Scan nicht erlaubt")

    def test_scan_seite_hat_den_dialog(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.filter(geraet=self.gerat).latest("id")
        self.assertContains(self.client.get(f"/protokolle/{protokoll.nr}/"), 'data-name="scan-hochladen"')


class AusgabeRegelnTests(Grundlage):
    """F-20, F-21, Kapitel 4."""

    def test_nur_aus_auf_lager(self):
        services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)

    def test_lager_ist_kein_ziel(self):
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.lager, ausgefuehrt_von=self.admin)

    def test_arbeitsplatz_ist_ein_ziel(self):
        services.gerat_ausgeben(self.gerat, self.platz, ausgefuehrt_von=self.admin)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(self.gerat.ort, self.platz)

    def test_offener_entwurf_sperrt_auch_den_papierweg(self):
        self._ausgabe()
        with self.assertRaises(services.GeratFehler):
            services.gerat_ausgeben(self.gerat, self.person, ausgefuehrt_von=self.admin)

    def test_entwurf_verwerfen_laesst_das_geraet_unveraendert(self):
        protokoll = self._ausgabe()
        antwort = self.client.post(f"/protokolle/{protokoll.nr}/abbrechen/")
        self.assertFalse(Protokoll.objects.filter(pk=protokoll.pk).exists())
        self.assertRedirects(antwort, f"/geraete/{self.gerat.inventarnummer}/", fetch_redirect_response=False)
        self.gerat.refresh_from_db()
        self.assertEqual(self.gerat.status, Gerat.STATUS_AUF_LAGER)
