"""Mail-Backend: jede Mail als Datei in MAIL_ABLAGE (TESTSCHNITTSTELLE 1.3).

Dateiname JJJJMMTT-HHMMSS-NNNN.eml mit der Zeit der Anwendung (Abschnitt 1.2)
und einer laufenden Nummer. Alphabetische Reihenfolge = Versandreihenfolge.
Inhalt: vollständige RFC-5322-Nachricht mit Anhängen.
"""
from __future__ import annotations

import email.utils
from pathlib import Path

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage

from .zeit import entwicklungsmodus_aktiv, jetzt_wie_im_entwicklungsmodus


class MailAblageBackend(BaseEmailBackend):
    """Schreibt Mails als .eml-Dateien in das MAIL_ABLAGE-Verzeichnis."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ablage = getattr(settings, "MAIL_ABLAGE", "")
        if not ablage:
            raise RuntimeError("MAIL_ABLAGE ist nicht gesetzt.")
        self._ablage = Path(ablage)
        self._ablage.mkdir(parents=True, exist_ok=True)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        jetzt = jetzt_wie_im_entwicklungsmodus()
        stempel = jetzt.strftime("%Y%m%d-%H%M%S")
        zaehler = self._laeufige_nummer()
        gesendet = 0
        for msg in email_messages:
            num = f"{stempel}-{zaehler:04d}"
            zaehler += 1
            pfad = self._ablage / f"{num}.eml"
            pfad.write_bytes(msg.message().as_bytes())
            gesendet += 1
        return gesendet

    def _laeufige_nummer(self) -> int:
        """Zählt die bisherige Anzahl an Dateien (NNNN), startet bei 1."""
        if not self._ablage.exists():
            return 1
        dateien = list(self._ablage.glob("*.eml"))
        return len(dateien) + 1
