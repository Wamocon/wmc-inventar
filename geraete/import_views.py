"""/import/ als Folge von Schritten (A-0113, F-80 bis F-87).

Schritt 1: Datei hochladen, Blatt und Kopfzeile wählen oder .csv
Schritt 2: Quellspalten einem Zielfeld zuordnen (Vorschläge F-81)
Schritt 3: Werte von Kategorie, Person, Arbeitsplatz zuordnen (F-82)
Schritt 4: Vorschau je Zeile mit Ergebnis und Grund, als CSV (F-83, F-86),
danach Speichern oder Verwerfen.

Der Stand bleibt zwischen den Schritten in der Sitzung, damit die Schritte
im Browser in Ruhe durchgegangen werden können (TESTSCHNITTSTELLE 3). In
jedem Schritt geht es zurück oder der Import wird abgebrochen. Nur der Admin
kann den Import sehen; für die beiden anderen Rollen gibt es 403
(TESTSCHNITTSTELLE 3).
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.contrib.messages import info as meldung_info
from django.contrib.messages import success as meldung_success
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from stammdaten.models import Kategorie, Ort, Person

from . import import_parser
from .import_parser import (IGNORIEREN, ImportFehler, VorschauZeile,
                            csv_vorschau, zusammenfassung)
from .models import Importlauf

# Schlüssel der Sitzung für den Import-Stand (TESTSCHNITTSTELLE 3).
SCHLUESSEL = "import_stand"

# F-80: Kopfzeile frei wählbar; ohne Wahl gilt die erkannte.
KOPFZEILEN = range(1, 31)


def _nutzer_konto(nutzer: User):
    """Das Konto (die Benutzerklasse) des Nutzers; None, wenn kein Konto."""
    return nutzer


def _darf_import(nutzer: User) -> bool:
    """IT-Admin darf den Import sehen (TESTSCHNITTSTELLE 3)."""
    rolle = getattr(nutzer, "rolle", None)
    return rolle == "admin"


def _rechte_pruefen(request: HttpRequest) -> None:
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")


def _stand_aus_sitzung(request: HttpRequest) -> dict | None:
    return request.session.get(SCHLUESSEL)


def _stand_in_sitzung(request: HttpRequest, stand: dict) -> None:
    request.session[SCHLUESSEL] = stand


def _vorlage_bauen(stand: dict) -> import_parser.Vorlage:
    """Die Vorlage aus dem gespeicherten Stand neu einlesen."""
    byte = bytes.fromhex(stand["datei_hex"])
    return import_parser.lade_datei(stand["dateiname"], byte,
                                    stand.get("blatt", ""), stand.get("kopfzeile") or None)


def _vorschau_aufladen(stand: dict) -> list[VorschauZeile]:
    vorlage = _vorlage_bauen(stand)
    return import_parser.vorschau_berechnen(
        vorlage,
        stand.get("spalten_ziel", {}),
        stand.get("wert_zu_kategorie", {}),
        stand.get("wert_zu_person", {}),
        stand.get("wert_zu_arbeitsplatz", {}),
        stand.get("kategorie_standard", ""),
    )


def _schritt_eins(request: HttpRequest, stand: dict | None, fehler: str = "", status: int = 200):
    """Schritt 1: ohne Stand die Dateiwahl, mit Stand Blatt und Kopfzeile der Datei (F-80)."""
    kontext = {"schritt": 1, "fehler": fehler}
    if stand is not None:
        kontext.update(
            dateiname=stand["dateiname"],
            blaetter=stand.get("blatter", []),
            blatt_wahl=stand.get("blatt", ""),
            kopfzeile_wahl=stand.get("kopfzeile") or "",
            kopfzeilen=KOPFZEILEN,
        )
    return render(request, "geraete/import.html", kontext, status=status)


def _werte_zeilen(vorlage, feld: str, stand: dict, schluessel: str, vorschlag) -> list[dict]:
    """Jeder Wert einmal mit Zeilenzahl und Zuordnung (F-82).

    Solange Schritt 3 noch nicht abgeschickt wurde, steht dort der Vorschlag,
    danach das, was der Mensch gewählt hat (Zurück verliert nichts).
    """
    gesetzt = stand.get("werte_gesetzt")
    gespeichert = stand.get(schluessel, {})
    return [
        {"wert": wert, "anzahl": anzahl,
         "wahl": gespeichert.get(wert, "") if gesetzt else vorschlag(wert),
         "mehrdeutig": import_parser.person_mehrdeutig(wert) if feld == "Person" else ""}
        for wert, anzahl in vorlage.werte_mit_anzahl(feld, stand.get("spalten_ziel")).items()
    ]


def import_seite(request: HttpRequest):
    """/import/: die Folge der Schritte (F-80 bis F-86)."""
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    schritt = stand.get("schritt", 1) if stand else 1
    if stand is None or schritt <= 1:
        return _schritt_eins(request, stand, request.GET.get("fehler", ""))
    try:
        vorlage = _vorlage_bauen(stand)
    except ImportFehler as fehler:
        stand["schritt"] = 1
        _stand_in_sitzung(request, stand)
        return _schritt_eins(request, stand, str(fehler))
    if schritt >= 4:
        vorschau = _vorschau_aufladen(stand)
        return render(request, "geraete/import.html", {
            "schritt": 4,
            "vorlage": vorlage,
            "vorschau": vorschau,
            "zusammenfassung": zusammenfassung(vorschau),
            # F-84: Ein zweiter Import des Blatts legt nichts doppelt an, aber er soll auffallen.
            "frueherer_lauf": Importlauf.objects.filter(
                dateiname=vorlage.dateiname, blatt=vorlage.blatt,
            ).order_by("-erzeugt_am").first(),
        })
    if schritt == 3:
        # A-0912 Nr. 3: Kategorie ist eine Auswahl aus den vorhandenen
        # Kategorien plus „nicht übernehmen“, wie im Prototyp.
        kat_namen = list(Kategorie.objects.order_by("name").values_list("name", flat=True))
        standard = stand.get("kategorie_standard", "")
        hat_kategorie_spalte = any(
            ziel in ("Kategorie", import_parser.ZIEL_WAHL_KAT_MOD)
            for ziel in stand.get("spalten_ziel", {}).values()
        )
        if not stand.get("werte_gesetzt") and not hat_kategorie_spalte:
            standard = import_parser.kategorie_standard_vorschlag(vorlage.blatt, kat_namen)
        return render(request, "geraete/import.html", {
            "schritt": 3,
            "vorlage": vorlage,
            "werte_kategorie": _werte_zeilen(
                vorlage, "Kategorie", stand, "wert_zu_kategorie",
                lambda wert: import_parser.kategorie_vorschlag(wert, kat_namen)),
            "werte_person": _werte_zeilen(
                vorlage, "Person", stand, "wert_zu_person", import_parser.person_vorschlag),
            "werte_arbeitsplatz": _werte_zeilen(
                vorlage, "Arbeitsplatz", stand, "wert_zu_arbeitsplatz", import_parser.ort_vorschlag),
            "kategorie_namen": kat_namen,
            "kategorie_standard": standard,
            "personen": sorted(p.voller_name() for p in Person.objects.all()),
            "orte": Ort.objects.order_by("kennung"),
            "neuer_person_name": stand.get("neuer_person_name", ""),
        })
    # schritt == 2
    # A-0912 Nr. 2: Spalten, die „Kategorie/Modell“ anbieten dürfen.
    wahl_spalten = set()
    spalten_ziel = stand.get("spalten_ziel", {})
    for s in vorlage.spalten:
        s.ziel = spalten_ziel.get(s.name, s.ziel)
        if " ".join(s.name.lower().split()) in import_parser.WAHL_KAT_MOD_SPALTEN:
            wahl_spalten.add(s.name)
    ziele = [z for z in import_parser.ZIELFELDER if z != IGNORIEREN]
    return render(request, "geraete/import.html", {
        "schritt": 2,
        "vorlage": vorlage,
        "ziele": ziele,
        "wahl_kat_mod": import_parser.ZIEL_WAHL_KAT_MOD,
        "wahl_spalten": wahl_spalten,
    })


def _blatt_uebernehmen(request: HttpRequest, stand: dict, blatt: str, kopfzeile_text: str):
    """Blatt und Kopfzeile einlesen; geht das nicht, bleibt es bei Schritt 1 mit Fehler."""
    try:
        kopfzeile = int(kopfzeile_text) if kopfzeile_text else None
    except ValueError:
        kopfzeile = None
    if import_parser.blatt_gesperrt(blatt):
        stand["schritt"] = 1
        _stand_in_sitzung(request, stand)
        return _schritt_eins(request, stand, f"Das Blatt {blatt} ist keine Bestandsliste und wird nicht übernommen.", status=400)
    byte = bytes.fromhex(stand["datei_hex"])
    try:
        vorlage = import_parser.lade_datei(stand["dateiname"], byte, blatt, kopfzeile)
    except ImportFehler as fehler:
        stand["schritt"] = 1
        stand["blatt"] = blatt
        _stand_in_sitzung(request, stand)
        return _schritt_eins(request, stand, str(fehler), status=400)
    stand.update(
        blatt=vorlage.blatt,
        kopfzeile=vorlage.kopfzeile,
        spalten_ziel={s.name: s.ziel for s in vorlage.spalten},
        wert_zu_kategorie={},
        wert_zu_person={},
        wert_zu_arbeitsplatz={},
        kategorie_standard="",
        neuer_person_name="",
        werte_gesetzt=False,
        schritt=2,
    )
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


@require_POST
def import_datei(request: HttpRequest):
    """Schritt 1: Datei hochladen (F-80).

    Die Blätter stehen erst fest, wenn die Datei da ist. Fehlt ``blatt``, zeigt
    die Seite danach die Blätter dieser Datei; mit ``blatt`` geht es gleich weiter.
    """
    _rechte_pruefen(request)
    up = request.FILES.get("datei")
    if up is None:
        return render(request, "geraete/import.html",
                      {"fehler": "Keine Datei hochgeladen.", "schritt": 1},
                      status=400)
    dateiname = up.name
    byte = up.read()
    blatt = request.POST.get("blatt", "")
    kopfzeile = request.POST.get("kopfzeile", "")
    stand = {"dateiname": dateiname, "datei_hex": byte.hex(), "blatt": "", "kopfzeile": None,
             "blatter": [], "schritt": 1}
    try:
        if dateiname.lower().endswith(".xlsx"):
            stand["blatter"] = import_parser.blaetter_lesen(byte)
        else:
            # .csv hat keine Blätter; andere Endungen lehnt lade_datei ab.
            import_parser.lade_datei(dateiname, byte)
    except ImportFehler as fehler:
        return render(request, "geraete/import.html",
                      {"fehler": str(fehler), "schritt": 1}, status=400)
    if dateiname.lower().endswith(".xlsx") and not blatt:
        _stand_in_sitzung(request, stand)
        return redirect("/import/")
    return _blatt_uebernehmen(request, stand, blatt, kopfzeile)


@require_POST
def import_blatt(request: HttpRequest):
    """Schritt 1: Blatt und Kopfzeile der hochgeladenen Datei wählen (F-80)."""
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    return _blatt_uebernehmen(request, stand, request.POST.get("blatt", ""),
                              request.POST.get("kopfzeile", ""))


@require_POST
def import_zurueck(request: HttpRequest):
    """Einen Schritt zurück (F-80, Prototyp); Eingaben bleiben im Stand."""
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    stand["schritt"] = max(1, stand.get("schritt", 1) - 1)
    if stand["schritt"] == 1 and not stand.get("blatter"):
        # .csv: Schritt 1 ist die Dateiwahl.
        request.session.pop(SCHLUESSEL, None)
        return redirect("/import/")
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


@require_POST
def import_abbrechen(request: HttpRequest):
    """Den Import verwerfen, in jedem Schritt (F-80, F-86); gespeichert wurde nichts."""
    _rechte_pruefen(request)
    request.session.pop(SCHLUESSEL, None)
    meldung_info(request, "Import verworfen. Es wurde nichts gespeichert.")
    return redirect("/import/")


@require_POST
def import_spalten(request: HttpRequest):
    """Schritt 2: Quellspalten einem Zielfeld zuordnen (F-81)."""
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    vorlage = _vorlage_bauen(stand)
    spalten_ziel = dict(stand.get("spalten_ziel", {}))
    for spalte in vorlage.spalten:
        wert = request.POST.get(f"ziel_{spalte.name}", IGNORIEREN)
        spalten_ziel[spalte.name] = wert if wert else IGNORIEREN
    if spalten_ziel != stand.get("spalten_ziel"):
        # Andere Spalten, andere Werte: Die Vorschläge in Schritt 3 gelten neu.
        stand["werte_gesetzt"] = False
    stand["spalten_ziel"] = spalten_ziel
    for key, feld in (("wert_zu_kategorie", "Kategorie"),
                      ("wert_zu_person", "Person"),
                      ("wert_zu_arbeitsplatz", "Arbeitsplatz")):
        alt = stand.get(key, {})
        stand[key] = {w: alt.get(w, "") for w in vorlage.werte_von(feld, stand.get("spalten_ziel"))}
    stand["schritt"] = 3
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


@require_POST
def import_werte(request: HttpRequest):
    """Schritt 3: Werte zuordnen (F-82).

    Jeder Wert einmal, auch auf nicht übernehmen (leer). Leere Werte der
    Datei zählen mit (F-82).
    """
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    vorlage = _vorlage_bauen(stand)
    for key, feld in (("wert_zu_kategorie", "Kategorie"),
                      ("wert_zu_person", "Person"),
                      ("wert_zu_arbeitsplatz", "Arbeitsplatz")):
        mappe: dict[str, str] = {}
        for wert in vorlage.werte_von(feld, stand.get("spalten_ziel")):
            mappe[wert] = request.POST.get(f"{key}_{wert}", "").strip()
        stand[key] = mappe
    stand["kategorie_standard"] = request.POST.get("kategorie_standard", "").strip()
    stand["neuer_person_name"] = request.POST.get("neuer_person_name", "").strip()
    stand["werte_gesetzt"] = True
    stand["schritt"] = 4
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


def import_vorschau_csv(request: HttpRequest):
    """Die Vorschau als CSV: eine Zeile je Excel-Zeile (F-83, F-86)."""
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None or stand.get("schritt", 1) < 2:
        return HttpResponse(status=404)
    vorschau = _vorschau_aufladen(stand)
    antwort = HttpResponse("﻿" + csv_vorschau(vorschau), content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = 'attachment; filename="import-vorschau.csv"'
    return antwort


@require_POST
def import_speichern_view(request: HttpRequest):
    """Speichern nach Bestätigung (F-86 bis F-87, A-0114 Teil 3).

    POST: ruft die Service-Funktion ``import_speichern`` auf und zeigt
    eine Erfolgsmeldung mit den Zahlen neu, ergänzt, Konflikt, übersprungen.
    """
    _rechte_pruefen(request)
    stand = _stand_aus_sitzung(request)
    if stand is None or stand.get("schritt", 1) < 2:
        return redirect("/import/")

    vorlage = _vorlage_bauen(stand)
    vorschau = _vorschau_aufladen(stand)
    from . import services
    ergebnis = services.import_speichern(
        vorlage=vorlage,
        vorschau=vorschau,
        spalten_ziel=stand.get("spalten_ziel", {}),
        wert_zu_kategorie=stand.get("wert_zu_kategorie", {}),
        wert_zu_person=stand.get("wert_zu_person", {}),
        wert_zu_arbeitsplatz=stand.get("wert_zu_arbeitsplatz", {}),
        dateiname=stand.get("dateiname", ""),
        blatt=stand.get("blatt", ""),
        konto=request.user,
        kategorie_standard=stand.get("kategorie_standard", ""),
        neuer_person_name=stand.get("neuer_person_name", ""),
    )
    # Sitzung bereinigen
    request.session.pop(SCHLUESSEL, None)
    meldung_success(
        request,
        f"Import gespeichert: {ergebnis['neu']} neu, {ergebnis['ergaenzt']} ergänzt, "
        f"{ergebnis['konflikt']} Konflikt, {ergebnis['uebersprungen']} übersprungen.",
    )
    return redirect("/import/")
