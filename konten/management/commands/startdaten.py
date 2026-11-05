"""Startdaten für den Betrieb (N-11): Kategorien, Checklisten, ein Lagerort, ein Admin-Konto.

    ADMIN_EMAIL=... ADMIN_PASSWORT=... python manage.py startdaten

Die verbindlichen Texte der Protokolle trägt die IT in den Einstellungen ein (FRM-001, FRM-002).
Vorhandenes bleibt unberührt, der Befehl lässt sich gefahrlos wiederholen.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from konten.forms import MIN_PASSWORT_LAENGE
from konten.models import Konto
from stammdaten.checklisten import vorbelegen
from stammdaten.models import Kategorie, Ort, Person

from .beispieldaten import KATEGORIEN


class Command(BaseCommand):
    help = "Legt Kategorien, einen Lagerort und das erste Admin-Konto an."

    def add_arguments(self, parser):
        parser.add_argument("--lager", default="LAGER", help="Kennung des ersten Lagerorts")

    def handle(self, *args, **optionen):
        neu = 0
        for name, datentraeger, seriennummer in KATEGORIEN:
            _, angelegt = Kategorie.objects.get_or_create(
                name=name,
                defaults={"hat_datentraeger": datentraeger, "seriennummer_pflicht": seriennummer},
            )
            neu += angelegt
        self.stdout.write(f"Kategorien: {neu} neu, {Kategorie.objects.count()} insgesamt")
        self.stdout.write(f"Checklistenpunkte: {vorbelegen()} neu")

        if not Ort.objects.filter(typ=Ort.TYP_LAGER).exists():
            Ort.objects.create(typ=Ort.TYP_LAGER, kennung=optionen["lager"], name="Lager")
            self.stdout.write(f"Lagerort {optionen['lager']} angelegt")

        if Konto.objects.filter(rolle=Konto.ROLLE_ADMIN).exists():
            self.stdout.write("Admin-Konto vorhanden, nichts geändert")
            return
        email = os.environ.get("ADMIN_EMAIL", "").strip()
        passwort = os.environ.get("ADMIN_PASSWORT", "")
        if not email or not passwort:
            raise CommandError("Für das erste Admin-Konto fehlen ADMIN_EMAIL und ADMIN_PASSWORT.")
        if len(passwort) < MIN_PASSWORT_LAENGE:
            raise CommandError(f"Das Passwort muss mindestens {MIN_PASSWORT_LAENGE} Zeichen lang sein.")
        konto = Konto(email=email, rolle=Konto.ROLLE_ADMIN)
        # Ohne Person stünde im Protokoll als Bearbeiter die Mailadresse.
        vorname, nachname = os.environ.get("ADMIN_VORNAME", "").strip(), os.environ.get("ADMIN_NACHNAME", "").strip()
        if vorname and nachname:
            konto.person = Person.objects.create(vorname=vorname, nachname=nachname, email=email, anrede="")
        konto.set_password(passwort)
        konto.save()
        self.stdout.write(f"Admin-Konto {email} angelegt")
