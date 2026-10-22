"""URLs für Anmeldung, Konten, Passwort (F-01 bis F-05)."""
from django.urls import path
from . import views

app_name = "konten"

urlpatterns = [
    path("anmelden/", views.anmelden, name="anmelden"),
    path("abmelden/", views.abmelden, name="abmelden"),
    path("passwort-vergessen/", views.passwort_vergessen, name="passwort-vergessen"),
    path("passwort-setzen/<str:token>/", views.passwort_setzen, name="passwort-setzen"),
    path("konto/passwort/", views.passwort_aendern, name="passwort-aendern"),
]
