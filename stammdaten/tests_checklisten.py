"""Checklisten pflegen (Kapitel 3.2, Kapitel 6), Startdaten (N-11), Inventarnummer nie doppelt (F-14)."""
from django.test import TestCase

from geraete import pdf as pdf_modul
from geraete import services
from geraete.models import Gerat, Protokoll
from geraete.tests import konto_erstellen
from stammdaten import checklisten
from stammdaten.models import Checklistenpunkt, Kategorie, Ort, Person


class ChecklistenTests(TestCase):
    def setUp(self):
        self.admin = konto_erstellen("it.admin", "admin", "it-admin@beispiel.test")
        self.client.force_login(self.admin)
        self.kat = Kategorie.objects.create(name="Maus")
        self.lager = Ort.objects.create(typ=Ort.TYP_LAGER, kennung="LAGER")
        self.anna = Person.objects.create(anrede=Person.ANREDE_FRAU, vorname="Anna", nachname="Becker", email="anna@beispiel.test")

    def _punkt(self, liste, schluessel):
        return Checklistenpunkt.objects.get(liste=liste, schluessel=schluessel)

    def _speichern(self, liste, **werte):
        daten = {"liste": liste}
        for p in Checklistenpunkt.objects.filter(liste=liste):
            daten[f"reihenfolge-{p.pk}"] = p.reihenfolge
            daten[f"text-{p.pk}"] = p.text
            if p.aktiv:
                daten[f"aktiv-{p.pk}"] = "on"
        daten.update(werte)
        return self.client.post("/einstellungen/checklisten/", daten, follow=True)

    def _gerat(self, sn="SN-1"):
        return services.gerat_anlegen(kategorie=self.kat, hersteller="Logi", modell="M1", seriennummer=sn, ort=self.lager, erzeugt_von=self.admin)

    def test_vorbelegung_aus_den_vorlagen(self):
        self.assertEqual(Checklistenpunkt.objects.filter(liste="zugaenge").count(), 6)
        self.assertEqual(Checklistenpunkt.objects.filter(liste="offboarding").count(), 13)
        self.assertEqual(Protokoll.OFFBOARDING_PUNKTE[-1][0], checklisten.PUNKT_INVENTAR)
        self.assertEqual(Protokoll.CHECKLISTE_PUNKTE[0][0], "m365")

    def test_nur_der_admin_pflegt(self):
        self.assertEqual(self.client.get("/einstellungen/checklisten/").status_code, 200)
        leser = konto_erstellen("leser.k", "leser", "leser@beispiel.test")
        self.client.force_login(leser)
        self.assertEqual(self.client.get("/einstellungen/checklisten/").status_code, 403)
        self.assertEqual(self.client.post("/einstellungen/checklisten/", {"liste": "zugaenge", "neu": "x"}).status_code, 403)
        self.assertFalse(Checklistenpunkt.objects.filter(text="x").exists())

    def test_text_und_reihenfolge_wirken_im_protokoll(self):
        vpn = self._punkt("zugaenge", "vpn")
        self._speichern("zugaenge", **{f"text-{vpn.pk}": "VPN neu formuliert", f"reihenfolge-{vpn.pk}": 1})
        self.assertEqual(Protokoll.CHECKLISTE_PUNKTE[0], ("vpn", "VPN neu formuliert"))
        services.gerat_ausgeben(self._gerat(), self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        self.assertContains(self.client.get(f"/protokolle/{protokoll.nr}/"), "VPN neu formuliert")

    def test_inaktiver_punkt_entfaellt_und_blockiert_nicht(self):
        vpn = self._punkt("zugaenge", "vpn")
        daten = {"liste": "zugaenge"}
        for p in Checklistenpunkt.objects.filter(liste="zugaenge"):
            daten[f"reihenfolge-{p.pk}"] = p.reihenfolge
            daten[f"text-{p.pk}"] = p.text
            if p.pk != vpn.pk:
                daten[f"aktiv-{p.pk}"] = "on"
        self.client.post("/einstellungen/checklisten/", daten)
        services.gerat_ausgeben(self._gerat(), self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        self.assertEqual(len(protokoll.checkliste_unbeantwortet()), 5)
        self.assertNotContains(self.client.get(f"/protokolle/{protokoll.nr}/"), "VPN-Zugang")

    def test_neuer_punkt_erscheint_und_muss_beantwortet_werden(self):
        self._speichern("zugaenge", neu="Diensthandy eingerichtet")
        services.gerat_ausgeben(self._gerat(), self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        self.assertIn("Diensthandy eingerichtet", protokoll.checkliste_unbeantwortet())
        self.assertEqual(len(Protokoll.CHECKLISTE_PUNKTE), 7)

    def test_leerer_text_wird_abgelehnt(self):
        vpn = self._punkt("zugaenge", "vpn")
        antwort = self._speichern("zugaenge", **{f"text-{vpn.pk}": "   "})
        self.assertContains(antwort, 'data-test="fehler"')
        self.assertEqual(self._punkt("zugaenge", "vpn").text, vpn.text)

    def test_feste_punkte_bleiben_aktiv(self):
        fest = self._punkt("offboarding", checklisten.PUNKT_INVENTAR)
        daten = {"liste": "offboarding"}
        for p in Checklistenpunkt.objects.filter(liste="offboarding"):
            daten[f"reihenfolge-{p.pk}"] = p.reihenfolge
            daten[f"text-{p.pk}"] = p.text
        self.client.post("/einstellungen/checklisten/", daten)
        fest.refresh_from_db()
        self.assertTrue(fest.aktiv)
        self.assertEqual(Protokoll.OFFBOARDING_PUNKTE, (
            (checklisten.PUNKT_ZURUECKSETZEN, self._punkt("offboarding", checklisten.PUNKT_ZURUECKSETZEN).text),
            (checklisten.PUNKT_INVENTAR, fest.text),
        ))

    def test_vorbelegung_folgt_dem_schluessel_nicht_der_reihenfolge(self):
        fest = self._punkt("offboarding", checklisten.PUNKT_INVENTAR)
        Checklistenpunkt.objects.filter(pk=fest.pk).update(reihenfolge=1)
        gerat = self._gerat()
        services.gerat_ausgeben(gerat, self.anna, ausgefuehrt_von=self.admin)
        gerat.refresh_from_db()
        services.gerat_rueckgeben(gerat, zustand_rueckgabe=2, ausgefuehrt_von=self.admin)
        protokoll = Protokoll.objects.get(art=Protokoll.ART_RUECKNAHME)
        self.assertEqual(protokoll.offboarding[checklisten.PUNKT_INVENTAR]["status"], "erledigt")
        self.assertEqual(protokoll.offboarding[checklisten.PUNKT_ZURUECKSETZEN]["status"], "erledigt")
        self.assertEqual(protokoll.offboarding["ssh_api"]["status"], "nicht_zutreffend")

    def test_signiertes_protokoll_bleibt_wie_es_war(self):
        services.gerat_ausgeben(self._gerat(), self.anna, ausgefuehrt_von=self.admin, unterschrift="tool")
        protokoll = Protokoll.objects.get(art=Protokoll.ART_AUSGABE)
        for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
            protokoll.checkliste[schluessel] = 0
        protokoll.save()
        self.client.post(f"/protokolle/{protokoll.nr}/signieren/", {"passwort": "test-passwort-123"})
        protokoll.refresh_from_db()
        Checklistenpunkt.objects.filter(liste="zugaenge", schluessel="vpn").update(aktiv=False)
        self._speichern("zugaenge", neu="Neu nach der Signatur")
        seite = self.client.get(f"/protokolle/{protokoll.nr}/")
        self.assertContains(seite, "VPN-Zugang")
        self.assertNotContains(seite, "Neu nach der Signatur")
        text = pdf_modul.pdf_bauen(Protokoll.objects.get(pk=protokoll.pk))
        self.assertTrue(text.startswith(b"%PDF"))
        self.assertEqual(Protokoll.objects.get(pk=protokoll.pk).stand, Protokoll.STAND_GEGENZEICHNUNG_OFFEN)

    def test_startdaten_nach_flush(self):
        from io import StringIO
        from django.core.management import call_command
        Checklistenpunkt.objects.all().delete()
        call_command("startdaten", stdout=StringIO())
        self.assertEqual(Checklistenpunkt.objects.count(), 19)


class InventarnummerTests(TestCase):
    """F-14: Ein gedrucktes Etikett darf nie auf ein anderes Gerät passen."""

    def test_nummer_wird_nach_dem_loeschen_nicht_neu_vergeben(self):
        admin = konto_erstellen("it.admin", "admin", "it-admin@beispiel.test")
        self.client.force_login(admin)
        kat = Kategorie.objects.create(name="Maus")
        erstes = services.gerat_anlegen(kategorie=kat, hersteller="A", modell="B", seriennummer="S1", erzeugt_von=admin)
        zweites = services.gerat_anlegen(kategorie=kat, hersteller="A", modell="B", seriennummer="S2", erzeugt_von=admin)
        nummer = zweites.inventarnummer
        self.client.post(f"/geraete/{nummer}/loeschen/bestaetigen/")
        self.assertFalse(Gerat.objects.filter(inventarnummer=nummer).exists())
        drittes = services.gerat_anlegen(kategorie=kat, hersteller="A", modell="B", seriennummer="S3", erzeugt_von=admin)
        self.assertNotEqual(drittes.inventarnummer, nummer)
        self.assertGreater(drittes.inventarnummer, nummer)
        self.assertLess(erstes.inventarnummer, nummer)
