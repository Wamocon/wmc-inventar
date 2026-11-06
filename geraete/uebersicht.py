"""Übersicht / und die Schnittstelle /api/kennzahlen (M7 Teil 3, A-0907).

F-100 Kennzahlen als IST/Gesamt, F-101 Delta zum Vortag, F-102 Arbeitslisten,
F-103 Export jeder Liste, F-104 Inventarwert, F-105 Schnittstelle.
TESTSCHNITTSTELLE Kapitel 3, 4 und 5.
"""
from __future__ import annotations

import os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from . import export as _export
from . import kennzahlen as _kz
from .views import _darf_sehen

# Prototyp: Unterzeile je Kennzahl und Warnfarbe, solange etwas offen ist.
UNTERZEILEN = {
    "in-benutzung": "von allen aktiven Geräten",
    "ueberfaellig": "von den ausgegebenen Leihen",
    "anfragen-offen": "warten auf Entscheidung",
    "garantie-30-tage": "in den nächsten 30 Tagen",
    "unterschriften-offen": "Protokolle ohne Unterschrift",
    "arbeitsplaetze-vollstaendig": "Soll-Ausstattung erfüllt",
    "verliehen": "vom Leihpool",
    "geprueft": "Stand der Erstinventur",
}
ACHTUNG = {"ueberfaellig", "unterschriften-offen"}


def _keine_berechtigung(request):
    """F-112: Antwort 403 mit Seite „Keine Berechtigung“."""
    return render(request, "konten/keine_berechtigung.html", status=403)


def _darf_lesen(request) -> bool:
    return request.user.is_authenticated and _darf_sehen(request.user)


def _nur_eigene_anfragen(konto, zeilen: list[dict]) -> list[dict]:
    """Kapitel 2: Der Leser sieht alle Listen außer dem Verleih. Von den offenen
    Leihanfragen bleiben ihm nur die eigenen, ohne Name und Zweck anderer (Erwin 06.11.2026)."""
    if konto.ist_admin:
        return zeilen
    return [z for z in zeilen if konto.person_id and z.get("person_id") == konto.person_id]


