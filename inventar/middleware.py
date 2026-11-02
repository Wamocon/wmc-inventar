"""Mittelschicht: sendet die Content-Security-Policy auf jeder Antwort.

N-02 (docs/anforderungen.md): „Sicherheitsheader. … Content-Security-Policy
ohne Inline-Skripte." Die CSP-Werte stehen in ``settings.CSP``.
"""

from django.conf import settings


class CSPMiddleware:
    """Setzt den HTTP-Kopf ``Content-Security-Policy`` auf jeder Antwort."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        antwort = self.get_response(request)
        antwort.headers.setdefault("Content-Security-Policy", settings.CSP)
        return antwort
