"""Aufnahme, Ausgabe, Rückgabe, Reparatur, Ausmusterung, Historie (Prüfung vom 05.11.)."""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from stammdaten.models import Kategorie, Ort, Person

from . import pdf as pdf_modul
from . import services
from .models import Gerat, Leihe, Protokoll, Vorgang
from .tests import konto_erstellen

PW = "test-passwort-123"


def _pdf_text(inhalt: bytes) -> str:
    import pypdfium2 as pdfium
    dokument = pdfium.PdfDocument(io.BytesIO(inhalt))
    return "\n".join(seite.get_textpage().get_text_bounded() for seite in dokument)


class Grundlage(TestCase):
    def setUp(self):
        self.medien = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.medien, ignore_errors=True)
        ueberschreiben = override_settings(MEDIA_ROOT=self.medien)
        ueberschreiben.enable()
        self.addCleanup(ueberschreiben.disable)
        self.notebook = Kategorie.objects.create(name="Notebook", hat_datentraeger=True, seriennummer_pflicht=True)
        self.maus = Kategorie.objects.create(name="Maus")
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-A")
        self.lager2 = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-B")
        self.platz = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WP-01")
        self.anna = Person.objects.create(anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker", email="anna@beispiel.test")
        self.felix = Person.objects.create(anrede=Person.ANREDE_HERR, vorname="Felix", nachname="Hoffmann", email="felix@beispiel.test")
        self.admin = konto_erstellen("it.admin", "admin", "it-admin@beispiel.test")
        self.client.force_login(self.admin)

    def _gerat(self, seriennummer="SN-1", kategorie=None, **werte) -> Gerat:
        return services.gerat_anlegen(
            kategorie=kategorie or self.notebook, hersteller="Lenovo", modell="T14",
            seriennummer=seriennummer, ort=self.lager, erzeugt_von=self.admin, **werte,
        )

    def _ausgegeben(self, gerat, person=None, zustand=2) -> Gerat:
        services.gerat_ausgeben(gerat, person or self.anna, zustand=zustand, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        return gerat

    def _neu_daten(self, **werte) -> dict:
        daten = {"kategorie": self.maus.pk, "hersteller": "Logi", "modell": "M1", "zustand": 1}
        daten.update(werte)
        return daten


class AufnahmeTests(Grundlage):
    """F-10, F-11, F-12."""

    def test_person_im_formular_wird_ignoriert(self):
        self.client.post("/geraete/speichern/", self._neu_daten(person=self.anna.pk))
        gerat = Gerat.objects.get(modell="M1")
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertIsNone(gerat.person)

    def test_kein_arbeitsplatz_bei_der_aufnahme(self):
        antwort = self.client.post("/geraete/speichern/", self._neu_daten(ort=self.platz.pk))
        self.assertEqual(antwort.status_code, 200)
        self.assertFalse(Gerat.objects.filter(modell="M1").exists())

    def test_ohne_lagerort_gilt_der_erste(self):
        self.client.post("/geraete/speichern/", self._neu_daten())
        self.assertEqual(Gerat.objects.get(modell="M1").ort, self.lager)

    def test_lagerort_wird_uebernommen(self):
        self.client.post("/geraete/speichern/", self._neu_daten(ort=self.lager2.pk))
        self.assertEqual(Gerat.objects.get(modell="M1").ort, self.lager2)

    def test_doppelte_seriennummer_laesst_die_eingaben_stehen(self):
        self._gerat("SN-X", kategorie=self.maus)
        antwort = self.client.post(
            "/geraete/speichern/", self._neu_daten(hersteller="Lenovo", seriennummer="SN-X", modell="M9", notiz="meine Notiz"),
        )
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "meine Notiz")
        self.assertContains(antwort, 'data-test="fehler"')

    def test_mehrfacherfassung_ganz_oder_gar_nicht(self):
        vorher = Gerat.objects.count()
        antwort = self.client.post("/geraete/speichern/", self._neu_daten(seriennummern="N-1\nN-2\nN-1\nN-3"))
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(Gerat.objects.count(), vorher)
        self.assertContains(antwort, "N-3")

    def test_einzelfeld_und_liste_zusammen(self):
        self.client.post("/geraete/speichern/", self._neu_daten(seriennummer="E-1", seriennummern="L-1\nL-2"))
        self.assertEqual(
            set(Gerat.objects.filter(modell="M1").values_list("seriennummer", flat=True)),
            {"E-1", "L-1", "L-2"},
        )

    def test_etikett_auch_bei_mehreren(self):
        antwort = self.client.post(
            "/geraete/speichern/", self._neu_daten(seriennummern="P-1\nP-2\nP-3", aktion="etikett"),
        )
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertEqual(Gerat.objects.filter(modell="M1").count(), 3)

    def test_vorlage_uebernimmt_kein_fremdes_ziel(self):
        gerat = self._ausgegeben(self._gerat("SN-V"))
        antwort = self.client.get(f"/geraete/neu/?vorlage={gerat.inventarnummer}")
        self.assertEqual(antwort.status_code, 200)
        self.assertNotContains(antwort, 'name="person"')


class AenderungTests(Grundlage):
    """F-40, F-43, F-58."""

    def _aendern_daten(self, gerat, **werte):
        daten = {"kategorie": gerat.kategorie_id, "hersteller": gerat.hersteller, "modell": gerat.modell,
                 "seriennummer": gerat.seriennummer, "zustand": gerat.zustand}
        daten.update(werte)
        return daten

    def test_aendern_wechselt_keine_person(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/aendern/", self._aendern_daten(gerat, person=self.felix.pk, lieferant="Neu"))
        gerat.refresh_from_db()
        self.assertEqual(gerat.person, self.anna)
        self.assertEqual(gerat.lieferant, "Neu")

    def test_geraet_mit_person_und_platz_laesst_sich_aendern(self):
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ziel_ort=self.platz, ausgefuehrt_von=self.admin)
        self.client.post(f"/geraete/{gerat.inventarnummer}/aendern/", self._aendern_daten(gerat, lieferant="Neu"))
        gerat.refresh_from_db()
        self.assertEqual(gerat.lieferant, "Neu")
        self.assertEqual(gerat.ort, self.platz)

    def test_notiz_schreibt_einen_vorgang(self):
        gerat = self._gerat()
        self.client.post(f"/geraete/{gerat.inventarnummer}/notiz/", {"notiz": "Hallo"})
        vorgang = gerat.vorgaenge.get(aenderung_feld="notiz")
        self.assertEqual(vorgang.aenderung_neuer_wert, "Hallo")

    def test_ausgemustert_bleibt_zu(self):
        gerat = self._gerat(kategorie=self.maus, seriennummer="")
        services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="Entsorger", ausgefuehrt_von=self.admin)
        self.client.post(f"/geraete/{gerat.inventarnummer}/notiz/", {"notiz": "NACH-ARCHIV"})
        self.client.post(f"/geraete/{gerat.inventarnummer}/pruefen/")
        gerat.refresh_from_db()
        self.assertNotEqual(gerat.notiz, "NACH-ARCHIV")
        self.assertIsNone(gerat.zuletzt_geprueft_am)

    def test_historie_zeigt_vorher_und_nachher(self):
        gerat = self._ausgegeben(self._gerat())
        vorgang = gerat.vorgaenge.get(typ=Vorgang.TYP_AUSGABE)
        self.assertEqual(vorgang.status_vorher, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(vorgang.status_nachher, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(vorgang.person_nachher, "Anna Becker")
        self.assertEqual(vorgang.ort_vorher, "LAGER-A")
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(antwort, "Status: Auf Lager → In Benutzung")
        self.assertContains(antwort, "Person: – → Anna Becker")

    def test_historie_verlinkt_das_protokoll(self):
        gerat = self._ausgegeben(self._gerat())
        protokoll = gerat.alle_protokolle().first()
        self.assertContains(
            self.client.get(f"/geraete/{gerat.inventarnummer}/"),
            f'href="/protokolle/{protokoll.nr}/" data-test="vorgang-protokoll"',
        )


class LoeschenTests(Grundlage):
    """F-14: Ein Entwurf verschwindet nicht still."""

    def test_entwurf_sperrt_das_loeschen(self):
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")
        self.assertNotContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-loeschen"')
        self.client.post(f"/geraete/{gerat.inventarnummer}/loeschen/")
        self.assertTrue(Gerat.objects.filter(pk=gerat.pk).exists())


class SammelausgabeTests(Grundlage):
    """F-20, F-21."""

    def _drei(self):
        return [self._gerat(f"S-{i}") for i in range(3)]

    def _post(self, geraete, **werte):
        daten = {"auswahl": [g.inventarnummer for g in geraete], "ziel_person": self.anna.pk, "unterschrift": "tool"}
        daten.update(werte)
        return self.client.post("/geraete/sammelausgabe/", daten)

    def test_ein_protokoll_fuer_alle(self):
        geraete = self._drei()
        self._post(geraete, **{f"zustand-{geraete[1].inventarnummer}": 3, f"zubehoer-{geraete[1].inventarnummer}": "nein", f"anmerkung-{geraete[1].inventarnummer}": "Kratzer"})
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        self.assertEqual(len(protokoll.positionen), 3)
        self.assertEqual(protokoll.positionen[1]["zustand_ausgabe"], 3)
        self.assertIs(protokoll.positionen[1]["zubehoer_komplett"], False)
        self.assertEqual(protokoll.positionen[1]["bemerkung"], "Kratzer")
        for gerat in geraete:
            self.assertEqual(gerat.alle_protokolle().get(), protokoll)
            gerat.refresh_from_db()
            self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_signatur_macht_alle_wirksam(self):
        geraete = self._drei()
        self._post(geraete)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            protokoll.checkliste[schluessel] = 0
        protokoll.save()
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        for gerat in geraete:
            gerat.refresh_from_db()
            self.assertEqual(gerat.status, Gerat.STATUS_IN_BENUTZUNG)
            self.assertEqual(gerat.person, self.anna)
            self.assertEqual(gerat.vorgaenge.filter(typ=Vorgang.TYP_AUSGABE).count(), 1)

    def test_pdf_zeigt_alle(self):
        geraete = self._drei()
        self._post(geraete)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            protokoll.checkliste[schluessel] = 0
        protokoll.save()
        text = _pdf_text(pdf_modul.pdf_bauen(protokoll))
        for gerat in geraete:
            self.assertIn(gerat.seriennummer, text)

    def test_nicht_ausgebbares_wird_genannt_und_uebersprungen(self):
        geraete = self._drei()
        self._ausgegeben(geraete[0], self.felix)
        antwort = self.client.get("/geraete/sammelausgabe/", {"auswahl": [g.inventarnummer for g in geraete]})
        self.assertContains(antwort, 'data-test="nicht-waehlbar"')
        self.assertContains(antwort, f'data-test="zeile" data-id="{geraete[1].inventarnummer}"')
        self.assertNotContains(antwort, f'data-test="zeile" data-id="{geraete[0].inventarnummer}"')

    def test_entwurf_sperrt_jedes_seiner_geraete(self):
        geraete = self._drei()
        self._post(geraete)
        self.assertIn("offenes Protokoll", services.ausgabe_sperrgrund(Gerat.objects.get(pk=geraete[2].pk)))

    def test_mitarbeiter_darf_nicht(self):
        konto = konto_erstellen("anna.m", "mitarbeiter", "anna.m@beispiel.test")
        self.client.force_login(konto)
        self.assertEqual(self.client.get("/geraete/sammelausgabe/").status_code, 403)


class RueckgabeTests(Grundlage):
    """F-50, F-51, F-141."""

    def _daten(self, **werte):
        daten = {"zustand_rueckgabe": 3, "zubehoer_komplett": "nein", "maengel": "Displaykratzer", "ziel": "lager", "unterschrift": "tool"}
        daten.update(werte)
        return daten

    def test_dialog_zeigt_den_zustand_bei_ausgabe(self):
        gerat = self._ausgegeben(self._gerat(), zustand=3)
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/rueckgeben/")
        self.assertContains(antwort, 'data-test="zustand-ausgabe"')
        self.assertContains(antwort, "<strong>3</strong>")
        self.assertContains(antwort, '<option value="3" selected>')

    def test_protokoll_traegt_die_eingaben(self):
        gerat = self._ausgegeben(self._gerat(), zustand=2)
        ausgabe = gerat.alle_protokolle().first()
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten())
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(gerat.zustand, 3)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(protokoll.stand, Protokoll.STAND_BEARBEITER_OFFEN)
        self.assertEqual(protokoll.rueckgabe_zu_protokoll, ausgabe)
        position = protokoll.positionen[0]
        self.assertEqual(position["zustand_ausgabe"], 2)
        self.assertEqual(position["zustand_rueckgabe"], 3)
        self.assertIs(position["zubehoer_komplett"], False)
        self.assertEqual(position["bemerkung"], "Displaykratzer")
        text = _pdf_text(pdf_modul.pdf_bauen(protokoll))
        self.assertIn("Displaykratzer", text)
        self.assertIn(ausgabe.nr, text)
        self.assertNotIn("Keine. Die Hardware", text)

    def test_ganzer_ablauf_elektronisch(self):
        from .models import SignaturCode
        from .siegel import SIEGEL_P12, testsiegel_anlegen
        if not SIEGEL_P12.exists():
            testsiegel_anlegen()
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten())
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(self.client.get(f"/protokolle/{protokoll.nr}/pdf/").status_code, 200)
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)
        self.client.logout()
        self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/code-senden/")
        code = SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).latest("id").code
        self.client.post(f"/signieren/{protokoll.gegenzeichnung_token}/", {"code": code})
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.stand, Protokoll.STAND_ABGESCHLOSSEN)
        self.assertTrue(protokoll.ruecknahme_geraet_im_lager)

    def test_papierweg_steht_auf_scan_offen(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(unterschrift="papier"))
        self.assertEqual(Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME).stand, Protokoll.STAND_SCAN_OFFEN)

    def test_adresse_fuer_den_link(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(empfaenger="privat@beispiel.test"))
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        from django.core import mail
        self.assertEqual(mail.outbox[-1].to, ["privat@beispiel.test"])

    def test_lagerort_wird_gesetzt(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(lager_ort=self.lager2.pk))
        gerat.refresh_from_db()
        self.assertEqual(gerat.ort, self.lager2)
        self.assertIsNone(gerat.person)

    def test_ziel_reparatur(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(ziel="reparatur"))
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_IN_REPARATUR)

    def test_fehlt_fuehrt_in_den_dialog(self):
        gerat = self._ausgegeben(self._gerat())
        antwort = self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(ziel="fehlend"))
        self.assertRedirects(antwort, f"/geraete/{gerat.inventarnummer}/ausmustern/?grund=verloren")
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        dialog = self.client.get(antwort["Location"])
        self.assertContains(dialog, '<option value="verloren" selected>')

    def test_leihe_endet_mit_der_rueckgabe(self):
        gerat = self._ausgegeben(self._gerat())
        leihe = Leihe.objects.create(person=self.anna, gerat=gerat, kat=self.notebook, status=Leihe.STATUS_AUSGEGEBEN)
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten())
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEGEBEN)

    def test_austritt_laesst_die_pruefpunkte_offen(self):
        self.anna.austritt = date(2026, 12, 31)
        self.anna.save()
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten())
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(len(protokoll.offboarding_unbeantwortet()), 12)
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
        protokoll.refresh_from_db()
        self.assertIsNone(protokoll.bearbeiter_signiert_am)
        self.assertIn("(Offboarding)", pdf_modul._titel(protokoll))

    def test_normale_rueckgabe_belegt_vor(self):
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten())
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(protokoll.offboarding_unbeantwortet(), [])
        erster = Protokoll.OFFBOARDING_PUNKTE[0][0]
        zweiter = Protokoll.OFFBOARDING_PUNKTE[1][0]
        letzter = Protokoll.OFFBOARDING_PUNKTE[-1][0]
        self.assertEqual(protokoll.offboarding[erster]["status"], "erledigt")
        self.assertEqual(protokoll.offboarding[zweiter]["status"], "nicht_zutreffend")
        self.assertEqual(protokoll.offboarding[letzter]["status"], "erledigt")

    def test_foto_aus_dem_dialog(self):
        from PIL import Image
        puffer = io.BytesIO()
        Image.new("RGB", (400, 300), (10, 20, 30)).save(puffer, format="JPEG")
        gerat = self._ausgegeben(self._gerat())
        self.client.post(f"/geraete/{gerat.inventarnummer}/rueckgeben/", self._daten(
            fotos=SimpleUploadedFile("kratzer.jpg", puffer.getvalue(), content_type="image/jpeg"),
        ))
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(protokoll.fotos, 1)
        self.assertEqual(protokoll.anhaenge[0]["inventarnummer"], gerat.inventarnummer)