@login_required
def uebersicht(request):
    """/ – Übersicht für Admin und Leser (F-100 bis F-104).

    Mitarbeiter werden nach /meine-geraete/ weitergeleitet (Kapitel 3).
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('konten:anmelden')}?next=/")
    if request.user.ist_mitarbeiter:
        return redirect("/meine-geraete/")
    if not _darf_sehen(request.user):
        return _keine_berechtigung(request)

    heute = _kz._heute()
    # F-101: Zum Vortag von heute, sonst zeigt ein alter Zählerstand ein altes Delta.
    delta = _kz.delta_zum_vortag(heute) or {}
    kennzahlen = [
        {**kz, "delta": delta.get(kz["data_id"]), "delta_abs": abs(delta.get(kz["data_id"], 0) or 0),
         "unterzeile": UNTERZEILEN.get(kz["data_id"], ""),
         "achtung": kz["data_id"] in ACHTUNG and bool(kz.get("ist"))}
        for kz in _kz.kennzahlen(heute)
        # F-100: „geprüft“ ist sichtbar, bis alle aktiven Geräte geprüft sind.
        if not (kz["data_id"] == "geprueft" and kz["gesamt"] and kz["ist"] >= kz["gesamt"])
    ]
    arbeitslisten = _kz.arbeitslisten(heute)
    if not request.user.ist_admin:
        # Testschnittstelle 3: /verleih/ ist nur für den Admin.
        for liste in arbeitslisten:
            if liste["data_id"] == "anfragen":
                liste["zeilen"] = _nur_eigene_anfragen(request.user, liste["zeilen"])
            for zeile in liste["zeilen"]:
                if "link_leser" in zeile:
                    zeile["link"] = zeile["link_leser"]
    # Bestand nach Status (Prototyp: stock-bar)
    from .models import Gerat
    _STATUS_ORDNUNG = (
        (Gerat.STATUS_IN_BENUTZUNG, "In Benutzung"),
        (Gerat.STATUS_VERLIEHEN, "Verliehen"),
        (Gerat.STATUS_AUF_LAGER, "Auf Lager"),
        (Gerat.STATUS_IN_REPARATUR, "In Reparatur"),
    )
    status_zahlen = [
        {"code": code, "label": label, "zahl": _kz._aktive_geraete().filter(status=code).count()}
        for code, label in _STATUS_ORDNUNG
    ]
    aktive_zahl = sum(e["zahl"] for e in status_zahlen)
    archiv_zahl = Gerat.objects.filter(status=Gerat.STATUS_AUSGEMUSTERT).count()
    return render(
        request,
        "uebersicht.html",
        {
            "stand": heute.strftime("%d.%m.%Y"),
            "kennzahlen": kennzahlen,
            "arbeitslisten": arbeitslisten,
            "inventarwert": _kz.inventarwert(),
            "status_zahlen": status_zahlen,
            "aktive_zahl": aktive_zahl,
            "archiv_zahl": archiv_zahl,
        },
    )


# --- Export der acht Listen (F-103) -----------------------------------------

_EXPORT_DEF = {
    "ueberfaellig": {
        "kopfzeile": ["Nr.", "Gerät", "Person", "Rückgabe bis"],
        "felder": ("nr", "gerat", "person", "frist"),
        "quelle": _kz.ueberfaellig,
    },
    "anfragen": {
        "kopfzeile": ["Nr.", "Gerät", "Person", "Zweck"],
        "felder": ("nr", "gerat", "person", "zweck"),
        "quelle": _kz.offene_anfragen,
    },
    "arbeitsplaetze-unvollstaendig": {
        "kopfzeile": ["Kennung", "Standort", "Mangel"],
        "felder": ("kennung", "standort", "mangel"),
        "quelle": _kz.arbeitsplaetze_unvollstaendig,
    },
    "garantie": {
        "kopfzeile": ["Inventarnummer", "Modell", "Garantie bis"],
        "felder": ("nr", "modell", "garantie_bis"),
        "quelle": _kz.garantie_laeuft_ab,
    },
    "unterschriften-offen": {
        "kopfzeile": ["Nr.", "Stand", "Person"],
        "felder": ("nr", "stand", "person"),
        "quelle": _kz.unterschreibungen_offen,
    },
    "versand-offen": {
        "kopfzeile": ["Nr.", "Stand", "Person"],
        "felder": ("nr", "stand", "person"),
        "quelle": _kz.versand_offen,
    },
    "daten-unvollstaendig": {
        "kopfzeile": ["Inventarnummer", "Modell", "Fehlende Angaben"],
        "felder": ("nr", "modell", "luecken"),
        "quelle": _kz.daten_unvollstaendig,
    },
    "offene-punkte": {
        "kopfzeile": ["Person", "Offene Punkte"],
        "felder": ("name", "punkte"),
        "quelle": _kz.offene_punkte_in_klaerung,
    },
    "austritte": {
        "kopfzeile": ["Person", "Austritt", "Geräte"],
        "felder": ("name", "austritt", "geraete"),
        "quelle": _kz.austritte,
    },
}


@login_required
def liste_export(request):
    """Eine der acht Listen als .csv oder .xlsx (F-103), nur Admin und Leser."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    liste_id = (request.GET.get("liste") or "").strip()
    format_export = (request.GET.get("format") or "").strip().lower()
    if liste_id not in _EXPORT_DEF or format_export not in ("csv", "xlsx"):
        return _keine_berechtigung(request)
    heute = _kz._heute()
    zeilen = _EXPORT_DEF[liste_id]["quelle"](heute)
    if liste_id == "anfragen":
        zeilen = _nur_eigene_anfragen(request.user, zeilen)
    kopfzeile = _EXPORT_DEF[liste_id]["kopfzeile"]
    felder = _EXPORT_DEF[liste_id]["felder"]
    # Die Spalten heißen wie die Kopfzeile, die Werte stehen unter den Feldern der Liste.
    daten = [
        {kopf: zeile.get(feld) for kopf, feld in zip(kopfzeile, felder)}
        for zeile in zeilen
    ]
    if format_export == "csv":
        return _export.antwort_csv(kopfzeile, daten, liste_id)
    return _export.antwort_xlsx(kopfzeile, daten, liste_id)


# --- Schnittstelle /api/kennzahlen (F-105) ----------------------------------

@csrf_exempt
def api_kennzahlen(request):
    """Lesender JSON-Endpunkt (F-105, Kapitel 4).

    Ohne gesetztes KENNZAHLEN_TOKEN: 404.
    Ohne oder mit falschem Token: 401.
    Mit richtigem Token: 200 mit stand und kennzahlen.
    """
    token = (os.environ.get("KENNZAHLEN_TOKEN") or "").strip()
    if not token:
        return JsonResponse({"fehler": "Schnittstelle ist nicht aktiv."}, status=404)
    if request.method != "GET":
        return JsonResponse({"fehler": "Nur GET."}, status=405)
    kopf = (request.headers.get("Authorization") or "").strip()
    if not kopf.startswith("Bearer ") or kopf[len("Bearer "):].strip() != token:
        return JsonResponse({"fehler": "Token fehlt oder ist falsch."}, status=401)
    return JsonResponse(_kz.uebersicht())
