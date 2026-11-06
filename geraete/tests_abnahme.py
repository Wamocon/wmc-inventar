"""Befunde der Prüfung nach der Abnahme (Stand ad682d8), jeder mit einem Test (N-10)."""
from __future__ import annotations

from datetime import timedelta

from django.test import Client

from stammdaten.models import Person

from . import pdf as pdf_modul, services
from .models import Gerat, Leihe, Protokoll
from .tests import konto_erstellen
from .tests_fix_listen import Werkzeug
from .tests_pruefung2 import HEUTE, Grundlage


class NichtVorhandenTests(Werkzeug):
    """Entscheidung 7 (Erwin 06.11.2026): „Nicht vorhanden“ in der Raumliste ist kein Gerät."""

    def _lesen(self, text: str):
        self._csv(text)
        self._weiter_mit_vorschlaegen()
        return self._vorschau()

    def test_auch_mit_hersteller_typ_und_modell_kein_geraet(self):
        vorschau = self._lesen("Typ;Hersteller;Modell;Gerätename\nNotebook;Dell;Display Link;Nicht vorhanden\n")
        self.assertEqual(vorschau, {2: "uebersprungen"})
        self.assertContains(self.client.get("/import/"), "kein Gerät am Platz")
        self._speichern()
        self.assertEqual(Gerat.objects.count(), 0)

    def test_eine_echte_zeile_daneben_bleibt(self):
        vorschau = self._lesen(
            "Typ;Hersteller;Modell;Gerätename\nNotebook;Dell;Display Link;Nicht vorhanden\nNotebook;HP;EliteBook;WMC-NB-7\n"
        )
        self.assertEqual(vorschau, {2: "uebersprungen", 3: "neu"})


class GemischteRuecknahmeTests(Grundlage):
    """FRM-002 Abschnitt 4: Altbestand und Gerät mit Ausgabeprotokoll in einer Rücknahme."""

    def _ruecknahme(self, *geraete):
        services.geraete_zuruecknehmen(
            self.anna,
            [{"gerat": Gerat.objects.get(pk=g.pk), "zustand_rueckgabe": 2, "zubehoer_komplett": True,
              "maengel": "", "ziel": "lager"} for g in geraete],
            ausgefuehrt_von=self.admin,
        )
        return Protokoll.objects.filter(art=Protokoll.ART_RUECKNAHME).latest("id")

    def _altbestand(self, sn):
        gerat = self._gerat(sn)
        Gerat.objects.filter(pk=gerat.pk).update(
            status=Gerat.STATUS_IN_BENUTZUNG, person=self.anna, ort=None, altbestand_ohne_protokoll=True,
        )
        return gerat

    def _mit_protokoll(self, sn):
        gerat = self._gerat(sn)
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin, unterschrift="papier")
        return gerat

    def test_gemischt_sagt_beides(self):
        html = pdf_modul._render_inhalt(self._ruecknahme(self._altbestand("G-1"), self._mit_protokoll("G-2")))
        self.assertIn("die Geräte mit Ausgabeprotokoll im dort dokumentierten Zustand", html)
        self.assertIn("Zum Zustand des Altbestands bei Ausgabe liegt kein Protokoll vor.", html)
        self.assertNotIn("im bei Ausgabe dokumentierten Zustand zurückgegeben", html)

    def test_nur_altbestand(self):
        html = pdf_modul._render_inhalt(self._ruecknahme(self._altbestand("G-3")))
        self.assertIn("Zum Zustand bei Ausgabe liegt kein Protokoll vor.", html)

    def test_nur_mit_protokoll(self):
        html = pdf_modul._render_inhalt(self._ruecknahme(self._mit_protokoll("G-4"), self._mit_protokoll("G-5")))
        self.assertIn("im bei Ausgabe dokumentierten Zustand zurückgegeben", html)
        self.assertNotIn("liegt kein Protokoll vor", html)


class LeserAnfragenTests(Grundlage):
    """Kapitel 2, Erwin 06.11.2026: Der Leser sieht von den offenen Leihanfragen nur seine eigenen."""

    def setUp(self):
        super().setUp()
        self.gf = Person.objects.create(vorname="Martin", nachname="Albers", email="gf@beispiel.test")
        self.leser = konto_erstellen("gf", "leser", "gf@beispiel.test")
        self.leser.person = self.gf
        self.leser.save()
        bis = HEUTE + timedelta(days=3)
        self.fremd = Leihe.objects.create(nr="L-0901", person=self.anna, kat=self.kat, beginn=HEUTE, ende=bis,
                                          rueckgabe_bis=bis, zweck="Messe Frankfurt", status=Leihe.STATUS_ANGEFRAGT)
        self.eigen = Leihe.objects.create(nr="L-0902", person=self.gf, kat=self.kat, beginn=HEUTE, ende=bis,
                                          rueckgabe_bis=bis, zweck="Vortrag", status=Leihe.STATUS_ANGEFRAGT)
        self.c = Client()
        self.c.force_login(self.leser)

    def test_uebersicht_ohne_fremde_anfragen(self):
        seite = self.c.get("/").content.decode()
        self.assertNotIn("Messe Frankfurt", seite)
        self.assertNotIn('data-id="L-0901"', seite)
        self.assertIn('data-id="L-0902"', seite)

    def test_export_ohne_fremde_anfragen(self):
        text = self.c.get("/exporte/?liste=anfragen&format=csv").content.decode("utf-8-sig")
        self.assertNotIn("Messe Frankfurt", text)
        self.assertNotIn("Anna", text)
        self.assertIn("L-0902", text)

    def test_admin_sieht_alle(self):
        seite = self.client.get("/").content.decode()
        self.assertIn('data-id="L-0901"', seite)
        self.assertIn('data-id="L-0902"', seite)
        text = self.client.get("/exporte/?liste=anfragen&format=csv").content.decode("utf-8-sig")
        self.assertIn("Messe Frankfurt", text)

    def test_leser_hat_den_eintrag_in_der_seitenleiste(self):
        self.assertContains(self.c.get("/meine-geraete/"), 'data-test="nav-leihen"')


class VerleihlisteTests(Grundlage):
    """Entscheidung 6: Beschriftungen im Verleih wörtlich aus dem Prototyp."""

    def test_spalten_wie_im_prototyp(self):
        seite = self.client.get("/verleih/").content.decode()
        kopf = seite[seite.index("<thead>"):seite.index("</thead>")]
        reihenfolge = [kopf.index(f"<th>{t}</th>") for t in ("Nr.", "Person", "Gerät", "Zeitraum", "Zweck", "Status")]
        self.assertEqual(reihenfolge, sorted(reihenfolge))
        self.assertNotIn("<th>Stand</th>", kopf)


class OffboardingZustandTests(Grundlage):
    """F-50: Ein leerer Zustand bei Rückgabe gilt nicht als der bisherige."""

    def test_leerer_zustand_wird_abgewiesen(self):
        gerat = self._gerat("O-1")
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin, unterschrift="papier")
        antwort = self.client.post(f"/personen/{self.anna.pk}/offboarding/zuruecknehmen/", {
            f"zustand-{gerat.inventarnummer}": "", "unterschrift": "tool", "aktion": "alle",
        }, follow=True)
        self.assertContains(antwort, "Bitte einen der vier Zustände wählen.")
        self.assertEqual(Gerat.objects.get(pk=gerat.pk).status, Gerat.STATUS_IN_BENUTZUNG)
        self.assertFalse(Protokoll.objects.filter(art=Protokoll.ART_RUECKNAHME).exists())
