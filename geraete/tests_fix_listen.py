"""Tests zu den Prüfbefunden in Listen, Import, Etiketten und Übersicht.

F-41, F-44, F-58, F-70 bis F-74, F-80 bis F-89, F-100 bis F-105. Die Eckwerte der
Testdatei prüft ``geraete.tests_import``; hier stehen die Abweichungen davon.
"""
from __future__ import annotations

import io
import os
import re
from datetime import date, timedelta
from urllib.parse import urlencode

from django.test import Client, TestCase
from openpyxl import Workbook, load_workbook

from konten.management.commands.beispieldaten import KATEGORIEN
from konten.models import Konto
from stammdaten.models import (Ausstattungsprofil, Einstellungen, Kategorie, Ort,
                               Person, Zaehlerstand)

from . import etiketten, import_parser, kennzahlen, services
from .models import Gerat, GeratKonflikt, Leihe, Vorgang

VORLAGE_PFAD = os.path.join(
    os.path.dirname(__file__), "..", "docs", "vorlagen", "bestandsliste_anonymisiert.xlsx")


def _konto(name: str, rolle: str, person: Person | None = None) -> Konto:
    konto = Konto(email=f"{name}@beispiel.test", rolle=rolle, person=person)
    konto.set_password("test-passwort-123")
    konto.save()
    return konto


class Grund(TestCase):
    """Stammdaten wie in den Beispieldaten, soweit diese Tests sie brauchen."""

    @classmethod
    def setUpTestData(cls):
        for name, datentraeger, pflicht in KATEGORIEN:
            Kategorie.objects.create(name=name, hat_datentraeger=datentraeger, seriennummer_pflicht=pflicht)
        cls.notebook = Kategorie.objects.get(name="Notebook")
        cls.monitor = Kategorie.objects.get(name="Monitor")
        cls.headset = Kategorie.objects.get(name="Headset")
        cls.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER-EG", name="IT-Lager")
        cls.wp1 = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WMC-WP-01")
        cls.wp5 = Ort.objects.create(typ=Ort.TYP_ARBEITSPLATZ, kennung="WMC-WP-05")
        cls.studio = Ort.objects.create(typ=Ort.TYP_RAUM, kennung="STUDIO-TECHNIK")
        cls.anna = Person.objects.create(vorname="Anna", nachname="Becker", email="anna.becker@beispiel.test")
        cls.felix = Person.objects.create(vorname="Felix", nachname="Hoffmann", email="felix.hoffmann@beispiel.test")
        cls.admin = _konto("it-admin", Konto.ROLLE_ADMIN)
        cls.leser = _konto("gf", Konto.ROLLE_LESER)
        cls.mitarbeiter = _konto("anna.becker", Konto.ROLLE_MITARBEITER, cls.anna)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def _gerat(self, **werte) -> Gerat:
        werte.setdefault("kategorie", self.notebook)
        werte.setdefault("hersteller", "Lenovo")
        werte.setdefault("modell", "T14")
        return services.gerat_anlegen(**werte)

    def _ausgemustert(self) -> Gerat:
        g = self._gerat(seriennummer="ALT-1", geraetename="ALT-NAME")
        Gerat.objects.filter(pk=g.pk).update(status=Gerat.STATUS_AUSGEMUSTERT)
        g.refresh_from_db()
        return g

    def _zeilen(self, antwort) -> list[str]:
        return re.findall(r'data-test="zeile" data-id="([^"]+)"', antwort.content.decode())


class GeraetelisteTests(Grund):
    def test_voller_name_findet(self):
        g = self._gerat(person=self.anna)
        self._gerat(person=self.felix)
        for suche in ("Anna Becker", "Becker Anna", "anna becker", "Becker"):
            with self.subTest(suche=suche):
                self.assertEqual(self._zeilen(self.client.get("/geraete/", {"q": suche})),
                                 [g.inventarnummer])

    def test_kategorie_ueber_den_namen(self):
        m = self._gerat(kategorie=self.monitor)
        self._gerat()
        antwort = self.client.get("/geraete/", {"kategorie": "Monitor"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(self._zeilen(antwort), [m.inventarnummer])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"kategorie": self.monitor.pk})),
                         [m.inventarnummer])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"kategorie": "Gibt-es-nicht"})), [])

    def test_unsinniger_filter_antwortet_ohne_fehler(self):
        self.assertEqual(self.client.get("/geraete/", {"person": "abc"}).status_code, 200)
        self.assertEqual(self.client.get("/geraete/", {"ort": "abc"}).status_code, 200)

    def test_archiv(self):
        aktiv = self._gerat()
        alt = self._ausgemustert()
        self.assertEqual(self._zeilen(self.client.get("/geraete/")), [aktiv.inventarnummer])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"archiv": "1"})), [alt.inventarnummer])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"status": "ausgemustert"})), [])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"q": "ALT-NAME"})), [])
        self.assertEqual(self._zeilen(self.client.get("/geraete/", {"q": "ALT-NAME", "archiv": "1"})),
                         [alt.inventarnummer])
        csv_text = self.client.get("/geraete/", {"archiv": "1", "format": "csv"}).content.decode()
        self.assertEqual(len(csv_text.strip().splitlines()), 2)
        self.assertIn(alt.inventarnummer, csv_text)

    def test_ausgemustert_notiz_und_pruefen_abgelehnt(self):
        alt = self._ausgemustert()
        self.client.post(f"/geraete/{alt.inventarnummer}/notiz/", {"notiz": "NACH-ARCHIV"})
        self.client.post(f"/geraete/{alt.inventarnummer}/pruefen/")
        alt.refresh_from_db()
        self.assertEqual(alt.notiz, "")
        self.assertIsNone(alt.zuletzt_geprueft_am)

    def test_kopfsuche_nicht_beim_mitarbeiter(self):
        self.client.force_login(self.mitarbeiter)
        self.assertNotContains(self.client.get("/meine-geraete/"), 'data-test="suche"')
        self.client.force_login(self.leser)
        self.assertContains(self.client.get("/geraete/"), 'data-test="suche"')

    def test_export_mit_geraetename_und_seriennummer(self):
        self._gerat(seriennummer="SN-77", geraetename="WMC-NB-77")
        zeilen = self.client.get("/geraete/", {"format": "csv"}).content.decode("utf-8-sig").splitlines()
        self.assertIn("Gerätename", zeilen[0])
        self.assertIn("Seriennummer", zeilen[0])
        self.assertIn("WMC-NB-77", zeilen[1])
        self.assertIn("SN-77", zeilen[1])

    def test_leser_sieht_keine_kaestchen(self):
        self._gerat()
        self.client.force_login(self.leser)
        antwort = self.client.get("/geraete/")
        self.assertNotContains(antwort, 'data-test="auswahl"')
        self.assertNotContains(antwort, 'data-test="etiketten-drucken"')
        self.assertEqual(self.client.post("/etiketten/auswahl/", {"auswahl": "WMC-00001"}).status_code, 403)

    def test_luecken_in_worten_je_geraet(self):
        self._gerat()
        antwort = self.client.get("/geraete/", {"unvollstaendig": "1"})
        self.assertContains(antwort, 'data-test="fehlende-felder"')
        self.assertContains(antwort, "fehlt: Seriennummer, Kaufdatum")
        self.assertNotContains(antwort, "zustand-ungeprueft")


