"""URLs für Stammdaten: Kategorien, Personen, Orte (F-60, F-120, F-121)."""
from django.urls import path
from . import views

app_name = "stammdaten"

urlpatterns = [
    # Kategorien (F-120)
    path("kategorien/", views.kategorien_liste, name="kategorien-liste"),
    path("kategorien/neu/", views.kategorien_anlegen, name="kategorien-anlegen"),
    path("kategorien/<int:pk>/aendern/", views.kategorien_aendern, name="kategorien-aendern"),
    # Personen (F-121)
    path("personen/", views.personen_liste, name="personen-liste"),
    path("personen/neu/", views.personen_anlegen, name="personen-anlegen"),
    path("personen/<int:pk>/", views.personen_detail, name="personen-detail"),
    path("personen/<int:pk>/offboarding/", views.offboarding, name="offboarding"),
    path("personen/<int:pk>/offboarding/zuruecknehmen/", views.offboarding_zuruecknehmen, name="offboarding-zuruecknehmen"),
    path("personen/<int:pk>/austritt/eintragen/", views.austritt_eintragen, name="austritt-eintragen"),
    path("personen/<int:pk>/austritt/speichern/", views.austritt_speichern, name="austritt-speichern"),
    path("personen/<int:pk>/aendern/", views.personen_aendern, name="personen-aendern"),
    # Orte (F-60)
    path("orte/", views.orte_liste, name="orte-liste"),
    path("orte/neu/", views.orte_anlegen, name="orte-anlegen"),
    path("orte/<int:pk>/aendern/", views.orte_aendern, name="orte-aendern"),
]
