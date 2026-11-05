"""Befunde der Nachprüfung (Stand c7b1ba7), jeder mit einem Test (N-10)."""
from __future__ import annotations

import re
from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from konten import zeit
from stammdaten.models import Checklistenpunkt, Einstellungen, Ort

from . import import_parser, kennzahlen, protokoll as protokoll_services, services
from .models import Gerat, GeratAnhang, Protokoll, Vorgang
from .tests_pruefung2 import Grundlage, PW


def _signiert(testfall, *geraete):
    protokoll = testfall._entwurf(*geraete)
    testfall._checkliste(protokoll)
    testfall.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": PW})
    protokoll.refresh_from_db()
    return protokoll


class KorrekturTests(Grundlage):
    """F-135, F-141: Eine neue Fassung nimmt alle Geräte und die Post-Adresse mit."""

    def test_alle_geraete_bleiben_dabei(self):
        a, b = self._gerat("A-1"), self._gerat("B-1")
        alt = _signiert(self, a, b)
        neu, ok = services.protokoll_korrigieren(alt, self.admin)
        self.assertTrue(ok)
        self.assertEqual({g.pk for g in neu.geraete_liste()}, {a.pk, b.pk})
        self.assertEqual(services._ausgabeprotokoll_fuer(b, self.anna), neu)
        self.assertIn(neu, b.alle_protokolle())

    def test_post_adresse_bleibt(self):
        alt = _signiert(self, self._gerat("A-2"))
        alt.gegenzeichnung_empfaenger = "privat@example.org"
        alt.save(update_fields=["gegenzeichnung_empfaenger"])
        neu, _ok = services.protokoll_korrigieren(alt, self.admin)
        self.assertEqual(neu.gegenzeichnung_empfaenger, "privat@example.org")


class ChecklisteTests(Grundlage):
    """F-132, F-133, F-135: Bemerkung bleibt, Punkte gehören zum Protokoll."""

    def _speichern(self, **punkte):
        return self.client.post("/einstellungen/checklisten/", punkte)

    def test_bemerkung_steht_auf_der_seite_und_bleibt(self):
        protokoll = self._entwurf(self._gerat("C-1"))
        adresse = f"/protokolle/{protokoll.nr}/checkliste/"
        self.client.post(adresse, {"checkliste.vpn": "ausgegeben", "checkliste.vpn.bemerkung": "Token 77"})
        seite = self.client.get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(seite, 'value="Token 77"')
        self.client.post(adresse, {"checkliste.vpn": "ausgegeben", "checkliste.vpn.bemerkung": "Token 77"})
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.checkliste_bemerkung["vpn"], "Token 77")

    def test_neuer_punkt_gilt_nur_fuer_neue_protokolle(self):
        protokoll = self._entwurf(self._gerat("C-2"))
        self._checkliste(protokoll)
        self.client.post("/einstellungen/checklisten/", {"liste": "zugaenge", "neu": "Diensthandy"})
        protokoll = Protokoll.objects.get(pk=protokoll.pk)
        self.assertEqual(protokoll.checkliste_unbeantwortet(), [])
        self.assertTrue(protokoll.pdf_baubar)
        self.assertNotContains(self.client.get(f"/protokolle/{protokoll.nr}/"), "Diensthandy")
        spaeter = self._entwurf(self._gerat("C-3"))
        self.assertIn("Diensthandy", spaeter.checkliste_unbeantwortet())

    def test_signiertes_protokoll_zeigt_den_alten_wortlaut(self):
        protokoll = _signiert(self, self._gerat("C-4"))
        Checklistenpunkt.objects.filter(liste="zugaenge", schluessel="vpn").update(text="VPN NEU-TEXT")
        seite = self.client.get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(seite, "VPN-Zugang")
        self.assertNotContains(seite, "VPN NEU-TEXT")

    def test_korrektur_behaelt_die_liste(self):
        alt = _signiert(self, self._gerat("C-5"))
        Checklistenpunkt.objects.create(liste="zugaenge", schluessel="spaet", text="Später", reihenfolge=999)
        neu, _ok = services.protokoll_korrigieren(alt, self.admin)
        self.assertEqual(neu.checkliste_unbeantwortet(), [])

    def test_zu_grosse_reihenfolge_und_zu_langer_text(self):
        self.client.get("/einstellungen/checklisten/")
        vpn = Checklistenpunkt.objects.get(liste="zugaenge", schluessel="vpn")
        antwort = self.client.post("/einstellungen/checklisten/", {
            "liste": "zugaenge", f"text-{vpn.pk}": vpn.text, f"reihenfolge-{vpn.pk}": "99999999999999999999",
        }, follow=True)
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, "bis 999999")
        antwort = self.client.post("/einstellungen/checklisten/", {
            "liste": "zugaenge", f"text-{vpn.pk}": "x" * 201, f"reihenfolge-{vpn.pk}": "1",
        }, follow=True)
        self.assertContains(antwort, "höchstens 200 Zeichen")
        vpn.refresh_from_db()
        self.assertEqual(vpn.text, "VPN-Zugang, Zertifikat oder Schlüssel")

    def test_ein_punkt_bleibt_aktiv(self):
        self.client.get("/einstellungen/checklisten/")
        daten = {"liste": "zugaenge"}
        for p in Checklistenpunkt.objects.filter(liste="zugaenge"):
            daten[f"text-{p.pk}"] = p.text
            daten[f"reihenfolge-{p.pk}"] = p.reihenfolge
        antwort = self.client.post("/einstellungen/checklisten/", daten, follow=True)
        self.assertContains(antwort, "Mindestens ein Punkt bleibt aktiv.")
        self.assertTrue(Checklistenpunkt.objects.filter(liste="zugaenge", aktiv=True).exists())