class UmzugTests(Grund):
    def _in_benutzung(self) -> Gerat:
        g = self._gerat()
        services.gerat_ausgeben(g, self.anna, ausgefuehrt_von=self.admin)
        g.refresh_from_db()
        return g

    def test_ziel_ist_kein_lager(self):
        g = self._in_benutzung()
        antwort = self.client.get(f"/geraete/{g.inventarnummer}/umziehen/")
        self.assertNotContains(antwort, "LAGER-EG")
        self.assertContains(antwort, "STUDIO-TECHNIK")
        self.client.post(f"/geraete/{g.inventarnummer}/umziehen/", {"ziel_ort": self.lager.pk})
        g.refresh_from_db()
        self.assertNotEqual(g.ort, self.lager)

    def test_auf_lager_kennt_keinen_umzug(self):
        g = self._gerat(ort=self.lager)
        self.assertNotContains(self.client.get(f"/geraete/{g.inventarnummer}/"), 'data-test="aktion-umzug"')
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/umziehen/", {"ziel_ort": self.wp1.pk})
        self.assertEqual(antwort.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.ort, self.lager)
        self.assertEqual(g.status, Gerat.STATUS_AUF_LAGER)

    def test_umzug_behaelt_die_person(self):
        g = self._in_benutzung()
        self.client.post(f"/geraete/{g.inventarnummer}/umziehen/", {"ziel_ort": self.wp5.pk})
        g.refresh_from_db()
        self.assertEqual((g.ort, g.person, g.status), (self.wp5, self.anna, Gerat.STATUS_IN_BENUTZUNG))

    def test_reparatur_auch_aus_in_benutzung(self):
        g = self._in_benutzung()
        self.assertContains(self.client.get(f"/geraete/{g.inventarnummer}/"), 'data-test="aktion-reparatur"')


