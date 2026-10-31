"""URLs der Anwendung.

TESTSCHNITTSTELLE Abschnitt 3 (Adressen).
"""
from django.contrib import admin
from django.urls import path, include
from geraete import views as geraete_views
from geraete import import_views
from stammdaten import views as stammdaten_views

urlpatterns = [
    path("", include("konten.urls")),
    path("", include("stammdaten.urls")),
    # QR-Code: /g/<Inventarnummer> leitet zu /geraete/<Inventarnummer>/ weiter (F-70)
    path("g/<str:inventarnummer>/", geraete_views.gerat_kurz, name="gerat-kurz"),
    # Etiketten (F-72, F-89): /etiketten/ und /etiketten/auswahl/
    path("etiketten/", geraete_views.etiketten_ort, name="etiketten-ort"),
    path("etiketten/auswahl/", geraete_views.etiketten_auswahl, name="etiketten-auswahl"),
    path("geraete/", include("geraete.urls")),
    # M4 Arbeitsplätze und Raumplan (F-65 bis F-69, A-0076 Teil 1):
    # direkt unter /arbeitsplaetze/, unter /geraete/arbeitsplaetze/ bleibt nichts.
    path("arbeitsplaetze/", geraete_views.arbeitsplaetze, name="arbeitsplaetze-raumplan"),
    path("arbeitsplaetze/plan/<int:plan_id>/bearbeiten/", stammdaten_views.plan_bearbeiten, name="plan-bearbeiten"),
    path("arbeitsplaetze/liste/", geraete_views.arbeitsplaetze_liste, name="arbeitsplaetze-liste"),
    path("arbeitsplaetze/bedarf/", geraete_views.bedarf, name="bedarf"),
    path("arbeitsplaetze/pruefen/", geraete_views.erstinventur, name="erstinventur"),
    path("arbeitsplaetze/<slug:kennung>/", geraete_views.arbeitsplatz_detail, name="arbeitsplatz-detail"),
    path("arbeitsplaetze/<slug:kennung>/pruefen/", geraete_views.ort_pruefen, name="ort-pruefen"),
    path("arbeitsplaetze/<slug:kennung>/popup/", geraete_views.platz_popup, name="platz-popup"),
    path("arbeitsplaetze/raum/<slug:kennung>/popup/", geraete_views.raum_popup, name="raum-popup"),
    # Import (A-0113, F-80 bis F-84, F-86): Folge von Schritten, keine Ablage
    path("import/", import_views.import_seite, name="import"),
    path("import/datei/", import_views.import_datei, name="import-datei"),
    path("import/spalten/", import_views.import_spalten, name="import-spalten"),
    path("import/werte/", import_views.import_werte, name="import-werte"),
    path("import/vorschau.csv/", import_views.import_vorschau_csv, name="import-vorschau-csv"),
    path("admin/", admin.site.urls),
]
