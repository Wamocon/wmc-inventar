"""Startdaten für den Betrieb (N-11): Kategorien, ein Lagerort, ein Admin-Konto.

    ADMIN_EMAIL=... ADMIN_PASSWORT=... python manage.py startdaten

Die Checklisten stehen im Code (Protokoll.CHECKLISTE_PUNKTE, OFFBOARDING_PUNKTE). Die
verbindlichen Texte der Protokolle trägt die IT in den Einstellungen ein (FRM-001, FRM-002).
Vorhandenes bleibt unberührt, der Befehl lässt sich gefahrlos wiederholen.
"""
from __future__ import annotations

import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from konten.models import Konto
from stammdaten.models import Kategorie, Ort

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
        konto = Konto(email=email, rolle=Konto.ROLLE_ADMIN)
        try:
            validate_password(passwort, konto)
        except ValidationError as fehler:
            raise CommandError("Das Passwort reicht nicht: " + " ".join(fehler.messages)) from fehler
        konto.set_password(passwort)
        konto.save()
        self.stdout.write(f"Admin-Konto {email} angelegt")