class EtikettenTests(Grund):
    def _seiten(self, pdf: bytes) -> int:
        from pyhanko.pdf_utils.reader import PdfFileReader
        return int(PdfFileReader(io.BytesIO(pdf)).root["/Pages"]["/Count"])

    def _nummern(self, n: int) -> list[str]:
        return [self._gerat().inventarnummer for _ in range(n)]

    def test_auswahl_druckt_jedes_kaestchen(self):
        nummern = self._nummern(3)
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": nummern, "startposition": "1"})
        self.assertEqual(antwort["Content-Type"], "application/pdf")
        self.assertIn("etiketten-bogen-3.pdf", antwort["Content-Disposition"])

    def test_mehr_als_ein_bogen(self):
        geraete = [self._gerat() for _ in range(30)]
        seiten = etiketten.bogen_seiten(geraete, 1, etiketten.FORMATE["a4"])
        self.assertEqual(len(seiten), 2)
        self.assertEqual(sum(1 for s in seiten for f in s if f), 30)
        self.assertEqual(self._seiten(etiketten.bogen_pdf(geraete, 1)), 2)

    def test_start_am_bogenende_geht_kein_etikett_verloren(self):
        geraete = [self._gerat() for _ in range(3)]
        seiten = etiketten.bogen_seiten(geraete, 23, etiketten.FORMATE["a4"])
        self.assertEqual(len(seiten), 2)
        self.assertEqual([f for f in seiten[0] if f], geraete[:2])
        self.assertIs(seiten[1][0], geraete[2])

    def test_falsche_startposition_wird_gemeldet(self):
        nummern = self._nummern(1)
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": nummern, "startposition": "99"}, follow=True)
        self.assertContains(antwort, "Die Startposition muss zwischen 1 und 24 liegen.")
        self._gerat(ort=self.lager)
        antwort = self.client.get("/etiketten/", {"ort": "LAGER-EG", "startposition": "0"}, follow=True)
        self.assertContains(antwort, "Die Startposition muss zwischen 1 und 24 liegen.")

    def test_format_aus_den_einstellungen(self):
        geraete = [self._gerat() for _ in range(11)]
        self.assertEqual(etiketten.format_aus_einstellungen().pro_bogen, 24)
        Einstellungen.objects.update_or_create(pk=1, defaults={"etikettenformat": "a5"})
        fmt = etiketten.format_aus_einstellungen()
        self.assertEqual(fmt.pro_bogen, 10)
        self.assertEqual(self._seiten(etiketten.bogen_pdf(geraete)), 2)
        self.assertContains(self.client.get("/etiketten/"), 'max="10"')

    def test_qr_im_browser_skaliert(self):
        svg = etiketten.qr_svg(self._gerat())
        self.assertIn("viewBox", svg)
        self.assertNotIn(" width=", svg.split(">")[0])

    def test_modell_wird_maskiert_und_gekuerzt(self):
        g = self._gerat(modell='Modell <b>A&B</b> "Q" mit einem sehr langen Namen')
        text = etiketten.etikett_html(g)
        self.assertNotIn("<b>A", text)
        self.assertIn("&lt;b&gt;A&amp;B", text)
        self.assertIn("…", text)

    def test_vorschau_zeigt_die_bogen(self):
        nummern = self._nummern(25)
        antwort = self.client.post("/etiketten/auswahl/", {"auswahl": nummern, "vorschau": "1"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.content.decode().count('data-test="bogen"'), 2)
        self.assertEqual(antwort.content.decode().count('data-test="etikett"'), 25)
        self._gerat(ort=self.lager)
        antwort = self.client.get("/etiketten/", {"ort": "LAGER-EG", "vorschau": "1"})
        self.assertContains(antwort, 'data-test="bogen"')

    def test_ort_nach_bisheriger_kennung(self):
        c = self._gerat(ort=self.lager, geraetename="WMC-C")
        ohne = self._gerat(ort=self.lager)
        a = self._gerat(ort=self.lager, geraetename="WMC-A", kategorie=self.monitor)
        self.assertEqual(etiketten.etiketten_fuer_ort(self.lager), [a, c, ohne])

    def test_leser_kein_etikett(self):
        g = self._gerat()
        self.client.force_login(self.leser)
        self.assertNotContains(self.client.get(f"/geraete/{g.inventarnummer}/"), 'data-test="aktion-etikett"')
        self.assertEqual(self.client.get(f"/geraete/{g.inventarnummer}/etikett/").status_code, 403)

    def test_anmeldung_fuehrt_zum_geraet(self):
        g = self._gerat()
        gast = Client()
        ziel = f"/g/{g.inventarnummer}"
        antwort = gast.get(ziel)
        self.assertEqual(antwort["Location"], "/anmelden/?" + urlencode({"next": ziel}))
        seite = gast.get(antwort["Location"])
        self.assertContains(seite, f'name="next" value="{ziel}"')
        antwort = gast.post("/anmelden/", {"email": self.admin.email, "passwort": "test-passwort-123", "next": ziel})
        self.assertEqual(antwort["Location"], ziel)


class Werkzeug(Grund):
    """Import wie im Browser: Datei, Blatt, Spalten, Werte, Vorschau, Speichern."""

    def _csv(self, text: str, name: str = "liste.csv"):
        datei = io.BytesIO(text.encode("utf-8"))
        datei.name = name
        return self.client.post("/import/datei/", {"datei": datei})

    def _xlsx(self, blatt: str = "", kopfzeile: str = ""):
        with open(VORLAGE_PFAD, "rb") as datei:
            daten = {"datei": datei}
            if blatt:
                daten["blatt"] = blatt
            if kopfzeile:
                daten["kopfzeile"] = kopfzeile
            return self.client.post("/import/datei/", daten)

    def _spalten_wie_vorgeschlagen(self):
        seite = self.client.get("/import/").content.decode()
        daten = {}
        for name, block in re.findall(r'<select name="(ziel_[^"]+)"[^>]*>(.*?)</select>', seite, re.S):
            gewaehlt = re.search(r'<option value="([^"]*)" selected', block)
            daten[_unescape(name)] = _unescape(gewaehlt.group(1)) if gewaehlt else "ignorieren"
        return daten

    def _weiter_mit_vorschlaegen(self, **ersetzt):
        self.assertEqual(self.client.post("/import/spalten/", self._spalten_wie_vorgeschlagen()).status_code, 302)
        seite = self.client.get("/import/").content.decode()
        daten = {}
        for name, block in re.findall(r'<select (?:id="[^"]*" )?name="((?:wert_zu_kategorie_|kategorie_standard)[^"]*)"[^>]*>(.*?)</select>', seite, re.S):
            gewaehlt = re.search(r'<option value="([^"]*)" selected', block)
            daten[_unescape(name)] = _unescape(gewaehlt.group(1)) if gewaehlt else ""
        for name, wert in re.findall(r'<input type="text" name="(wert_zu_[^"]+)"[^>]*value="([^"]*)"', seite):
            daten[_unescape(name)] = _unescape(wert)
        daten.update(ersetzt)
        self.assertEqual(self.client.post("/import/werte/", daten).status_code, 302)

    def _vorschau(self) -> dict[int, str]:
        seite = self.client.get("/import/").content.decode()
        return {int(z): e for z, e in re.findall(r'data-test="zeile" data-zeile="(\d+)" data-ergebnis="(\w+)"', seite)}

    def _zahlen(self) -> dict[str, int]:
        return kennzahlen_zahlen(self._vorschau())

    def _speichern(self):
        self.assertEqual(self.client.post("/import/speichern/").status_code, 302)

    def _blatt(self, blatt: str, kopfzeile: str = "") -> dict[str, int]:
        """Ein Blatt der Testdatei nur mit den Vorschlägen einlesen und speichern."""
        self.assertEqual(self._xlsx(blatt, kopfzeile).status_code, 302)
        self._weiter_mit_vorschlaegen()
        zahlen = self._zahlen()
        self._speichern()
        return zahlen


def _unescape(text: str) -> str:
    import html
    return html.unescape(text)


def kennzahlen_zahlen(vorschau: dict[int, str]) -> dict[str, int]:
    zahl = {"neu": 0, "ergaenzt": 0, "konflikt": 0, "uebersprungen": 0}
    for ergebnis in vorschau.values():
        zahl[ergebnis] += 1
    return zahl


class ImportDateiTests(Werkzeug):
    def test_blaetter_kommen_aus_der_datei(self):
        wb = Workbook()
        wb.active.title = "Tabelle1"
        wb.active.append(["Typ", "Modell", "Seriennummer"])
        wb.active.append(["Maus", "M185", "S1"])
        puffer = io.BytesIO()
        wb.save(puffer)
        puffer.seek(0)
        puffer.name = "eigen.xlsx"
        self.assertEqual(self.client.post("/import/datei/", {"datei": puffer}).status_code, 302)
        seite = self.client.get("/import/")
        self.assertContains(seite, 'value="Tabelle1"')
        self.assertNotContains(seite, 'value="Inventar"')
        self.assertEqual(self.client.post("/import/blatt/", {"blatt": "Tabelle1", "kopfzeile": ""}).status_code, 302)
        self.assertContains(self.client.get("/import/"), 'data-nr="2"')

    def test_kopfzeile_wird_erkannt(self):
        for blatt, kopf in (("Inventar", 3), ("Notebooks", 4), ("Smartphones", 4), ("Raumliste Hardware", 4)):
            with self.subTest(blatt=blatt):
                self.assertEqual(self._xlsx().status_code, 302)
                self.client.post("/import/blatt/", {"blatt": blatt, "kopfzeile": ""})
                stand = self.client.session["import_stand"]
                self.assertEqual(stand["kopfzeile"], kopf)
                self.client.post("/import/abbrechen/")

    def test_kaputte_datei(self):
        datei = io.BytesIO(b"keine zip-datei")
        datei.name = "kaputt.xlsx"
        antwort = self.client.post("/import/datei/", {"datei": datei})
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, 'data-test="fehler"', status_code=400)

    def test_kopfzeile_ohne_spalten_ist_keine_sackgasse(self):
        self.assertEqual(self._xlsx().status_code, 302)
        antwort = self.client.post("/import/blatt/", {"blatt": "Notebooks", "kopfzeile": "3"})
        self.assertEqual(antwort.status_code, 400)
        self.assertContains(antwort, "keine Spaltennamen", status_code=400)
        self.assertContains(antwort, 'data-test="blatt"', status_code=400)

    def test_zurueck_und_abbrechen(self):
        self._xlsx("Inventar", "3")
        self.assertContains(self.client.get("/import/"), 'data-test="zurueck"')
        self.client.post("/import/zurueck/")
        self.assertContains(self.client.get("/import/"), 'data-test="blatt"')
        self.client.post("/import/blatt/", {"blatt": "Inventar", "kopfzeile": "3"})
        self._weiter_mit_vorschlaegen()
        self.client.post("/import/zurueck/")
        self.assertContains(self.client.get("/import/"), 'data-nr="3"')
        self.client.post("/import/abbrechen/")
        self.assertEqual(Gerat.objects.count(), 0)
        self.assertContains(self.client.get("/import/"), 'type="file"')

    def test_nicht_angemeldet_zur_anmeldung(self):
        antwort = Client().get("/import/")
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort["Location"], "/anmelden/?" + urlencode({"next": "/import/"}))


