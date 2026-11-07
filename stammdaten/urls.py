"""URLs für Stammdaten: Kategorien, Personen, Orte (F-60, F-120, F-121)."""
from django.urls import path
from . import views

app_name = "stammdaten"

urlpatterns = [
    # Einstellungen (F-122, F-90, F-96, F-130, N-02) — M7 Teil 1 (A-0905)
    path("einstellungen/", views.einstellungen_sehen, name="einstellungen"),
    path("einstellungen/checklisten/", views.checklisten_pflegen, name="checklisten"),
    path("einstellungen/testmail/", views.einstellungen_testmail, name="einstellungen-testmail"),
    path("einstellungen/logo/", views.einstellungen_logo, name="einstellungen-logo"),
    # Kategorien (F-120)
    path("kategorien/", views.kategorien_liste, name="kategorien-liste"),
    path("kategorien/neu/", views.kategorien_anlegen, name="kategorien-anlegen"),
    path("kategorien/<int:pk>/aendern/", views.kategorien_aendern, name="kategorien-aendern"),
    path("kategorien/<int:pk>/loeschen/", views.kategorien_loeschen, name="kategorien-loeschen"),
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
    # Ausstattungsprofile (F-61)
    path("profile/", views.profile_liste, name="profile-liste"),
    path("profile/neu/", views.profil_anlegen, name="profil-anlegen"),
    path("profile/<int:pk>/aendern/", views.profil_aendern, name="profil-aendern"),
]
