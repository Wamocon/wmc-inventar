"""Beispieldaten anlegen (TESTSCHNITTSTELLE Abschnitt 2).

Legt Konten, Personen, Kategorien, Profile, Orte und Einstellungen an.
Bricht ab, wenn die Datenbank schon Konten hat.
Mit --neu werden vorher Datenbankinhalt, DATEIABLAGE, MAIL_ABLAGE und var/jetzt.txt geleert.
Läuft nur im Entwicklungsmodus.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from konten.models import Konto
from stammdaten.models import Ausstattungsprofil, Kategorie, Ort, Person, Profilposition
from geraete import services
from geraete.models import Gerat


# Kategorien nach Kapitel 3.2 der Anforderungen (TESTSCHNITTSTELLE 2)
KATEGORIEN = [
    ("Notebook", True, True),
    ("Desktop-PC", True, True),
    ("Monitor", False, False),
    ("Dockingstation", False, False),
    ("Notebook-Ständer", False, False),
    ("Tastatur", False, False),
    ("Maus", False, False),
    ("Headset", False, False),
    ("Webcam", False, False),
    ("Konferenzsystem", False, False),
    ("Smartphone", True, True),
    ("Tablet", True, True),
    ("Smartwatch", True, True),
    ("Kamera und Video", True, True),
    ("Powerbank", False, False),
    ("USB-Hub", False, False),
    ("NAS", True, True),
    ("Drucker", True, True),
    ("Netzwerkgerät", False, False),
    ("Fernseher", False, False),
    ("Sonstiges", False, False),
]

# Konten (TESTSCHNITTSTELLE 2)
KONTEN = [
    ("it-admin@beispiel.test", Konto.ROLLE_ADMIN, "Tobias Klein", "IT", "WMC-WP-09"),
    ("gf@beispiel.test", Konto.ROLLE_LESER, "Martin Albers", "Geschäftsführung", "WMC-WP-13"),
    ("anna.becker@beispiel.test", Konto.ROLLE_MITARBEITER, "Anna Becker", "Testmanagement", "WMC-WP-01"),
    ("felix.hoffmann@beispiel.test", Konto.ROLLE_MITARBEITER, "Felix Hoffmann", "Testmanagement", "WMC-WP-02"),
]

# Weitere Personen ohne Konto (TESTSCHNITTSTELLE 2)
PERSONEN_OHNE_KONTO = [
    ("Jonas Weber", "Entwicklung", "WMC-WP-03"),
    ("Elena Petrova", "Entwicklung", "WMC-WP-04"),
    ("David Neumann", "Testautomatisierung", "WMC-WP-05"),
    ("Murat Yılmaz", "Testautomatisierung", "WMC-WP-06"),
    ("Sophie Wagner", "Vertrieb", "WMC-WP-07"),
    ("Marie Richter", "Buchhaltung", "WMC-WP-08"),
    ("Kai Brandt", "IT", "WMC-WP-10"),
    ("Leonie Schmitt", "Academy", "WMC-WP-11"),
    ("Lena Wolf", "Academy", "WMC-WP-12"),
    ("Paul Schröder", "Vertrieb", None),
]

# Ausstattungsprofile (TESTSCHNITTSTELLE 2)
PROFILE = [
    ("Standard", [("Monitor", 2), ("Dockingstation", 1), ("Tastatur", 1), ("Maus", 1), ("Headset", 1)]),
    ("Entwicklung", [("Monitor", 2), ("Dockingstation", 1), ("Tastatur", 1), ("Maus", 1), ("Headset", 1), ("Webcam", 1)]),
    ("Studio", [("Monitor", 2), ("Dockingstation", 1), ("Tastatur", 1), ("Maus", 1), ("Headset", 1), ("Webcam", 1)]),
]

# Arbeitsplätze (TESTSCHNITTSTELLE 2)
ARBEITSPLAETZE = [
    ("WMC-WP-01", "Großraumbüro", "Anna Becker", "Standard", 50.1, 55.6),
    ("WMC-WP-02", "Großraumbüro", "Felix Hoffmann", "Standard", 64.1, 55.6),
    ("WMC-WP-03", "Großraumbüro", "Jonas Weber", "Entwicklung", 50.1, 61.3),
    ("WMC-WP-04", "Großraumbüro", "Elena Petrova", "Entwicklung", 64.1, 61.3),
    ("WMC-WP-05", "Großraumbüro", "David Neumann", "Entwicklung", 50.1, 69.3),
    ("WMC-WP-06", "Großraumbüro", "Murat Yılmaz", "Standard", 64.1, 69.3),
    ("WMC-WP-07", "Großraumbüro", "Sophie Wagner", "Standard", 50.1, 75.1),
    ("WMC-WP-08", "Großraumbüro", "Marie Richter", "Standard", 64.1, 75.1),
    ("WMC-WP-09", "Großraumbüro", "Tobias Klein", "Standard", 50.1, 83.1),
    ("WMC-WP-10", "Großraumbüro", "Kai Brandt", "Standard", 64.1, 83.1),
    ("WMC-WP-11", "Großraumbüro", "Leonie Schmitt", "Standard", 50.1, 88.9),
    ("WMC-WP-12", "Großraumbüro", "Lena Wolf", "Standard", 64.1, 88.9),
    ("WMC-WP-13", "Büro Geschäftsführung", "Martin Albers", "Standard", 10.4, 62.7),
    ("WMC-WP-14", "Büro Geschäftsführung", None, "Standard", 24.3, 62.7),
    ("WMC-WP-15", "Studio", None, "Studio", 10.7, 77.3),
]

# Orte vom Typ Raum (TESTSCHNITTSTELLE 2)
RAEUME = [
    ("STUDIO-TECHNIK", "Studiotechnik", "Studio", 24.1, 87.3),
    ("ACADEMY-TECHNIK", "Academy-Technik", "Academy-Raum", 77.4, 36.9),
    ("SERVER-TECHNIK", "Serverschrank", "Serverraum", 24.6, 30.3),
    ("EINGANG", "Eingangsbereich", "Großraumbüro", 44.6, 44.7),
]

# Lagerort (TESTSCHNITTSTELLE 2)
LAGERORT = ("LAGER-EG", "IT-Lager")

# Raumplan (TESTSCHNITTSTELLE 2, F-65 bis F-67):
# Plan je Standort und Etage. Der Grundriss kommt aus docs/vorlagen/
# und wird nach der DATEIABLAGE kopiert.
PLAN = {
    "standort": "Eschborn",
    "etage": "1. OG",
    "grundriss_datei": "grundriss_eschborn_1og.svg",
    "ablage_ordner": "grundrisse",
}

# Geräte je Arbeitsplatz (TESTSCHNITTSTELLE 2, F-45)
GERATEJE_PLATZ = [
    ("Notebook", "Lenovo", "ThinkPad X1 Carbon"),
    ("Display", "Dell", "U2723QE"),
    ("Headset", "Logitech", "Zone 2"),
    ("Dokumenten-Scanner", "Epson", "DS-770 II"),
    ("WLAN-USB-Stick", "Intel", "AX200"),
]


def _vorname(nachname_vorname: str) -> str:
    return nachname_vorname.split()[0] if nachname_vorname else ""


def _nachname(nachname_vorname: str) -> str:
    return nachname_vorname.split()[-1] if nachname_vorname else ""


def _kuerzel(nachname_vorname: str) -> str:
    teile = nachname_vorname.split()
    if len(teile) >= 2:
        return (teile[0][0] + teile[-1][0]).upper()
    return teile[0][0].upper() if teile else ""


def _anrede(vorname: str) -> str:
    # N-04: Anrede nach Vorname (Herr oder Frau) – vereinfacht, da die
    # Anrede im Beispieldatensatz nicht explizit festgelegt ist.
    # Für die bekannten Namen (TESTSCHNITTSTELLE 2) gibt es eine feste Zuordnung.
    frau = {"Anna", "Elena", "Sophie", "Marie", "Leonie", "Lena"}
    return "Frau" if vorname in frau else "Herr"


class Command(BaseCommand):
    help = "Legt Beispieldaten an (Konten, Personen, Kategorien, Profile, Orte)."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="Leert vorher die Datenbank und Ablagen.")
        parser.add_argument("--demo", action="store_true", help="Zusätzlich einen Demobestand anlegen (TESTSCHNITTSTELLE 2).")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("beispieldaten läuft nur im Entwicklungsmodus (INVENTAR_DEBUG=1).")

        if opts["neu"]:
            self._leeren()

        if Konto.objects.exists():
            raise CommandError("Die Datenbank enthält bereits Konten. Mit --neu neu beginnen.")

        with transaction.atomic():
            self._anlegen_kategorien()
            self._anlegen_profile()
            self._anlegen_orte()
            self._anlegen_personen()
            self._anlegen_konten()
            self._anlegen_geraete()
            self._anlegen_einstellungen()

        self.stdout.write(self.style.SUCCESS("Beispieldaten angelegt."))

    def _leeren(self):
        from django.db import connection
        # Tabellen in der Reihenfolge der Fremdschlüssel leeren (Werkbank 23.10.):
        # zuerst die Tabellen, die auf andere verweisen, dann die Referenzierten.
        for tabelle in (
            "geraete_geratkonflikt",   # FK → geraete_gerat
            "geraete_vorgang",         # FK → geraete_gerat, konten_konto, stammdaten_person
            "geraete_gerat",          # FK → konten_konto, stammdaten_*
            "geraete_importlauf",     # FK → konten_konto
            "konten_konto",          # FK → stammdaten_person
            "stammdaten_profilposition",  # FK → stammdaten_ausstattungsprofil, stammdaten_kategorie
            "stammdaten_ort",        # FK → stammdaten_person, stammdaten_ausstattungsprofil
            "stammdaten_person",
            "stammdaten_ausstattungsprofil",
            "stammdaten_kategorie",
            "stammdaten_plan",       # A-0076: Raumplan
        ):
            connection.cursor().execute(f"DELETE FROM {tabelle}")

        for var in ("DATEIABLAGE", "MAIL_ABLAGE"):
            p = getattr(settings, var, "")
            if p:
                pfad = Path(p)
                if pfad.exists():
                    for kind in [f for f in pfad.iterdir()]:
                        if kind.is_dir():
                            import shutil
                            shutil.rmtree(kind)
                        else:
                            kind.unlink()

        jetzt_pfad = Path(settings.ROOT_DIR) / "var" / "jetzt.txt"
        if jetzt_pfad.exists():
            jetzt_pfad.unlink()

    def _anlegen_kategorien(self):
        for name, datentraeger, seriennummer in KATEGORIEN:
            Kategorie.objects.create(
                name=name,
                hat_datentraeger=datentraeger,
                seriennummer_pflicht=seriennummer,
            )
        self.stdout.write(f"  {len(KATEGORIEN)} Kategorien")

    def _anlegen_profile(self):
        for name, positionen in PROFILE:
            profil = Ausstattungsprofil.objects.create(name=name)
            for kat_name, anz in positionen:
                kat = Kategorie.objects.get(name=kat_name)
                Profilposition.objects.create(profil=profil, kategorie=kat, anzahl=anz)
        self.stdout.write(f"  {len(PROFILE)} Profile")

    def _anlegen_orte(self):
        # A-0106: Plan erstellen, damit Orte ihm zugeordnet werden können
        plan = self._anlegen_plan()

        for kennung, raum, person, profil_name, x, y in ARBEITSPLAETZE:
            profil = Ausstattungsprofil.objects.get(name=profil_name) if profil_name else None
            fest_person = None
            if person:
                fest_person = Person.objects.filter(nachname=_nachname(person), vorname=_vorname(person)).first()
            Ort.objects.create(
                typ=Ort.TYP_ARBEITSPLATZ,
                kennung=kennung,
                name=kennung,
                standort="Eschborn",
                raum=raum,
                profil=profil,
                feste_person=fest_person,
                position_x=x,
                position_y=y,
                plan_id=plan.id,
            )
        for kennung, name, raum, x, y in RAEUME:
            Ort.objects.create(
                typ=Ort.TYP_RAUM,
                kennung=kennung,
                name=name,
                standort="Eschborn",
                raum=raum,
                position_x=x,
                position_y=y,
                plan_id=plan.id,
            )
        kennung, name = LAGERORT
        Ort.objects.create(
            typ=Ort.TYP_LAGER,
            kennung=kennung,
            name=name,
            standort="Eschborn",
        )
        self.stdout.write(f"  {len(ARBEITSPLAETZE)} Arbeitsplätze, {len(RAEUME)} Räume, 1 Lagerort")

    def _anlegen_plan(self):
        """Raumplan: Eschborn, 1. OG, mit Grundriss (TESTSCHNITTSTELLE 2, F-65).

        Der Grundriss liegt unter docs/vorlagen/ und wird in die DATEIABLAGE
        kopiert; die Datei wird über das FileField im Modell ``Plan`` gespeichert.
        """
        from django.core.files.base import ContentFile
        from stammdaten.models import Plan

        grundriss_name = PLAN["grundriss_datei"]
        quelle = Path(settings.ROOT_DIR) / "docs" / "vorlagen" / grundriss_name

        plan = Plan(standort=PLAN["standort"], etage=PLAN["etage"])
        if quelle.exists():
            with open(quelle, "rb") as f:
                plan.grundriss.save(grundriss_name, ContentFile(f.read()), save=False)
        plan.save()
        self.stdout.write(f"  1 Raumplan ({PLAN['standort']}, {PLAN['etage']})")
        return plan

    def _anlegen_personen(self):
        eintritt = date(2024, 1, 1)
        # Personen mit Konto
        for email, rolle, name, abteilung, _ in KONTEN:
            vorname = _vorname(name)
            nachname = _nachname(name)
            email_person = f"{vorname.lower()}.{nachname.lower()}@beispiel.test"
            if nachname == "Albers":
                email_person = "gf@beispiel.test"
            Person.objects.create(
                anrede=_anrede(vorname),
                vorname=vorname,
                nachname=nachname,
                email=email_person,
                abteilung=abteilung,
                eintritt=eintritt,
                anschrift="Beispielweg 3, 65760 Eschborn" if vorname == "Anna" else "",
            )
        # Personen ohne Konto
        for name, abteilung, _ in PERSONEN_OHNE_KONTO:
            vorname = _vorname(name)
            nachname = _nachname(name)
            email_person = f"{vorname.lower()}.{nachname.lower()}@beispiel.test"
            if vorname == "Murat":
                email_person = "murat.yilmaz@beispiel.test"
            eintritt_p = date(2024, 1, 1)
            if vorname == "Felix":
                eintritt_p = date(2025, 9, 15)
            Person.objects.create(
                anrede=_anrede(vorname),
                vorname=vorname,
                nachname=nachname,
                email=email_person,
                abteilung=abteilung,
                eintritt=eintritt_p,
            )
        self.stdout.write(f"  {len(KONTEN) + len(PERSONEN_OHNE_KONTO)} Personen")

    def _anlegen_konten(self):
        passwort = settings.BEISPIEL_PASSWORT
        for email, rolle, name, abteilung, _ in KONTEN:
            vorname = _vorname(name)
            nachname = _nachname(name)
            person = Person.objects.filter(vorname=vorname, nachname=nachname).first()
            Konto.objects.create(
                email=email,
                rolle=rolle,
                person=person,
                aktiv=True,
            )
            # Passwort setzen
            konto = Konto.objects.get(email=email)
            konto.set_password(passwort)
            konto.save(update_fields=["password"])
        self.stdout.write(f"  {len(KONTEN)} Konten")

    def _anlegen_geraete(self):
        """Geräte je Arbeitsplatz (TESTSCHNITTSTELLE 2, F-45).

        Feste Zuordnung: jede Person, die einen festen Platz hat, bekommt
        die Geräte des Platzes. Die Inventarnummer wird fortlaufend vergeben.
        """
        for kennung, _raum, person_name, _profil, _x, _y in ARBEITSPLAETZE:
            if not person_name:
                continue
            person = Person.objects.filter(
                vorname=_vorname(person_name), nachname=_nachname(person_name)
            ).first()
            if person is None:
                continue
            ort = Ort.objects.get(kennung=kennung)
            for kat_name, hersteller, modell in GERATEJE_PLATZ:
                kategorie = Kategorie.objects.filter(name=kat_name).first()
                if kategorie is None:
                    continue
                gerat = services.gerat_anlegen(
                    kategorie=kategorie,
                    hersteller=hersteller,
                    modell=modell,
                    seriennummer=f"SN-{kennung}-{kat_name[:3].upper()}",
                    person=person,
                    erzeugt_von=Konto.objects.filter(rolle=Konto.ROLLE_ADMIN).first(),
                )
        self.stdout.write(f"  {Gerat.objects.count()} Geräte")

    def _anlegen_einstellungen(self):
        # F-122: Einstellungen (TESTSCHNITTSTELLE 2)
        # In M1 noch kein eigenes Modell für Einstellungen – die Werte
        # stehen in den Variablen der Anwendung und werden in M7 ausgeführt.
        self.stdout.write("  Einstellungen (F-122) in M7 umgesetzt")
