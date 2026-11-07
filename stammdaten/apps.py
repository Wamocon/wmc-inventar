"""App-Konfiguration für Stammdaten."""
from django.apps import AppConfig


class StammdatenConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stammdaten"
    verbose_name = "Stammdaten"