class ImportVorschlagTests(Werkzeug):
    def test_spalten_sind_vorbelegt(self):
        self._xlsx("Inventar", "3")
        spalten = self._spalten_wie_vorgeschlagen()
        self.assertEqual(spalten["ziel_Typ"], "Kategorie")
        self.assertEqual(spalten["ziel_Garantie Ende"], "Garantie bis")
        self.assertEqual(spalten["ziel_Datum erhalt"], "Kaufdatum")
        self.assertEqual(spalten["ziel_Rechnung"], "ignorieren")
        self.assertEqual(spalten["ziel_Garantie"], "ignorieren")
        self.assertEqual(spalten["ziel_Status"], "ignorieren")

    def test_nur_mit_vorschlaegen_stimmen_die_eckwerte(self):
        self.assertEqual(self._blatt("Inventar"),
                         {"neu": 81, "ergaenzt": 1, "konflikt": 0, "uebersprungen": 41})
        self.assertEqual(self._blatt("Notebooks"),
                         {"neu": 18, "ergaenzt": 11, "konflikt": 0, "uebersprungen": 0})
        self.assertEqual(Gerat.objects.count(), 99)
        self.assertEqual(Gerat.objects.filter(status=Gerat.STATUS_IN_BENUTZUNG).count(), 15)
        self.assertEqual(Gerat.objects.filter(status=Gerat.STATUS_AUF_LAGER).count(), 84)
        # F-85: In Benutzung steht nicht am Lagerort; Kapitel 4.
        self.assertEqual(Gerat.objects.filter(ort=self.lager).count(), 84)
        self.assertEqual(Gerat.objects.filter(status=Gerat.STATUS_IN_BENUTZUNG, ort=self.lager).count(), 0)

    def test_person_aus_kommentar(self):
        self.assertEqual(import_parser.nutzer_aus_kommentar("aktueller Nutzer: Simon"), "Simon")
        self.assertEqual(import_parser.nutzer_aus_kommentar("Nutzer: Ben Hartung"), "Ben Hartung")
        self.assertEqual(import_parser.nutzer_aus_kommentar("Ursprünglicher Nutzer: Simon"), "")
        self.assertEqual(import_parser.nutzer_aus_kommentar("ursprunglicher Nutzer: Ben"), "")
        self.assertEqual(import_parser.nutzer_aus_kommentar("Defect"), "")


class ImportWerteTests(Werkzeug):
    def _csv_person(self, person: str, **ersetzt):
        self._csv(f"Typ;Modell;Seriennummer;Nutzer\nNotebook;T14;S-1;{person}\n")
        self._weiter_mit_vorschlaegen(**ersetzt)

    def test_neuer_arbeitsplatz_entsteht(self):
        self._csv("Typ;Modell;Seriennummer;Arbeitsplatz\nNotebook;T14;S-1;Platz 99\n")
        self._weiter_mit_vorschlaegen(**{"wert_zu_arbeitsplatz_Platz 99": "WMC-WP-99"})
        self.assertIn("neuer Arbeitsplatz", self.client.get("/import/").content.decode())
        self._speichern()
        g = Gerat.objects.get(seriennummer="S-1")
        self.assertEqual(g.ort.kennung, "WMC-WP-99")
        self.assertEqual(g.ort.typ, Ort.TYP_ARBEITSPLATZ)
        self.assertEqual(g.status, Gerat.STATUS_IN_BENUTZUNG)

    def test_feld_neue_person_wirkt(self):
        self._csv_person("Anna Becker", neuer_person_name="Nora Neumann")
        self._speichern()
        self.assertTrue(Person.objects.filter(vorname="Nora", nachname="Neumann").exists())

    def test_drei_namen_bleiben_drei_namen(self):
        self._csv_person("Anna Maria Schmidt")
        self.assertIn("(neue Person)", self.client.get("/import/").content.decode())
        self._speichern()
        p = Gerat.objects.get(seriennummer="S-1").person
        self.assertEqual((p.vorname, p.nachname), ("Anna Maria", "Schmidt"))

    def test_vorhandene_personen_stehen_zur_wahl(self):
        self._csv("Typ;Modell;Seriennummer;Nutzer\nNotebook;T14;S-1;Anna\n")
        self.client.post("/import/spalten/", self._spalten_wie_vorgeschlagen())
        seite = self.client.get("/import/")
        self.assertContains(seite, '<option value="Felix Hoffmann">')
        self.assertContains(seite, 'value="Anna Becker"')

    def test_mehrdeutiger_vorname_bleibt_offen(self):
        Person.objects.create(vorname="Anna", nachname="Wolf")
        self.assertIsNone(import_parser._person_finden("Anna"))
        self.assertEqual(import_parser._person_finden("Anna Wolf").nachname, "Wolf")


