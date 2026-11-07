"""TESTSCHNITTSTELLE Kapitel 1: manage.py testsiegel.

Legt ``var/testsiegel.p12`` (Passwort „testsiegel") und
``var/testsiegel.crt`` (PEM) an, nur im Entwicklungsmodus.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from geraete import siegel


class Command(BaseCommand):
    help = "Legt das Test-Siegel an: var/testsiegel.p12 und var/testsiegel.crt (F-138)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--neu",
            action="store_true",
            help="Existierende Dateien überschreiben.",
        )

    def handle(self, *args, **options):
        import os
        from pathlib import Path

        if not os.environ.get("INVENTAR_DEBUG", "").strip() in ("1", "true", "ja"):
            raise CommandError(
                "testsiegel ist nur im Entwicklungsmodus erlaubt (INVENTAR_DEBUG=1)."
            )

        var_dir = siegel.VAR_DIR
        p12_pfad = siegel.SIEGEL_P12
        crt_pfad = siegel.SIEGEL_CRT

        # Bestehende Dateien prüfen.
        if p12_pfad.exists() and not options.get("neu"):
            raise CommandError(
                f"{p12_pfad} existiert bereits. Benutze --neu zum Überschreiben."
            )

        # Siegel anlegen.
        p12_pfad, crt_pfad = siegel.testsiegel_anlegen()

        self.stdout.write(self.style.SUCCESS(
            f"Test-Siegel angelegt:\n"
            f"  {p12_pfad}\n"
            f"  {crt_pfad}\n"
            f"  Passwort: {siegel.SIEGEL_PASSWORT}"
        ))
