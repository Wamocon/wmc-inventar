"""Zeit in der Anwendung.

TESTSCHNITTSTELLE 1.2: Im Entwicklungsmodus gilt var/jetzt.txt (Format JJJJ-MM-TTTHH:MM
in Europe/Berlin) als aktuelle Zeit. Die Datei wird bei jeder Anfrage neu gelesen.
Ohne Entwicklungsmodus wird die Datei ignoriert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

_ROOT = Path(settings.BASE_DIR).resolve().parent
JETZT_DATEI = _ROOT / "var" / "jetzt.txt"

# Europe/Berlin
try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = timezone(timedelta(hours=2))


def entwicklungsmodus_aktiv() -> bool:
    """Gibt an, ob der Entwicklungsmodus aktiv ist (INVENTAR_DEBUG=1)."""
    return bool(getattr(settings, "DEBUG", False))


def jetzt_wie_im_entwicklungsmodus() -> datetime:
    """Liefert die aktuelle Zeit der Anwendung.

    Im Entwicklungsmodus: Inhalt von var/jetzt.txt, Format JJJJ-MM-TTTHH:MM, Europe/Berlin.
    Ohne Datei oder ohne Entwicklungsmodus: echte Zeit.
    """
    if entwicklungsmodus_aktiv() and JETZT_DATEI.exists():
        text = JETZT_DATEI.read_text(encoding="utf-8").strip()
        try:
            return datetime.strptime(text, "%Y-%m-%dT%H:%M")
        except ValueError:
            return datetime.now(_BERLIN)
    return datetime.now(_BERLIN)


def jetzt_aware() -> datetime:
    """Aktuelle Zeit mit Zeitzone (für Django-Felder)."""
    dt = jetzt_wie_im_entwicklungsmodus()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_BERLIN)
    return dt


def ist_vergangen(dt: datetime) -> bool:
    """Ist dt in der Vergangenheit (bezogen auf die Zeit der Anwendung)?"""
    return dt < jetzt_wie_im_entwicklungsmodus()


def ist_in_zukunft(dt: datetime) -> bool:
    """Liegt dt in der Zukunft (bezogen auf die Zeit der Anwendung)?"""
    return dt > jetzt_wie_im_entwicklungsmodus()


def ist_in_naechsten_tagen(dt: datetime, tage: int) -> bool:
    """Liegt dt innerhalb der nächsten `tage` Tage?"""
    jetzt = jetzt_wie_im_entwicklungsmodus()
    return jetzt <= dt <= (jetzt + timedelta(days=tage))


def ist_aelter_also_minuten(dt: datetime, minuten: int) -> bool:
    """Ist dt mindestens `minuten` Minuten in der Vergangenheit?"""
    return dt < (jetzt_wie_im_entwicklungsmodus() - timedelta(minutes=minuten))
