"""Mittelschichten: Content-Security-Policy und Anmeldezwang.

N-02 (docs/anforderungen.md): „Sicherheitsheader. … Content-Security-Policy
ohne Inline-Skripte." Die CSP-Werte stehen in ``settings.CSP``.

TESTSCHNITTSTELLE 3: Ohne Anmeldung leitet jede Seite auf ``/anmelden/?next=…`` um,
außer Anmeldung, Passwort vergessen, Passwort setzen, Gegenzeichnung und
``/api/kennzahlen``. F-02: Ein deaktiviertes Konto verliert auch seine laufende Sitzung.
"""
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect

from konten.zeit import jetzt_aware

OHNE_ANMELDUNG = (
    "/anmelden/",
    "/passwort-vergessen/",
    "/passwort-setzen/",
    "/signieren/",
    "/api/kennzahlen",
    "/static/",
)


class CSPMiddleware:
    """Setzt den HTTP-Kopf ``Content-Security-Policy`` auf jeder Antwort."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        antwort = self.get_response(request)
        antwort.headers.setdefault("Content-Security-Policy", settings.CSP)
        return antwort


class AnmeldungMiddleware:
    """Anmeldezwang für alle Seiten; deaktivierte Konten werden abgemeldet."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.aktiv:
            logout(request)
        if request.user.is_authenticated:
            # F-05: nach der Uhr der Anwendung (Testschnittstelle 1.2); das Cookie allein kennt nur die echte Zeit.
            jetzt = jetzt_aware()
            zuletzt = request.session.get("zuletzt_aktiv")
            if zuletzt and (jetzt - datetime.fromisoformat(zuletzt)).total_seconds() > settings.SESSION_COOKIE_AGE:
                logout(request)
            else:
                request.session["zuletzt_aktiv"] = jetzt.isoformat()
        if not request.user.is_authenticated and not request.path.startswith(OHNE_ANMELDUNG):
            ziel = urlencode({"next": request.get_full_path()})
            return redirect(f"{settings.LOGIN_URL}?{ziel}")
        return self.get_response(request)