class OffboardingTests(Grundlage):
    """F-52."""

    def _vorbereitet(self):
        self.g1 = self._ausgegeben(self._gerat("O-1"))
        self.g2 = self._ausgegeben(self._gerat("O-2"))
        self.g3 = self._ausgegeben(self._gerat("O-3"))
        services.gerat_in_reparatur_geschickt(self.g3, dienstleister="X", vorgangsnummer="1", notiz="n", ausgefuehrt_von=self.admin)
        self.leihe = Leihe.objects.create(person=self.anna, kat=self.notebook, nr="L-0009", status=Leihe.STATUS_ANGEFRAGT)

    def test_ansicht_zeigt_alles(self):
        self._vorbereitet()
        antwort = self.client.get(f"/personen/{self.anna.pk}/offboarding/")
        for nummer in (self.g1, self.g2, self.g3):
            self.assertContains(antwort, f'data-id="{nummer.inventarnummer}"')
        self.assertContains(antwort, "L-0009")
        self.assertContains(antwort, "Alle Geräte zurücknehmen")

    def test_alle_ein_protokoll(self):
        self._vorbereitet()
        antwort = self.client.post(
            f"/personen/{self.anna.pk}/offboarding/zuruecknehmen/",
            {"aktion": "alle", f"zustand-{self.g1.inventarnummer}": 4, f"maengel-{self.g1.inventarnummer}": "Riss"},
        )
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertRedirects(antwort, f"/protokolle/{protokoll.nr}/", fetch_redirect_response=False)
        self.assertEqual(len(protokoll.positionen), 3)
        self.assertEqual(protokoll.positionen[0]["zustand_rueckgabe"], 4)
        self.assertEqual(protokoll.positionen[0]["bemerkung"], "Riss")
        for gerat in (self.g1, self.g2):
            gerat.refresh_from_db()
            self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)
            self.assertIsNone(gerat.person)
        self.g3.refresh_from_db()
        self.assertEqual(self.g3.status, Gerat.STATUS_IN_REPARATUR)
        self.assertIsNone(self.g3.person)

    def test_nur_die_gewaehlten(self):
        self._vorbereitet()
        self.client.post(f"/personen/{self.anna.pk}/offboarding/zuruecknehmen/", {"aktion": "auswahl", "auswahl": [self.g2.inventarnummer]})
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual([p["inventarnummer"] for p in protokoll.positionen], [self.g2.inventarnummer])
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.person, self.anna)

    def test_get_fuehrt_nichts_aus(self):
        self._vorbereitet()
        self.assertEqual(self.client.get(f"/personen/{self.anna.pk}/offboarding/zuruecknehmen/").status_code, 405)
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.person, self.anna)

    def test_ohne_wahl_passiert_nichts(self):
        self._vorbereitet()
        self.client.post(f"/personen/{self.anna.pk}/offboarding/zuruecknehmen/", {"aktion": "auswahl"})
        self.assertFalse(Protokoll.objects.filter(art=Protokoll.ART_RUECKNAHME).exists())