class PruefpunktDatumTests(Grundlage):
    """F-133: Datum der Prüfpunkte."""

    def _ruecknahme(self):
        gerat = self._gerat("D-1")
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin, unterschrift="papier")
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=2, ausgefuehrt_von=self.admin, unterschrift="tool")
        return Protokoll.objects.filter(art=Protokoll.ART_RUECKNAHME).latest("id")

    def test_freitext_wird_abgelehnt(self):
        protokoll = self._ruecknahme()
        with self.assertRaises(services.GeratFehler):
            protokoll_services.offboarding_beantworten(
                protokoll, {"vpn_zertifikate": "erledigt", "vpn_zertifikate.datum": "kein datum"}, self.admin,
            )

    def test_iso_wird_umgeschrieben(self):
        protokoll = self._ruecknahme()
        protokoll_services.offboarding_beantworten(
            protokoll, {"vpn_zertifikate": "erledigt", "vpn_zertifikate.datum": "2026-11-03"}, self.admin,
        )
        protokoll.refresh_from_db()
        self.assertEqual(protokoll.offboarding["vpn_zertifikate"]["datum"], "03.11.2026")


class ReservierungAufhebenTests(Grundlage):
    """F-20: Nach dem Aufheben ist das Gerät wieder frei, und es heißt nicht „Leihanfrage“."""

    def _genehmigt(self, gerat, von, bis):
        from .models import Leihe
        leihe = Leihe.objects.create(person=self.anna, kat=self.kat, beginn=von, ende=bis, rueckgabe_bis=bis,
                                     status=Leihe.STATUS_ANGEFRAGT, zweck="Messe")
        return services.leihe_genehmigen(leihe, gerat, self.admin) or leihe

    def test_geraet_ist_danach_frei(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = self._genehmigt(gerat, heute, heute + timedelta(days=5))
        adresse = f"/verleih/{leihe.id}/ablehnen/"
        seite = self.client.get(adresse)
        self.assertContains(seite, "Reservierung aufheben")
        self.assertNotContains(seite, "Leihanfrage ablehnen")
        mail.outbox.clear()
        self.client.post(adresse, {"begruendung": "Gerät wird gebraucht"})
        gerat = Gerat.objects.get(pk=gerat.pk)
        self.assertFalse(gerat.reserviert)
        self.assertFalse(gerat.reserviert_aktiv)
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/"), 'data-test="aktion-ausgabe"')
        self.assertEqual(mail.outbox[0].subject, "Reservierung aufgehoben")
        self.assertIn("Reservierung aufgehoben.", [v.notiz for v in Vorgang.objects.filter(gerat=gerat)])

    def test_zweite_reservierung_bleibt(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        erste = self._genehmigt(gerat, heute, heute + timedelta(days=2))
        self._genehmigt(gerat, heute + timedelta(days=5), heute + timedelta(days=7))
        services.leihe_ablehnen(erste, "Geht nicht", self.admin)
        gerat = Gerat.objects.get(pk=gerat.pk)
        self.assertTrue(gerat.reserviert)
        self.assertEqual(gerat.reserviert_bis, heute + timedelta(days=7))

    def test_verleih_dialog_nennt_die_reservierung(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        self._genehmigt(gerat, heute, heute + timedelta(days=5))
        self.assertContains(self.client.get(f"/geraete/{gerat.inventarnummer}/verleih/"), 'data-test="hinweis-reserviert"')

    def test_reparatur_am_reservierten_geraet_nennt_die_leihe(self):
        gerat = self._gerat(leihpool=True)
        heute = zeit.jetzt_wie_im_entwicklungsmodus().date()
        leihe = self._genehmigt(gerat, heute + timedelta(days=9), heute + timedelta(days=12))
        antwort = self.client.post(f"/geraete/{gerat.inventarnummer}/reparatur/start/", {
            "dienstleister": "Fix GmbH", "vorgangsnummer": "R-1", "notiz": "defekt",
        }, follow=True)
        self.assertContains(antwort, f"für die Leihe {leihe.nr}")


class MeldungenTests(Grundlage):
    """F-96, F-35: Die Meldung sagt nur, was geschieht."""

    def _verliehen(self):
        gerat = self._gerat(leihpool=True)
        bis = zeit.jetzt_wie_im_entwicklungsmodus().date() + timedelta(days=5)
        self.client.post(f"/geraete/{gerat.inventarnummer}/verleih/", {
            "person": self.anna.pk, "rueckgabe_bis": bis.isoformat(), "zweck": "Messe", "unterschrift": "papier",
            "zustand": 2, "zubehoer_komplett": "ja",
        })
        from .models import Leihe
        leihe = Leihe.objects.get(gerat=gerat)
        leihe.verlaengerung_bis = bis + timedelta(days=3)
        leihe.save(update_fields=["verlaengerung_bis"])
        return leihe

    def test_verlaengerung_abgelehnt_ohne_mail(self):
        leihe = self._verliehen()
        Einstellungen.objects.filter(pk=Einstellungen.aktuelles().pk).update(mail_verleih_ablehnung=False)
        antwort = self.client.post(f"/verleih/{leihe.id}/verlaengern/", {"aktion": "ablehnen"}, follow=True)
        self.assertContains(antwort, "Eine Mail geht nicht hinaus.")
        self.assertNotContains(antwort, "unterwegs")
        self.assertIn(f"Verlängerung der Leihe {leihe.nr} abgelehnt.",
                      [v.notiz for v in Vorgang.objects.filter(gerat=leihe.gerat)])


class VersandOffenTests(Grundlage):
    """F-139: Die IT sieht es in der Übersicht."""

    def test_zeile_und_export(self):
        protokoll = self._entwurf(self._gerat("V-1"))
        self.assertNotIn("versand-offen", [l["data_id"] for l in kennzahlen.arbeitslisten()])
        Protokoll.objects.filter(pk=protokoll.pk).update(pdf_versand_offen=True)
        self.assertContains(self.client.get("/"), 'data-id="versand-offen"')
        liste = {l["data_id"]: l for l in kennzahlen.arbeitslisten()}["versand-offen"]
        self.assertEqual(liste["zeilen"][0]["nr"], protokoll.nr)
        antwort = self.client.get("/exporte/?liste=versand-offen&format=csv")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn(protokoll.nr, antwort.content.decode("utf-8-sig"))


class ImportLagerTests(Grundlage):
    """F-85: Der Lagerort der Startdaten heißt LAGER, nicht LAGER-EG."""

    def test_lagerort_aus_den_startdaten(self):
        self.assertEqual(self.lager.kennung, "LAGER")
        self.assertEqual(import_parser._lagerort_finden(), self.lager)

    def test_ohne_lager_kein_ort(self):
        Ort.objects.all().delete()
        self.assertIsNone(import_parser._lagerort_finden())

    def test_latin1_meldung_ohne_python_text(self):
        with self.assertRaises(import_parser.ImportFehler) as fehler:
            import_parser.lade_csv("liste.csv", "Hersteller;Modell\nMüller;A\n".encode("latin-1"))
        self.assertNotIn("codec", str(fehler.exception))


class KleinigkeitenTests(Grundlage):
    def test_datum_im_dialog_ausmustern(self):
        gerat = self._gerat("K-1")
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/ausmustern/").content.decode()
        marke = re.search(r'<input[^>]*data-test="ausmusterung-datum"[^>]*>', seite).group(0)
        self.assertRegex(marke, r'value="\d{4}-\d{2}-\d{2}"')

    def test_knopf_signieren_ist_primaer(self):
        protokoll = _signiert(self, self._gerat("K-2"))
        seite = self.client.get(f"/signieren/{protokoll.gegenzeichnung_token}/")
        self.assertContains(seite, 'class="btn primary" type="submit" data-test="signieren"')

    def test_reparatur_historie_in_worten(self):
        gerat = self._gerat("K-3")
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin, unterschrift="papier")
        gerat = Gerat.objects.get(pk=gerat.pk)
        services.gerat_in_reparatur_geschickt(
            gerat, dienstleister="Fix", vorgangsnummer="R", notiz="", ausgefuehrt_von=self.admin,
        )
        gerat = Gerat.objects.get(pk=gerat.pk)
        services.gerat_reparatur_fertig(gerat, zustand=2, ziel="zuordnung", ausgefuehrt_von=self.admin)
        notizen = [v.notiz for v in Vorgang.objects.filter(gerat=gerat)]
        self.assertIn("Zustand: 2, Ziel: bisherige Zuordnung", notizen)

    def test_nachtrag_heisst_nachtrag(self):
        gerat = self._gerat("K-4")
        services.gerat_in_reparatur_geschickt(
            gerat, dienstleister="Fix", vorgangsnummer="R", notiz="", ausgefuehrt_von=self.admin,
        )
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/reparatur/start/")
        self.assertContains(seite, "Angaben nachtragen")
        self.assertNotContains(seite, "Reparatur starten")

    def test_anhang_meldung_und_dateiname(self):
        gerat = self._gerat("K-5")
        antwort = self.client.post(f"/geraete/{gerat.inventarnummer}/anhang/", {
            "datei": SimpleUploadedFile("text.pdf", b"kein pdf"),
        }, follow=True)
        self.assertContains(antwort, "Anhang nicht erlaubt")
        self.assertNotContains(antwort, "Nachweis")
        self.client.post(f"/geraete/{gerat.inventarnummer}/anhang/", {
            "datei": SimpleUploadedFile("Rechnung März.pdf", b"%PDF-1.4 inhalt"),
        })
        anhang = GeratAnhang.objects.filter(gerat=gerat).first()
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/{anhang.pk}/")
        self.assertIn("Rechnung", antwort["Content-Disposition"])

    def test_anhang_dialog_am_ausgemusterten_geraet(self):
        gerat = self._gerat("K-6")
        Gerat.objects.filter(pk=gerat.pk).update(status=Gerat.STATUS_AUSGEMUSTERT)
        antwort = self.client.get(f"/geraete/{gerat.inventarnummer}/anhang/")
        self.assertEqual(antwort.status_code, 302)

    def test_sammeldialog_behaelt_die_eingaben(self):
        a, b = self._gerat("K-7"), self._gerat("K-8")
        antwort = self.client.post("/geraete/sammelausgabe/", {
            "auswahl": [a.inventarnummer, b.inventarnummer],
            f"zustand-{a.inventarnummer}": "4",
            f"zubehoer-{a.inventarnummer}": "nein",
            f"anmerkung-{a.inventarnummer}": "Kratzer Deckel",
            "unterschrift": "tool",
        })
        self.assertEqual(antwort.status_code, 200)
        seite = antwort.content.decode()
        self.assertIn('value="Kratzer Deckel"', seite)
        self.assertIn('<option value="nein" selected>', seite)
        self.assertRegex(seite, r'<option value="4" selected>')

    def test_offener_entwurf_zeigt_hinweis_statt_knoepfen(self):
        gerat = self._gerat("K-9")
        protokoll = self._entwurf(gerat)
        seite = self.client.get(f"/geraete/{gerat.inventarnummer}/")
        self.assertContains(seite, 'data-test="hinweis-entwurf"')
        self.assertContains(seite, protokoll.nr)
        self.assertNotContains(seite, 'data-test="aktion-ausgabe"')
        self.assertNotContains(seite, 'data-test="aktion-ausmustern"')

    def test_historie_grossgeschrieben(self):
        gerat = self._gerat("K-10")
        services.gerat_bearbeiten(gerat, kaufdatum_nicht_ermittelbar=True, erzeugt_von=self.admin)
        vorgang = Vorgang.objects.filter(gerat=gerat, aenderung_feld="kaufdatum_nicht_ermittelbar").first()
        self.assertTrue(vorgang.aenderung_anzeige.startswith("Kaufdatum nicht ermittelbar"))