class ImportRegelnTests(Werkzeug):
    def _lesen(self, text: str, **ersetzt):
        self._csv(text)
        self._weiter_mit_vorschlaegen(**ersetzt)
        return self._vorschau()

    def test_nur_kategorie_wird_uebersprungen(self):
        self.assertEqual(self._lesen("Typ;Modell;Kommentar\nNotebook;;Nicht vorhanden\n"), {2: "uebersprungen"})
        self._speichern()
        self.assertEqual(Gerat.objects.count(), 0)

    def test_ohne_kategorie_stimmen_vorschau_und_ergebnis(self):
        vorschau = self._lesen("Hersteller;Modell;Gerätename\nHP;EliteBook;\nHP;EliteBook;WMC-NB-9\n")
        self.assertEqual(vorschau, {2: "uebersprungen", 3: "neu"})
        self._speichern()
        g = Gerat.objects.get()
        self.assertEqual((g.geraetename, g.kategorie.name), ("WMC-NB-9", "Sonstiges"))

    def test_kategorie_fuer_zeilen_ohne_kategorie(self):
        vorschau = self._lesen("Hersteller;Modell\nHP;EliteBook\n", kategorie_standard="Notebook")
        self.assertEqual(vorschau, {2: "neu"})
        self._speichern()
        self.assertEqual(Gerat.objects.get().kategorie, self.notebook)

    def test_ungueltiges_datum_bleibt_leer(self):
        self._lesen("Typ;Modell;Kaufdatum\nNotebook;T14;31.02.2024\n")
        self._speichern()
        self.assertIsNone(Gerat.objects.get().kaufdatum)

    def test_gleicher_name_andere_seriennummer_ist_neu(self):
        self._gerat(geraetename="WMC-HS-001", seriennummer="SN-1")
        self.assertEqual(self._lesen("Typ;Hersteller;Modell;Gerätename;Seriennummer\nNotebook;HP;X;WMC-HS-001;SN-2\n"), {2: "neu"})
        self._speichern()
        self.assertEqual(Gerat.objects.filter(geraetename="WMC-HS-001").count(), 2)

    def test_abweichende_werte_sind_konflikt(self):
        g = self._gerat(seriennummer="SN-1", garantie_bis=date(2026, 1, 1), rechnungsnummer="R-1",
                        kaufdatum=date(2024, 1, 1), person=self.anna)
        vorschau = self._lesen(
            "Typ;Modell;Seriennummer;Garantie bis;Rechnungsnummer;Kaufdatum;Nutzer\n"
            "Notebook;T14;SN-1;02.02.2027;R-2;03.03.2023;Felix Hoffmann\n")
        self.assertEqual(vorschau, {2: "konflikt"})
        seite = self.client.get("/import/").content.decode()
        self.assertNotIn("abweichende Seriennummer", seite)
        self.assertIn("Garantie bis 01.01.2026 → 02.02.2027", seite)
        self._speichern()
        g.refresh_from_db()
        self.assertEqual(g.garantie_bis, date(2026, 1, 1))
        self.assertEqual(g.person, self.anna)
        self.assertEqual(set(g.konflikte.values_list("feld", flat=True)),
                         {"garantie_bis", "rechnungsnummer", "kaufdatum", "person"})

    def test_andere_schreibweise_ist_kein_konflikt(self):
        self._gerat(seriennummer="SN-1", hersteller="Apple Inc.", modell="MacBook")
        vorschau = self._lesen("Typ;Hersteller;Modell;Seriennummer\nNotebook;apple;Macbook Pro;SN-1\n")
        self.assertEqual(vorschau, {2: "ergaenzt"})

    def test_derselbe_konflikt_nur_einmal_offen(self):
        g = self._gerat(seriennummer="SN-1", geraetename="ALT")
        text = "Typ;Modell;Seriennummer;Gerätename\nNotebook;T14;SN-1;NEU\n"
        self._lesen(text)
        self._speichern()
        self._lesen(text)
        self._speichern()
        self.assertEqual(g.konflikte.filter(offen=True).count(), 1)

    def test_entschiedener_konflikt_kommt_nicht_wieder(self):
        g = self._gerat(seriennummer="SN-1", geraetename="ALT")
        text = "Typ;Modell;Seriennummer;Gerätename\nNotebook;T14;SN-1;NEU\n"
        self._lesen(text)
        self._speichern()
        services.konflikt_loesen(g.konflikte.get(), "alt", ausgefuehrt_von=self.admin)
        self.assertEqual(self._lesen(text), {2: "ergaenzt"})

    def test_konflikt_neuer_wert_datum_und_person(self):
        g = self._gerat(seriennummer="SN-1", kaufdatum=date(2024, 1, 1))
        konflikt = GeratKonflikt.objects.create(gerat=g, feld="kaufdatum", alter_wert="01.01.2024", neuer_wert="02.02.2023")
        services.konflikt_loesen(konflikt, "neu", ausgefuehrt_von=self.admin)
        g.refresh_from_db()
        self.assertEqual(g.kaufdatum, date(2023, 2, 2))
        konflikt = GeratKonflikt.objects.create(gerat=g, feld="person", alter_wert="", neuer_wert="Felix Hoffmann")
        with self.assertRaises(services.GeratFehler):
            services.konflikt_loesen(konflikt, "neu", ausgefuehrt_von=self.admin)

    def test_gleiche_nummer_anderer_hersteller_behaelt_sie(self):
        vorschau = self._lesen(
            "Typ;Hersteller;Modell;Seriennummer\n"
            "Notebook;Bose;A;SN-1\nNotebook;Logitech;B;SN-1\nNotebook;Logitech;C;SN-1\n")
        self.assertEqual(vorschau, {2: "neu", 3: "neu", 4: "neu"})
        self._speichern()
        self.assertEqual(Gerat.objects.filter(seriennummer="SN-1").count(), 2)
        drittes = Gerat.objects.get(modell="C")
        self.assertEqual(drittes.seriennummer, "")
        self.assertIn("SN-1", drittes.notiz)

    def test_ausgemustert_bleibt_wie_es_ist(self):
        alt = self._ausgemustert()
        vorschau = self._lesen("Typ;Modell;Seriennummer;Gerätename;Rechnungsnummer\nNotebook;T14;ALT-1;NEU;R-9\n")
        self.assertEqual(vorschau, {2: "uebersprungen"})
        self._speichern()
        alt.refresh_from_db()
        self.assertEqual((alt.geraetename, alt.rechnungsnummer), ("ALT-NAME", ""))

    def test_zweiter_import_legt_nichts_doppelt_an(self):
        self._blatt("Inventar")
        self._blatt("Notebooks")
        vorher = Gerat.objects.count()
        konflikte = GeratKonflikt.objects.count()
        vorgaenge = Vorgang.objects.count()
        self.assertEqual(self._blatt("Inventar"), {"neu": 0, "ergaenzt": 82, "konflikt": 0, "uebersprungen": 41})
        self.assertEqual(self._blatt("Notebooks"), {"neu": 0, "ergaenzt": 29, "konflikt": 0, "uebersprungen": 0})
        self.assertEqual(Gerat.objects.count(), vorher)
        self.assertEqual(GeratKonflikt.objects.count(), konflikte)
        self.assertEqual(Vorgang.objects.count(), vorgaenge)

    def test_zweiter_import_wird_angekuendigt(self):
        self._blatt("Inventar")
        self._xlsx("Inventar", "3")
        self._weiter_mit_vorschlaegen()
        self.assertContains(self.client.get("/import/"), 'data-test="frueherer-import"')

    def test_vorbelegte_hinweise(self):
        self._xlsx("Inventar", "3")
        self._weiter_mit_vorschlaegen()
        seite = self.client.get("/import/").content.decode()
        for zeile in (71, 77, 80, 97):
            block = re.search(rf'data-zeile="{zeile}".*?</tr>', seite, re.S).group(0)
            self.assertIn('data-art="geraetename-doppelt"', block)
        block = re.search(r'data-zeile="18".*?</tr>', seite, re.S).group(0)
        self.assertIn('data-art="seriennummer-doppelt"', block)


class ImportEckwerteTests(Werkzeug):
    """Fallen aus vorlagen/README, gelesen am Ergebnis im Bestand."""

    def test_zeile_5_und_die_ipads(self):
        self._blatt("Inventar")
        self._xlsx("Notebooks", "4")
        self._weiter_mit_vorschlaegen()
        seite = self.client.get("/import/").content.decode()
        for zeile in (18, 19):
            block = re.search(rf'data-zeile="{zeile}".*?</tr>', seite, re.S).group(0)
            self.assertIn('data-art="geraetename-doppelt"', block)
        self._speichern()
        defekt = Gerat.objects.get(geraetename="WMC-NB-MB-01")
        self.assertEqual(defekt.zustand, Gerat.ZUSTAND_EINGESCHRAENKT)
        self.assertEqual(defekt.notiz, "Defect; laut Altliste defekt: reparieren oder ausmustern")
        ipads = Gerat.objects.filter(geraetename="WMC-I-2301")
        self.assertEqual(ipads.count(), 2)
        self.assertEqual(ipads.exclude(seriennummer="").count(), 2)
        a = ipads.first()
        self.assertContains(self.client.get(f"/geraete/{a.inventarnummer}/"), "Gerätename auch bei")

    def test_zeile_18_zeigt_den_vermerk_im_detail(self):
        self._blatt("Inventar")
        g = Gerat.objects.get(geraetename="WMC-HW-2016")
        self.assertEqual(g.seriennummer, "")
        seite = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertContains(seite, 'data-test="hinweis" data-art="seriennummer-doppelt"')
        self.assertContains(seite, "2382KZ42KWQ5")


