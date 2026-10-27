"""URLs der Anwendung.

TESTSCHNITTSTELLE Abschnitt 3 (Adressen).
"""
from django.contrib import admin
from django.urls import path, include
from geraete import views as geraete_views

urlpatterns = [
    path("", include("konten.urls")),
    path("", include("stammdaten.urls")),
    path("geraete/", include("geraete.urls")),
    # M4 Arbeitsplätze und Raumplan (F-65 bis F-69, A-0076 Teil 1):
    # direkt unter /arbeitsplaetze/, unter /geraete/arbeitsplaetze/ bleibt nichts.
    path("arbeitsplaetze/", geraete_views.arbeitsplaetze, name="arbeitsplaetze-raumplan"),
    path("arbeitsplaetze/liste/", geraete_views.arbeitsplaetze_liste, name="arbeitsplaetze-liste"),
    path("arbeitsplaetze/bedarf/", geraete_views.bedarf, name="bedarf"),
    path("arbeitsplaetze/pruefen/", geraete_views.erstinventur, name="erstinventur"),
    path("arbeitsplaetze/<slug:kennung>/", geraete_views.arbeitsplatz_detail, name="arbeitsplatz-detail"),
    path("arbeitsplaetze/<slug:kennung>/pruefen/", geraete_views.ort_pruefen, name="ort-pruefen"),
    path("arbeitsplaetze/<slug:kennung>/popup/", geraete_views.platz_popup, name="platz-popup"),
    path("arbeitsplaetze/raum/<slug:kennung>/popup/", geraete_views.raum_popup, name="raum-popup"),
    path("admin/", admin.site.urls),
]
