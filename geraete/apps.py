"""App-Konfiguration für Geräte (M2 Bestand)."""
from django.apps import AppConfig


class GeraeteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "geraete"
    verbose_name = "Geräte"
