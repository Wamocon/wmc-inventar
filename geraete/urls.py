"""URLs für Geräte (M2 Bestand, M3 Lebenszyklus)."""
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
    # M3 Lebenszyklus
    path("<slug:inventarnummer>/ausgeben/", views.ausgeben, name="ausgeben"),
    path("<slug:inventarnummer>/rueckgeben/", views.rueckgeben, name="rueckgeben"),
    path("<slug:inventarnummer>/umziehen/", views.umziehen, name="umziehen"),
    path("<slug:inventarnummer>/reparatur/start/", views.reparatur_start, name="reparatur-start"),
    path("<slug:inventarnummer>/reparatur/fertig/", views.reparatur_fertig, name="reparatur-fertig"),
    path("<slug:inventarnummer>/ausmustern/", views.ausmustern, name="ausmustern"),
    # M4 Arbeitsplätze
    path("arbeitsplaetze/", views.arbeitsplaetze_liste, name="arbeitsplaetze"),
    path("arbeitsplaetze/bedarf/", views.bedarf, name="bedarf"),
    path("erstinventur/", views.erstinventur, name="erstinventur"),
    path("arbeitsplaetze/<int:pk>/", views.arbeitsplatz_detail, name="arbeitsplatz-detail"),
    path("arbeitsplaetze/<int:pk>/pruefen/", views.ort_pruefen, name="ort-pruefen"),
]