class ImportVerbleibTests(Werkzeug):
    def test_nur_arbeitsplatz_ist_in_benutzung(self):
        self._csv("Typ;Modell;Seriennummer;Arbeitsplatz\nNotebook;T14;S-1;WMC-WP-01\n")
        self._weiter_mit_vorschlaegen()
        self.assertIn("In Benutzung an WMC-WP-01", self.client.get("/import/").content.decode())
        self._speichern()
        g = Gerat.objects.get()
        self.assertEqual((g.status, g.ort, g.person), (Gerat.STATUS_IN_BENUTZUNG, self.wp1, None))
        self.assertTrue(g.altbestand_ohne_protokoll)

    def test_raumliste_liest_verbundene_zellen(self):
        self.assertEqual(self._xlsx("Raumliste Hardware").status_code, 302)
        self._weiter_mit_vorschlaegen()
        vorschau = self._vorschau()
        self.assertEqual(len(vorschau), 56)
        self.assertEqual(vorschau[56], "uebersprungen")
        self.assertEqual(vorschau[65], "uebersprungen")
        self._speichern()
        self.assertEqual(Gerat.objects.filter(ort=self.wp1).count(), 7)
        self.assertEqual(Gerat.objects.filter(ort__kennung="WMC-WP-05").count(), 7)
        # Jonas Albrecht steht über alle Zeilen von WMC-WP-01 verbunden.
        self.assertEqual(Gerat.objects.filter(ort=self.wp1, person__nachname="Albrecht").count(), 7)

    def test_smartphones_mit_vorschlaegen(self):
        self.assertEqual(self._xlsx("Smartphones").status_code, 302)
        self._weiter_mit_vorschlaegen()
        self.assertEqual(self._zahlen(), {"neu": 10, "ergaenzt": 0, "konflikt": 0, "uebersprungen": 0})
        self._speichern()
        defekt = Gerat.objects.filter(zustand=Gerat.ZUSTAND_EINGESCHRAENKT)
        self.assertEqual(defekt.count(), 5)
        self.assertIn("laut Altliste defekt", defekt.first().notiz)
        self.assertEqual(Gerat.objects.filter(kategorie__name="Smartphone").count(), 10)

    def test_spaeteres_blatt_setzt_arbeitsplatz(self):
        self._csv("Typ;Modell;Seriennummer\nNotebook;T14;S-1\n", name="a.csv")
        self._weiter_mit_vorschlaegen()
        self._speichern()
        g = Gerat.objects.get()
        self.assertEqual((g.status, g.ort), (Gerat.STATUS_AUF_LAGER, self.lager))
        self._csv("Typ;Modell;Seriennummer;Arbeitsplatz\nNotebook;T14;S-1;WMC-WP-01\n", name="b.csv")
        self._weiter_mit_vorschlaegen()
        self._speichern()
        g.refresh_from_db()
        self.assertEqual((g.status, g.ort), (Gerat.STATUS_IN_BENUTZUNG, self.wp1))
        self.assertTrue(g.altbestand_ohne_protokoll)

    def test_von_hand_erfasst_bleibt_auf_lager(self):
        g = self._gerat(seriennummer="S-1", ort=self.lager)
        self._csv("Typ;Modell;Seriennummer;Nutzer\nNotebook;T14;S-1;Felix Hoffmann\n")
        self._weiter_mit_vorschlaegen()
        self.assertEqual(self._vorschau(), {2: "ergaenzt"})
        self._speichern()
        g.refresh_from_db()
        self.assertEqual((g.status, g.person), (Gerat.STATUS_AUF_LAGER, None))
        self.assertFalse(g.altbestand_ohne_protokoll)

    def test_defekt_auf_ergaenzter_zeile(self):
        self._csv("Typ;Modell;Seriennummer\nNotebook;T14;S-1\n", name="a.csv")
        self._weiter_mit_vorschlaegen()
        self._speichern()
        self._csv("Typ;Modell;Seriennummer;Kommentar\nNotebook;T14;S-1;Defect\n", name="b.csv")
        self._weiter_mit_vorschlaegen()
        self._speichern()
        g = Gerat.objects.get()
        self.assertEqual(g.zustand, Gerat.ZUSTAND_EINGESCHRAENKT)
        self.assertIn("laut Altliste defekt", g.notiz)

    def test_altbestand_endet_mit_der_bewegung(self):
        self._csv("Typ;Modell;Seriennummer;Nutzer\nNotebook;T14;S-1;Felix Hoffmann\n")
        self._weiter_mit_vorschlaegen()
        self._speichern()
        g = Gerat.objects.get()
        self.assertTrue(g.altbestand_ohne_protokoll)
        services.gerat_umziehen(g, self.wp5, ausgefuehrt_von=self.admin)
        g.refresh_from_db()
        self.assertFalse(g.altbestand_ohne_protokoll)
        self.assertEqual(g.person, self.felix)


class ImportVorschauTests(Werkzeug):
    def test_feste_texte_und_marker(self):
        self._gerat(seriennummer="SN-1", geraetename="WMC-A")
        self._csv("Typ;Modell;Seriennummer;Gerätename\nNotebook;T14;SN-1;\nNotebook;T15;SN-2;WMC-B\nUSB-C Kabel;X;;\n")
        self._weiter_mit_vorschlaegen()
        seite = self.client.get("/import/").content.decode()
        self.assertIn('data-test="zeile" data-zeile="2" data-ergebnis="ergaenzt"', seite)
        self.assertNotIn("vorschau-zeile", seite)
        self.assertIn(">ergänzt</span>", seite)
        self.assertIn(">übersprungen</span>", seite)
        self.assertNotIn(">ergaenzt<", seite)
        self.assertIn("WMC-B", seite)
        self.assertIn('data-test="hinweis" data-art="ungeprueft"', seite)
        csv_text = self.client.get("/import/vorschau.csv/").content.decode("utf-8-sig")
        self.assertEqual(len(csv_text.strip().splitlines()), 4)
        self.assertIn("ergänzt", csv_text)

    def test_meldung_nach_dem_speichern(self):
        self._csv("Typ;Modell;Seriennummer\nNotebook;T14;S-1\n")
        self._weiter_mit_vorschlaegen()
        antwort = self.client.post("/import/speichern/", follow=True)
        self.assertContains(antwort, 'data-test="meldung"')
        self.assertContains(antwort, "Import gespeichert: 1 neu, 0 ergänzt, 0 Konflikt, 0 übersprungen.")

    def test_grund_nennt_die_neue_person(self):
        self._csv("Typ;Modell;Seriennummer;Nutzer\nNotebook;T14;S-1;Nora Neu\n")
        self._weiter_mit_vorschlaegen()
        seite = self.client.get("/import/").content.decode()
        self.assertIn("In Benutzung bei Nora Neu (neue Person)", seite)
        self.assertNotIn("ohne Person und Arbeitsplatz", seite)

    def test_garantiezeile_nennt_die_zeile(self):
        self._xlsx("Inventar", "3")
        self._weiter_mit_vorschlaegen()
        self.assertContains(self.client.get("/import/"), "ergänzt Gerät aus Zeile 4")


