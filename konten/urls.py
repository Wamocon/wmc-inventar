"""URLs für Anmeldung, Konten, Passwort (F-01 bis F-05)."""
from django.urls import path
from . import views

app_name = "konten"

urlpatterns = [
    # Die Übersicht / wurde mit M7 Teil 3 (A-0907) nach geraete.uebersicht verlegt.
    path("anmelden/", views.anmelden, name="anmelden"),
    path("abmelden/", views.abmelden, name="abmelden"),
    path("passwort-vergessen/", views.passwort_vergessen, name="passwort-vergessen"),
    path("passwort-setzen/<str:token>/", views.passwort_setzen, name="passwort-setzen"),
    path("konto/passwort/", views.passwort_aendern, name="passwort-aendern"),
    # Konten verwalten (F-02): nur Admin
    path("konten/", views.konten_liste, name="konten-liste"),
    path("konten/neu/", views.konto_anlegen, name="konto-anlegen"),
    path("konten/<int:pk>/", views.konto_aendern, name="konto-aendern"),
]
