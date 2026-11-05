"""Mailversand: Backends und gemeinsame Regeln (F-90, F-96, TESTSCHNITTSTELLE 1.3).

``MailAblageBackend``: jede Mail als Datei in MAIL_ABLAGE. Dateiname
JJJJMMTT-HHMMSS-NNNN.eml mit der Zeit der Anwendung (Abschnitt 1.2) und einer
laufenden Nummer. Alphabetische Reihenfolge = Versandreihenfolge.
Inhalt: vollständige RFC-5322-Nachricht mit Anhängen.

``EinstellungenSmtpBackend``: Versand über die SMTP-Werte aus /einstellungen/.
"""
from __future__ import annotations

import email.utils
from pathlib import Path

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend
from django.core.mail.message import EmailMessage
from django.db.models import Q

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


class EinstellungenSmtpBackend(SmtpEmailBackend):
    """F-90: SMTP-Zugang aus den Einstellungen.

    Die Werte werden je Verbindung gelesen, eine Änderung wirkt ohne Neustart.
    Ohne SMTP-Server in den Einstellungen gilt die Umgebung (SMTP_HOST usw.).
    """

    def __init__(self, **kwargs):
        from stammdaten.models import Einstellungen

        e = Einstellungen.aktuelles()
        if e.smtp_server:
            ssl = e.smtp_tls and e.smtp_port == 465
            kwargs.update(
                host=e.smtp_server,
                port=e.smtp_port,
                username=e.smtp_benutzer,
                password=e.smtp_passwort,
                use_tls=e.smtp_tls and not ssl,
                use_ssl=ssl,
            )
        super().__init__(**kwargs)


def mail_absender() -> str:
    """F-90: Absender aller Mails: Einstellungen, sonst MAIL_ABSENDER der Umgebung."""
    from stammdaten.models import Einstellungen

    return Einstellungen.aktuelles().smtp_absender or settings.DEFAULT_FROM_EMAIL


def mail_signatur() -> str:
    """Schlusszeile der Mails aus den Einstellungen (F-122)."""
    from stammdaten.models import Einstellungen

    e = Einstellungen.aktuelles()
    return e.absenderzeile or e.firmenname


def link_ins_tool(pfad: str) -> str:
    """F-96, TESTSCHNITTSTELLE 1.3: Links in Mails sind absolut und beginnen mit BASIS_URL."""
    return f"{settings.BASIS_URL}{pfad}"


def konto_deaktiviert(adresse: str) -> bool:
    """F-96: Gehört die Adresse nur zu deaktivierten Konten?

    Zählt das Konto selbst und die Adresse der Person daran. Adressen ohne
    Konto (Person ohne Konto, Sammeladresse der IT) sind nicht betroffen.
    """
    from .models import Konto

    konten = Konto.objects.filter(
        Q(email__iexact=adresse) | Q(person__email__iexact=adresse)
    )
    return konten.exists() and not konten.filter(aktiv=True).exists()


def aktive_empfaenger(adressen) -> list[str]:
    """F-96: Keine Mails an deaktivierte Konten; leere Adressen fallen weg.

    Nicht für die Ausnahmen aus F-96 verwenden (Einmalcode, Link zur
    Gegenzeichnung, fertiges Protokoll): Sie gehen immer an die Person.
    """
    return [a for a in adressen if a and not konto_deaktiviert(a)]