class LueckenTests(Grund):
    def test_nicht_ermittelbar_im_formular(self):
        g = self._gerat(seriennummer="SN-1", ort=self.lager)
        self.assertContains(self.client.get(f"/geraete/{g.inventarnummer}/aendern/"), "kaufdatum_nicht_ermittelbar")
        daten = {"kategorie": g.kategorie_id, "hersteller": g.hersteller, "modell": g.modell,
                 "seriennummer": g.seriennummer, "zustand": g.zustand, "ort": g.ort_id,
                 "kaufdatum_nicht_ermittelbar": "on", "garantie_nicht_ermittelbar": "on"}
        self.assertEqual(self.client.post(f"/geraete/{g.inventarnummer}/aendern/", daten).status_code, 302)
        g.refresh_from_db()
        self.assertTrue(g.kaufdatum_nicht_ermittelbar)
        self.assertEqual(g.datenluecken(), [])
        self.assertFalse(g.ist_unvollstaendig())

    def test_importiertes_geraet_ohne_nummer_laesst_sich_aendern(self):
        g = self._gerat(ort=self.lager)
        self.assertEqual(g.seriennummer, "")
        daten = {"kategorie": g.kategorie_id, "hersteller": g.hersteller, "modell": "Neu",
                 "seriennummer": "", "zustand": g.zustand, "ort": g.ort_id}
        self.assertEqual(self.client.post(f"/geraete/{g.inventarnummer}/aendern/", daten).status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.modell, "Neu")

    def test_gepruft_beendet_ungeprueft(self):
        g = self._gerat(ort=self.lager)
        Gerat.objects.filter(pk=g.pk).update(zustand_ungeprueft=True)
        self.client.post(f"/geraete/{g.inventarnummer}/pruefen/")
        g.refresh_from_db()
        self.assertFalse(g.zustand_ungeprueft)
        self.assertIsNotNone(g.zuletzt_geprueft_am)

    def test_zustand_aendern_beendet_ungeprueft(self):
        g = self._gerat(ort=self.lager)
        Gerat.objects.filter(pk=g.pk).update(zustand_ungeprueft=True)
        g.refresh_from_db()
        services.gerat_bearbeiten(g, werte={"zustand": Gerat.ZUSTAND_SPUREN}, erzeugt_von=self.admin)
        g.refresh_from_db()
        self.assertFalse(g.zustand_ungeprueft)

    def test_erstinventur_traegt_nach(self):
        g = self._gerat(ort=self.lager)
        Gerat.objects.filter(pk=g.pk).update(zustand_ungeprueft=True)
        seite = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertContains(seite, 'data-test="erstinventur"')
        self.assertContains(seite, 'data-test="hinweis" data-art="ungeprueft"')
        self.client.post(f"/geraete/{g.inventarnummer}/pruefen/", {
            "seriennummer": "SN-NEU", "zustand": "3", "kaufdatum": "01.02.2024",
            "garantie_nicht_ermittelbar": "1", "ziel_ort": "",
        })
        g.refresh_from_db()
        self.assertEqual((g.seriennummer, g.zustand, g.kaufdatum), ("SN-NEU", 3, date(2024, 2, 1)))
        self.assertTrue(g.garantie_nicht_ermittelbar)
        self.assertEqual(g.datenluecken(), [])
        self.assertTrue(Vorgang.objects.filter(gerat=g, aenderung_feld="seriennummer").exists())

    def test_erstinventur_falsches_datum_aendert_nichts(self):
        g = self._gerat(ort=self.lager)
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/pruefen/", {"kaufdatum": "gestern"}, follow=True)
        self.assertContains(antwort, 'data-test="fehler"')
        g.refresh_from_db()
        self.assertIsNone(g.zuletzt_geprueft_am)

    def test_erstinventur_verbleib_von_hand_erfasst_nur_ueber_ausgabe(self):
        g = self._gerat(ort=self.lager)
        antwort = self.client.post(f"/geraete/{g.inventarnummer}/pruefen/", {"ziel_ort": self.wp1.pk}, follow=True)
        self.assertContains(antwort, 'data-test="fehler"')
        g.refresh_from_db()
        self.assertEqual(g.ort, self.lager)
        self.assertIsNone(g.zuletzt_geprueft_am)

    def test_naechstes_geraet(self):
        g = self._gerat(ort=self.lager)
        n = self._gerat(ort=self.lager)
        seite = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertContains(seite, f'href="/geraete/{n.inventarnummer}/" data-test="naechstes-geraet"')

    def test_leser_hat_keine_erstinventur(self):
        g = self._gerat(ort=self.lager)
        self.client.force_login(self.leser)
        seite = self.client.get(f"/geraete/{g.inventarnummer}/")
        self.assertNotContains(seite, 'data-test="geprueft"')
        self.assertEqual(self.client.post(f"/geraete/{g.inventarnummer}/pruefen/").status_code, 403)

    def test_fortschritt_auch_fuer_das_lager(self):
        g = self._gerat(ort=self.lager)
        services.gerat_pruefen(g, self.admin)
        self._gerat(person=self.anna)
        seite = self.client.get("/arbeitsplaetze/pruefen/")
        self.assertContains(seite, "1 von 2 geprüft")
        self.assertContains(seite, "LAGER-EG")

    def test_doppelter_name_als_hinweis(self):
        a = self._gerat(geraetename="WMC-X")
        b = self._gerat(geraetename="WMC-X", kategorie=self.monitor)
        seite = self.client.get(f"/geraete/{a.inventarnummer}/")
        self.assertContains(seite, 'data-test="hinweis" data-art="geraetename-doppelt"')
        self.assertContains(seite, "Gerätename auch bei")
        self.assertContains(seite, b.inventarnummer)

    def test_seriennummer_vermerk_als_hinweis(self):
        a = self._gerat(seriennummer="SN-1", hersteller="Logitech")
        b = self._gerat(hersteller="Logitech", notiz="Seriennummer SN-1 doppelt im Blatt")
        seite = self.client.get(f"/geraete/{b.inventarnummer}/")
        self.assertContains(seite, 'data-test="hinweis" data-art="seriennummer-doppelt"')
        self.assertContains(seite, a.inventarnummer)

    def test_pflicht_wie_in_der_testschnittstelle(self):
        ohne = {name for name, _, pflicht in KATEGORIEN if not pflicht}
        self.assertEqual(ohne, {"Tastatur", "Maus", "Headset", "Notebook-Ständer", "Powerbank", "USB-Hub", "Sonstiges"})


