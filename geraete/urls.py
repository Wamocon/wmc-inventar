"""URLs für Geräte (M2 Bestand)."""
from django.urls import path
from . import views

app_name = "geraete"

urlpatterns = [
    path("neu/", views.neu_anzeigen, name="neu"),
    path("speichern/", views.neu_anlegen, name="speichern"),
    path("", views.liste, name="liste"),
    path("<slug:inventarnummer>/", views.detail, name="detail"),
    path("<slug:inventarnummer>/aendern/", views.bearbeiten, name="aendern"),
    path("<slug:inventarnummer>/pruefen/", views.pruefen, name="pruefen"),
    path("<slug:inventarnummer>/konflikt/<int:konflikt_id>/loesen/", views.konflikt_loesen, name="konflikt-loesen"),
]
