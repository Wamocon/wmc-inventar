"""URLs für Geräte (M2 Bestand, M3 Lebenszyklus).

Die Seiten der Arbeitsplätze und der Raumplan liegen seit A-0076 (Teil 1)
direkt unter /arbeitsplaetze/, nicht mehr unter /geraete/arbeitsplaetze/
(TESTSCHNITTSTELLE Kapitel 3).
"""
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
    path("<slug:inventarnummer>/loeschen/", views.loeschen_zeigen, name="loeschen-zeigen"),
    path("<slug:inventarnummer>/loeschen/bestaetigen/", views.loeschen, name="loeschen"),
    # QR-Code und Etiketten (F-12, F-70 bis F-73, F-89)
    path("<slug:inventarnummer>/etikett/", views.etikett_drucken, name="etikett-drucken"),
]