class UebersichtTests(Grund):
    def _kennzahl(self, html: str, data_id: str) -> str | None:
        treffer = re.search(rf'data-test="kennzahl" data-id="{data_id}".*?</li>', html, re.S)
        return treffer.group(0) if treffer else None

    def _platz_mit_profil(self):
        profil = Ausstattungsprofil.objects.create(name="P")
        profil.positionen.create(kategorie=self.headset, anzahl=1)
        self.wp1.profil = profil
        self.wp1.save()
        self.wp5.profil = profil
        self.wp5.save()
        self.studio.profil = None
        return profil

    def test_arbeitsplaetze_nach_soll_ist(self):
        self._platz_mit_profil()
        g = self._gerat(kategorie=self.headset, modell="H1")
        Gerat.objects.filter(pk=g.pk).update(ort=self.wp1, status=Gerat.STATUS_IN_BENUTZUNG)
        html = self.client.get("/").content.decode()
        zeile = self._kennzahl(html, "arbeitsplaetze-vollstaendig")
        self.assertIn('data-test="ist">1<', zeile)
        self.assertIn('data-test="gesamt">2<', zeile)
        liste = re.search(r'data-id="arbeitsplaetze-unvollstaendig".*?</section>', html, re.S).group(0)
        self.assertIn("WMC-WP-05", liste)
        self.assertNotIn("WMC-WP-01", liste)
        self.assertIn("fehlt: 1 × Headset", liste)

    def test_geprueft_verschwindet_wenn_alle_geprueft(self):
        g = self._gerat(ort=self.lager)
        self.assertIsNotNone(self._kennzahl(self.client.get("/").content.decode(), "geprueft"))
        services.gerat_pruefen(g, self.admin)
        self.assertIsNone(self._kennzahl(self.client.get("/").content.decode(), "geprueft"))

    def test_zurueckgegebene_leihe_ist_nicht_ueberfaellig(self):
        g = self._gerat(ort=self.lager)
        Leihe.objects.create(gerat=g, person=self.anna, rueckgabe_bis=date(2020, 1, 1),
                             status=Leihe.STATUS_AUSGEGEBEN, nr="L-0001")
        self.assertEqual(kennzahlen.ueberfaellig(date(2026, 1, 1)), [])
        Gerat.objects.filter(pk=g.pk).update(status=Gerat.STATUS_VERLIEHEN)
        self.assertEqual(len(kennzahlen.ueberfaellig(date(2026, 1, 1))), 1)

    def test_kein_altes_delta(self):
        heute = kennzahlen._heute()
        for tage, wert in ((3, 5), (2, 7)):
            Zaehlerstand.objects.create(
                stichtag=heute - timedelta(days=tage),
                kennzahlen={"in-benutzung": {"ist": wert, "gesamt": 9}},
                erzeugt_am=kennzahlen.jetzt_aware(),
            )
        self.assertNotContains(self.client.get("/"), 'data-test="delta"')

    def test_delta_zum_vortag(self):
        heute = kennzahlen._heute()
        for tage, wert in ((1, 5), (0, 7)):
            Zaehlerstand.objects.create(
                stichtag=heute - timedelta(days=tage),
                kennzahlen={"in-benutzung": {"ist": wert, "gesamt": 9}},
                erzeugt_am=kennzahlen.jetzt_aware(),
            )
        self.assertContains(self.client.get("/"), "+2")

    def test_anfrage_springt_zur_entscheidung(self):
        leihe = Leihe.objects.create(person=self.anna, kat=self.notebook, status=Leihe.STATUS_ANGEFRAGT, nr="L-0002")
        self.assertContains(self.client.get("/"), f'href="/geraete/verleih/{leihe.pk}/genehmigen/"')
        self.client.force_login(self.leser)
        antwort = self.client.get("/")
        self.assertNotContains(antwort, "/genehmigen/")
        self.assertContains(antwort, "L-0002")

    def test_lange_arbeitsliste_bleibt_im_rahmen(self):
        for _ in range(9):
            self._gerat()
        html = self.client.get("/").content.decode()
        liste = re.search(r'data-id="daten-unvollstaendig".*?</section>', html, re.S).group(0)
        self.assertIn('class="worklist lang"', liste)
        self.assertEqual(liste.count('data-test="zeile"'), 9)
        self.assertIn('data-test="alle-anzeigen"', liste)
        self.assertNotIn("zustand-ungeprueft", liste)

    def test_export_der_arbeitslisten_hat_inhalt(self):
        g = self._gerat(garantie_bis=kennzahlen._heute() + timedelta(days=5))
        for fmt in ("csv", "xlsx"):
            antwort = self.client.get("/exporte/", {"liste": "garantie", "format": fmt})
            self.assertEqual(antwort.status_code, 200)
            if fmt == "csv":
                self.assertIn(g.inventarnummer, antwort.content.decode("utf-8-sig"))
            else:
                wb = load_workbook(io.BytesIO(antwort.content))
                self.assertEqual(wb.active.cell(2, 1).value, g.inventarnummer)

    def test_alle_arbeitslisten_exportieren_ohne_leere_zellen(self):
        self._gerat()
        zeilen = self.client.get("/exporte/", {"liste": "daten-unvollstaendig", "format": "csv"}) \
            .content.decode("utf-8-sig").splitlines()
        self.assertIn("Seriennummer", zeilen[1])

    def test_mitarbeiter_exportiert_nicht(self):
        self.client.force_login(self.mitarbeiter)
        self.assertEqual(self.client.get("/exporte/", {"liste": "garantie", "format": "csv"}).status_code, 403)

    def test_export_arbeitsplatzliste(self):
        self._platz_mit_profil()
        antwort = self.client.get("/arbeitsplaetze/liste/", {"format": "csv"})
        self.assertEqual(antwort["Content-Type"], "text/csv; charset=utf-8")
        text = antwort.content.decode("utf-8-sig")
        self.assertIn("WMC-WP-05", text)
        self.assertIn("1 × Headset", text)
        self.assertContains(self.client.get("/arbeitsplaetze/liste/"), 'data-test="export-csv"')

    def test_export_bedarf(self):
        self._platz_mit_profil()
        antwort = self.client.get("/arbeitsplaetze/bedarf/", {"format": "xlsx"})
        wb = load_workbook(io.BytesIO(antwort.content))
        self.assertEqual(wb.active.cell(2, 1).value, "Headset")

    def test_api_stand_mit_uhrzeit(self):
        self.assertRegex(kennzahlen.uebersicht()["stand"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
