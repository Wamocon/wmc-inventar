"""URLs der Anwendung.

TESTSCHNITTSTELLE Abschnitt 3 (Adressen).
"""
from django.urls import path, include
from geraete import views as geraete_views
from geraete import import_views
from geraete import uebersicht as uebersicht_views
from stammdaten import views as stammdaten_views

urlpatterns = [
    # M7 Teil 3 (A-0907): Übersicht / für Admin und Leser (F-100 bis F-104).
    # Steht vor den includes, damit der neue Stand die alte Startseite ablöst.
    path("", uebersicht_views.uebersicht, name="uebersicht"),
    path("exporte/", uebersicht_views.liste_export, name="uebersicht-export"),
    path("api/kennzahlen", uebersicht_views.api_kennzahlen, name="api-kennzahlen"),
    path("", include("konten.urls")),
    path("", include("stammdaten.urls")),
    # QR-Code: /g/<Inventarnummer> leitet zu /geraete/<Inventarnummer>/ weiter (F-70)
    path("g/<str:inventarnummer>", geraete_views.gerat_kurz, name="gerat-kurz"),
    # Etiketten (F-72, F-89): /etiketten/ und /etiketten/auswahl/
    path("etiketten/", geraete_views.etiketten_ort, name="etiketten-ort"),
    path("etiketten/auswahl/", geraete_views.etiketten_auswahl, name="etiketten-auswahl"),
    path("geraete/", include("geraete.urls")),
    # M4 Arbeitsplätze und Raumplan (F-65 bis F-69, A-0076 Teil 1):
    # direkt unter /arbeitsplaetze/, unter /geraete/arbeitsplaetze/ bleibt nichts.
    path("arbeitsplaetze/", geraete_views.arbeitsplaetze, name="arbeitsplaetze-raumplan"),
    path("arbeitsplaetze/plan/<int:plan_id>/bearbeiten/", stammdaten_views.plan_bearbeiten, name="plan-bearbeiten"),
    path("arbeitsplaetze/plan/<int:plan_id>/grundriss/", geraete_views.grundriss_zeige, name="plan-grundriss"),
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
    path("import/speichern/", import_views.import_speichern_view, name="import-speichern"),
    # M5 Verleih (F-36): /verleih/ – Leihen-Übersicht, nur Admin
    path("verleih/", geraete_views.verleih_liste, name="verleih-liste"),
    # M5 Teil 2: Meine Geräte (F-95, F-112, F-31, F-37)
    # direkt unter /meine-geraete/ (TESTSCHNITTSTELLE Kapitel 3)
    path("meine-geraete/", geraete_views.meine_geraete_zeige, name="meine_geraete"),
    path("meine-geraete/leihe/neu/", geraete_views.meine_geraete_leihe_neu, name="meine_geraete_leihe_neu"),
    path("meine-geraete/leihe/frei/", geraete_views.meine_geraete_leihe_frei, name="meine_geraete_leihe_frei"),
    path("meine-geraete/leihe/<int:leih_id>/zurueckziehen/", geraete_views.meine_geraete_leihe_zurueckziehen, name="meine_geraete_leihe_zurueckziehen"),
    path("meine-geraete/leihe/<int:leih_id>/verlaengern/", geraete_views.meine_geraete_leihe_verlaengern, name="meine_geraete_leihe_verlaengern"),
    # M6 Teil 1: Protokoll (F-130, F-132, F-133, F-134, F-22)
    path("protokolle/<str:protokoll_nr>/", geraete_views.protokoll_detail, name="protokoll-detail"),
    path("protokolle/<str:protokoll_nr>/pdf/", geraete_views.protokoll_pdf, name="protokoll-pdf"),
    path("protokolle/<str:protokoll_nr>/foto/", geraete_views.protokoll_foto_hochladen, name="protokoll-foto"),
    path("protokolle/<str:protokoll_nr>/scan/", geraete_views.protokoll_scan_hochladen, name="protokoll-scan"),
    path("protokolle/<str:protokoll_nr>/checkliste/", geraete_views.protokoll_checkliste_beantworten, name="protokoll-checkliste"),
    path("protokolle/<str:protokoll_nr>/offboarding/", geraete_views.protokoll_offboarding_beantworten, name="protokoll-offboarding"),
    # M6 Teil 2: Signatur, Gegenzeichnung (F-135, F-136, F-137, F-141)
    path("protokolle/<str:protokoll_nr>/signieren/", geraete_views.protokoll_signieren, name="protokoll-signieren"),
    path("protokolle/<str:protokoll_nr>/abbrechen/", geraete_views.protokoll_abbrechen, name="protokoll-abbrechen"),
    path("protokolle/<str:protokoll_nr>/code-senden/", geraete_views.protokoll_code_senden, name="protokoll-code-senden"),
    path("protokolle/<str:protokoll_nr>/korrigieren/", geraete_views.protokoll_korrigieren, name="protokoll-korrigieren"),
    # F-140 (M6 Teil 3): Abgelaufener Link neu senden.
    path("protokolle/<str:protokoll_nr>/link-neu-senden/", geraete_views.protokoll_link_neu_senden, name="protokoll-link-neu-senden"),
    path("signieren/<str:token>/code-senden/", geraete_views.signieren_code_senden, name="signieren-code-senden"),
    path("signieren/<str:token>/pdf/", geraete_views.signieren_pdf, name="signieren-pdf"),
    path("signieren/<str:token>/", geraete_views.signieren_link, name="signieren-link"),
]
