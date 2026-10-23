"""URLs der Anwendung.

TESTSCHNITTSTELLE Abschnitt 3 (Adressen).
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("", include("konten.urls")),
    path("", include("stammdaten.urls")),
    path("geraete/", include("geraete.urls")),
    path("admin/", admin.site.urls),
]
