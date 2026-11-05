"""Firmendaten aus den Einstellungen (F-122) für PDFs, Mails und Etiketten."""
from __future__ import annotations

from .models import Einstellungen


def firmendaten() -> dict:
    """Aktuelle Firmendaten aus /einstellungen/.

    Schlüssel: ``firmenname``, ``absenderzeile``, ``telefon``, ``email_it``,
    ``logo_name`` (Name in der DATEIABLAGE, sonst leer) und ``logo_pfad``
    (Pfad im Dateisystem, sonst leer). Leere Felder bleiben leer; hier steht
    bewusst kein Ersatzwert, denn feste Firmendaten gehören nicht in den Code.
    """
    e = Einstellungen.aktuelles()
    logo_name = e.logo.name if e.logo else ""
    return {
        "firmenname": e.firmenname,
        "absenderzeile": e.absenderzeile,
        "telefon": e.telefon,
        "email_it": e.email_it,
        "logo_name": logo_name,
        "logo_pfad": e.logo.path if logo_name else "",
    }