class ReparaturTests(Grundlage):
    """F-42."""

    def _start(self, gerat):
        services.gerat_in_reparatur_geschickt(gerat, dienstleister="DL-Firma", vorgangsnummer="VG-4711", notiz="kaputt", ausgefuehrt_von=self.admin)

    def test_knopf_auch_bei_in_benutzung(self):
        gerat = self._ausgegeben(self._gerat())
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-reparatur"')

    def test_angaben_auf_der_detailseite(self):
        gerat = self._ausgegeben(self._gerat())
        self._start(gerat)
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(antwort, "DL-Firma")
        self.assertContains(antwort, "VG-4711")
        self.assertContains(antwort, "Bisherige Zuordnung: Anna Becker")

    def test_lagergeraet_zurueck_an_bisherige_zuordnung_bleibt_auf_lager(self):
        gerat = self._gerat()
        self._start(gerat)
        services.gerat_reparatur_fertig(gerat, zustand=1, ziel="zuordnung", ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(gerat.ort, self.lager)

    def test_person_zurueck_an_bisherige_zuordnung(self):
        gerat = self._ausgegeben(self._gerat())
        self._start(gerat)
        services.gerat_reparatur_fertig(gerat, zustand=1, ziel="zuordnung", ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertEqual(gerat.person, self.anna)

    def test_ins_lager_mit_lagerort(self):
        gerat = self._ausgegeben(self._gerat())
        self._start(gerat)
        self.client.post(f"/geraete/{gerat.inventarnummer}/reparatur/fertig/", {"zustand": 1, "ziel": "lager", "lager_ort": self.lager2.pk})
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)
        self.assertEqual(gerat.ort, self.lager2)
        self.assertIsNone(gerat.person)


class AusmusterungTests(Grundlage):
    """F-55 bis F-58, Kapitel 4."""

    def _daten(self, **werte):
        daten = {"grund": "defekt", "datum": "2026-11-05", "disposition": "Entsorger GmbH"}
        daten.update(werte)
        return daten

    def test_aus_in_benutzung_nur_verloren_oder_gestohlen(self):
        gerat = self._ausgegeben(self._gerat())
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="X", loeschung_art="nist", loeschung_nachweis="N")
        services.ausmustern(gerat, grund="verloren", datum=date(2026, 1, 1), disposition="unbekannt", bestaetigt_gemeldt=True)
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_dialog_bietet_nur_erlaubte_gruende(self):
        gerat = self._ausgegeben(self._gerat())
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/ausmustern/")
        self.assertContains(antwort, 'value="verloren"')
        self.assertNotContains(antwort, 'value="defekt"')

    def test_knoepfe_je_status(self):
        lager = self._gerat("K-1")
        benutzt = self._ausgegeben(self._gerat("K-2"))
        reparatur = self._gerat("K-3")
        services.gerat_in_reparatur_geschickt(reparatur, dienstleister="X", vorgangsnummer="1", notiz="n")
        for gerat in (lager, benutzt, reparatur):
            self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-ausmustern"')

    def test_aus_reparatur_erlaubt(self):
        gerat = self._gerat(kategorie=self.maus, seriennummer="")
        services.gerat_in_reparatur_geschickt(gerat, dienstleister="X", vorgangsnummer="1", notiz="n")
        services.ausmustern(gerat, grund="defekt", datum=date(2026, 1, 1), disposition="Entsorger")
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUSGEMUSTERT)

    def test_verbleib_ist_immer_pflicht(self):
        gerat = self._gerat()
        antwort = self.client.post(f"/geraete/{gerat.inventarnummer}/ausmustern/", self._daten(grund="verloren", disposition="", bestaetigt_gemeldt="on"))
        self.assertEqual(antwort.status_code, 200)
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_nachweis_als_datei(self):
        gerat = self._gerat()
        self.client.post(f"/geraete/{gerat.inventarnummer}/ausmustern/", self._daten(
            loeschung_art="zerstoert",
            loeschung_datei=SimpleUploadedFile("zert.pdf", b"%PDF-1.7\nZertifikat", content_type="application/pdf"),
        ))
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUSGEMUSTERT)
        vorgang = gerat.vorgaenge.get(typ=Vorgang.TYP_AUSMUSTERUNG)
        self.assertEqual(vorgang.loeschung_art, "zerstoert")
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/nachweis/{vorgang.pk}/")
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertEqual(antwort.content, b"%PDF-1.7\nZertifikat")

    def test_nachweis_mit_falschem_inhalt_wird_abgelehnt(self):
        gerat = self._gerat()
        self.client.post(f"/geraete/{gerat.inventarnummer}/ausmustern/", self._daten(
            loeschung_art="zerstoert",
            loeschung_datei=SimpleUploadedFile("zert.pdf", b"<html>", content_type="application/pdf"),
        ))
        gerat.refresh_from_db()
        self.assertEqual(gerat.status, Gerat.STATUS_AUF_LAGER)

    def test_grund_und_verbleib_auf_der_detailseite(self):
        gerat = self._gerat()
        self.client.post(f"/geraete/{gerat.inventarnummer}/ausmustern/", self._daten(loeschung_art="nist", loeschung_nachweis="Zert-777"))
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(antwort, "Entsorger GmbH")
        self.assertContains(antwort, "defekt")
        self.assertContains(antwort, "Zert-777")
        self.assertContains(antwort, "Gelöscht durch die IT nach NIST SP 800-88")

    def test_verlust_schliesst_die_leihe(self):
        gerat = self._ausgegeben(self._gerat())
        leihe = Leihe.objects.create(person=self.anna, gerat=gerat, kat=self.notebook, status=Leihe.STATUS_AUSGEGEBEN)
        services.ausmustern(gerat, grund="gestohlen", datum=date(2026, 1, 1), disposition="unbekannt", bestaetigt_gemeldt=True)
        leihe.refresh_from_db()
        self.assertEqual(leihe.status, Leihe.STATUS_ZURUECKGEGEBEN)

    def test_verlust_verlangt_die_bestaetigung(self):
        gerat = self._ausgegeben(self._gerat())
        with self.assertRaises(services.GeratFehler):
            services.ausmustern(gerat, grund="verloren", datum=date(2026, 1, 1), disposition="unbekannt")
