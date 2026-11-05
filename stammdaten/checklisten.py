"""Checklisten als Daten (Kapitel 3.2, Kapitel 6, N-11).

Vorbelegung aus den Vorlagen, Wortlaut aus ``docs/vorlagen/FRM-001.md`` und ``FRM-002.md``
(F-132, F-133). Die IT pflegt Text, Reihenfolge und „aktiv“ unter ``/einstellungen/checklisten/``.
Zwei Prüfpunkte setzt das Tool selbst vor, sie bleiben immer aktiv.
"""
from __future__ import annotations

ZUGAENGE = "zugaenge"
OFFBOARDING = "offboarding"

PUNKT_ZURUECKSETZEN = "werkseinstellung"
PUNKT_INVENTAR = "inventar_dokumentiert"
FESTE_PUNKTE = {(OFFBOARDING, PUNKT_ZURUECKSETZEN), (OFFBOARDING, PUNKT_INVENTAR)}

VORBELEGUNG = {
    ZUGAENGE: (
        ("m365", "Benutzerkonto Microsoft 365, Erstkennwort persönlich übergeben"),
        ("mfa", "Mehrfaktor-Authentifizierung eingerichtet"),
        ("passwortmanager", "Zugang Passwortmanager"),
        ("vpn", "VPN-Zugang, Zertifikat oder Schlüssel"),
        ("projektsysteme", "Zugriff Confluence, Jira und weitere Projektsysteme"),
        ("zugangskarte", "Zugangskarte, Schlüssel, Transponder"),
    ),
    OFFBOARDING: (
        (PUNKT_ZURUECKSETZEN, "Gerät auf Werkseinstellungen zurückgesetzt, Datenträger sicher gelöscht"),
        ("daten_gesichert", "Lokale Daten des Nutzers gesichert oder zur Löschung freigegeben"),
        ("geraeteverwaltung", "Gerät aus der Geräteverwaltung und aus dem Inventar ausgetragen"),
        ("benutzerkonten", "Benutzerkonten deaktiviert (Microsoft 365, Confluence, Jira, weitere)"),
        ("mfa_entkoppelt", "Mehrfaktor-Authentifizierung und Authenticator vom Gerät entkoppelt"),
        ("ssh_api", "SSH-Schlüssel und API-Token widerrufen"),
        ("vpn_zertifikate", "VPN-Zugang und Zertifikate widerrufen"),
        ("passwortmanager", "Zugriffe im Passwortmanager entzogen"),
        ("gemeinsame_kennworter", "Gemeinsam genutzte Kennwörter geändert"),
        ("softwarelizenzen", "Softwarelizenzen zurückgeführt oder neu zugewiesen (Microsoft 365)"),
        ("zugangskarte", "Zugangskarte, Schlüssel und Transponder zurückgegeben"),
        ("private_geraete", "Geschäftliche Daten von privaten Geräten und Cloud-Speichern entfernt"),
        (PUNKT_INVENTAR, "Rückgabe im Hardware-Inventar dokumentiert"),
    ),
}


def vorbelegen(modell=None) -> int:
    """Legt die Punkte der Vorlagen an, wenn eine Liste noch leer ist. Liefert die Anzahl neuer Punkte."""
    if modell is None:
        from .models import Checklistenpunkt as modell
    neu = 0
    for liste, punkte in VORBELEGUNG.items():
        if modell.objects.filter(liste=liste).exists():
            continue
        for nummer, (schluessel, text) in enumerate(punkte, start=1):
            modell.objects.create(liste=liste, schluessel=schluessel, text=text, reihenfolge=nummer * 10)
            neu += 1
    return neu


def aktive_punkte(liste: str) -> tuple:
    """Die aktiven Punkte einer Liste als (Schlüssel, Text), in der gepflegten Reihenfolge."""
    from .models import Checklistenpunkt

    zeilen = Checklistenpunkt.objects.filter(liste=liste)
    if not zeilen.exists():
        return VORBELEGUNG[liste]
    return tuple(zeilen.filter(aktiv=True).order_by("reihenfolge", "id").values_list("schluessel", "text"))


def punkte_mit_antwort(liste: str, antworten: dict) -> tuple:
    """Für ein signiertes Protokoll: Was beantwortet wurde, auch wenn der Punkt inzwischen inaktiv ist."""
    from .models import Checklistenpunkt

    zeilen = Checklistenpunkt.objects.filter(liste=liste, schluessel__in=list(antworten or {}))
    if not zeilen.exists():
        return aktive_punkte(liste)
    return tuple(zeilen.order_by("reihenfolge", "id").values_list("schluessel", "text"))


class Punktliste:
    """Die aktiven Punkte, abrufbar wie ein Attribut der Klasse Protokoll."""

    def __init__(self, liste: str):
        self.liste = liste

    def __get__(self, obj, typ=None) -> tuple:
        return aktive_punkte(self.liste)
