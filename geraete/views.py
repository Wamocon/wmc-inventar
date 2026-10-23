"""Ansichten für Geräte (M2 Bestand).

F-11 bis F-16 (Aufnahme, Bearbeiten, Prüfung),
F-40 bis F-42 (Auffindbarkeit, Suche, Liste),
F-84 bis F-88 (Konflikte, Datenlücken).
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.contrib.messages import error as meldung_error
from django.contrib.messages import info as meldung_info
from django.contrib.messages import success as meldung_success
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from stammdaten.models import Kategorie, Ort, Person

from . import services
from .forms import (
    GeratAusgabeForm,
    GeratAusmusterungForm,
    GeratBearbeitungsForm,
    GeratForm,
    GeratReparaturFertigForm,
    GeratReparaturStartForm,
    GeratRueckgabeForm,
    GeratUmzugForm,
)
from .models import Gerat, GeratKonflikt

# --- Rechte -----------------------------------------------------------------

def _darf_sehen(user) -> bool:
    return user.ist_admin or user.ist_mitarbeiter or user.ist_leser


def _darf_ändern(user) -> bool:
    return user.ist_admin or user.ist_mitarbeiter


# --- Liste (F-41) -------------------------------------------------------------

@login_required
def liste(request):
    """Liste aller Geräte (F-41): Standard aufsteigend nach Inventarnummer,
    Filter nach Status, Ort, Kategorie, Person, Gerätename (F-40)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    ort_id = request.GET.get("ort") or ""
    kategorie_id = request.GET.get("kategorie") or ""
    person_id = request.GET.get("person") or ""
    unvollstaendig = request.GET.get("unvollstaendig") == "1"

    qs = Gerat.objects.select_related("person", "ort", "zuletzt_geprueft_von")
    if status:
        qs = qs.filter(status=status)
    if ort_id:
        qs = qs.filter(ort_id=ort_id)
    if kategorie_id:
        qs = qs.filter(kategorie_id=kategorie_id)
    if person_id:
        qs = qs.filter(person_id=person_id)

    if q:
        qs = qs.filter(
            Q(inventarnummer__icontains=q)
            | Q(geraetename__icontains=q)
            | Q(seriennummer__icontains=q)
            | Q(hersteller__icontains=q)
            | Q(modell__icontains=q)
            | Q(kategorie__name__icontains=q)
            | Q(ort__kennung__icontains=q)
            | Q(person__vorname__icontains=q)
            | Q(person__nachname__icontains=q)
        )

    aufsteigend = request.GET.get("sort") != "absteigend"
    qs = qs.order_by("inventarnummer" if aufsteigend else "-inventarnummer")

    anzahl = qs.count()
    if unvollstaendig:
        qs = [g for g in qs if g.ist_unvollstaendig()]
    else:
        qs = list(qs)

    return render(
        request,
        "geraete/liste.html",
        {
            "geraete": qs,
            "anzahl": anzahl,
            "suche": q,
            "status_filter": status,
            "ort_filter": ort_id,
            "kategorie_filter": kategorie_id,
            "person_filter": person_id,
            "unvollstaendig": unvollstaendig,
            "aufsteigend": aufsteigend,
            "statuser": [c for c in Gerat.STATUSES],
            "orte": Ort.objects.all(),
            "kategorien": sorted(Kategorie.objects.all(), key=lambda k: k.name),
            "personen": Person.objects.all(),
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


# --- Detail (F-16) -------------------------------------------------------------

@login_required
def detail(request, inventarnummer: str):
    """Gerät anzeigen (F-16: Prüfung, letzte Daten, Konflikte)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(
        Gerat.objects.select_related(
            "person", "ort",
            "zuletzt_geprueft_von", "erstellt_von",
        ),
        inventarnummer=inventarnummer,
    )
    offene_konflikte = list(GeratKonflikt.objects.filter(gerat=gerat, offen=True))
    doppelte_namen = gerat.doppelte_namen()
    doppelte_serien = gerat.doppelte_seriennummern()
    return render(
        request,
        "geraete/detail.html",
        {
            "gerat": gerat,
            "offene_konflikte": offene_konflikte,
            "doppelte_namen": doppelte_namen,
            "doppelte_serien": doppelte_serien,
            "datenluecken": gerat.datenluecken(),
            "koennen_aendern": _darf_ändern(request.user),
            "ist_admin": request.user.ist_admin,
        },
    )


# --- Neu anlegen (F-11 bis F-14) -------------------------------------------------

@login_required
@require_POST
def neu_anlegen(request):
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
        return redirect("/geraete/")
    form = GeratForm(request.POST, request.FILES)
    if form.is_valid():
        daten = dict(form.cleaned_data)
        daten.pop("status", None)
        try:
            gerat = services.gerat_anlegen(
                erzeugt_von=request.user,
                pruefen=True,
                **{k: v for k, v in daten.items()},
            )
        except services.GeratFehler as fehler:
            meldung_error(request, str(fehler))
            return redirect("/geraete/neu/")
        meldung_success(request, f"Gerät {gerat.inventarnummer} angelegt.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    return render(request, "geraete/neu.html", {"form": form})


@login_required
def neu_anzeigen(request):
    """Formularseite für ein neues Gerät (F-11 bis F-14)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
        return redirect("/")
    return render(request, "geraete/neu.html", {"form": GeratForm()})


# --- Bearbeiten (F-15) ------------------------------------------------------------

@login_required
def bearbeiten(request, inventarnummer: str):
    """Änderungen eintragen (F-15). Inventarnummer bleibt unverändert (F-12)."""
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Ändern ist Ihnen nicht erlaubt.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    if request.method == "POST":
        form = GeratForm(request.POST, instance=gerat)
        if form.is_valid():
            try:
                werte = dict(form.cleaned_data)
                werte.pop("status", None)
                services.gerat_bearbeiten(
                    gerat,
                    werte=werte,
                    erzeugt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/aendern/")
            meldung_success(request, f"Gerät {gerat.inventarnummer} geändert.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratForm(instance=gerat)
    return render(
        request,
        "geraete/aendern.html",
        {"form": form, "gerat": gerat},
    )


# --- M4 Arbeitsplätze (F-62 bis F-64, F-89) ---------------------------------

@login_required
def arbeitsplaetze_liste(request):
    """Alle Arbeitsplätze mit Soll-Ist-Abgleich (F-62)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    orte = list(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).order_by("kennung")
    )
    zeilen = []
    for ort in orte:
        abgleich = services.soll_ist_abgleich(ort)
        zeilen.append({"ort": ort, "abgleich": abgleich})
    return render(
        request,
        "geraete/arbeitsplaetze_liste.html",
        {"zeilen": zeilen},
    )


@login_required
def arbeitsplatz_detail(request, pk):
    """Ein Arbeitsplatz: Soll, Ist, Fehlliste, Mehrliste (F-62, F-64)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    ort = get_object_or_404(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).select_related("profil", "feste_person"),
        pk=pk,
    )
    abgleich = services.soll_ist_abgleich(ort)
    gerate = services.gerate_am_ort(ort)
    personen_gerate = services.gerate_der_person(ort.feste_person) if ort.feste_person else []
    return render(
        request,
        "geraete/arbeitsplatz_detail.html",
        {
            "ort": ort,
            "abgleich": abgleich,
            "gerate": gerate,
            "personen_gerate": personen_gerate,
        },
    )


@login_required
def bedarf(request):
    """Bedarf: fehlende Ausstattung je Kategorie mit Lagerbestand (F-63)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    uebersicht = services.bedarf_uebersicht()
    return render(
        request,
        "geraete/bedarf.html",
        {"uebersicht": uebersicht},
    )


@login_required
def erstinventur(request):
    """Erstinventur: Fortschritt je Ort (F-89, AUFTRAG M4)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    zeilen = services.fortschritt_je_ort()
    total_geprueft = sum(z["geprueft"] for z in zeilen)
    total_alle = sum(z["alle"] for z in zeilen)
    return render(
        request,
        "geraete/erstinventur.html",
        {
            "zeilen": zeilen,
            "total_geprueft": total_geprueft,
            "total_alle": total_alle,
        },
    )


@login_required
@require_POST
def ort_pruefen(request, pk):
    """Ort als geprüft markieren (F-89 Fortschritt je Ort)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Prüfen ist Ihnen nicht erlaubt.")
        return redirect("/arbeitsplaetze/")
    ort = get_object_or_404(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ), pk=pk
    )
    # Setze aktualisiert_am als Zeitstempel der letzten Prüfung
    ort.aktualisiert_am = timezone.now()
    ort.save(update_fields=["aktualisiert_am"])
    meldung_success(request, f"Ort {ort.kennung} als geprüft markiert.")
    return redirect("/arbeitsplaetze/" + str(pk) + "/")


# --- Prüfung (F-16) -------------------------------------------------------------

@login_required
@require_POST
def pruefen(request, inventarnummer: str):
    """Prüfung abhaken (F-16): Datum und Kontext."""
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Prüfen ist Ihnen nicht erlaubt.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    services.gerat_pruefen(gerat, request.user)
    meldung_success(request, f"Prüfung für {gerat.inventarnummer} erfasst.")
    return redirect("/geraete/" + gerat.inventarnummer + "/")


# --- Konflikt lösen (F-86) ----------------------------------------------------------

@login_required
@require_POST
def konflikt_loesen(request, inventarnummer: str, konflikt_id: int):
    """Konflikt: alten Wert behalten oder neuen übernehmen (F-86)."""
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Konflikte lösen ist Ihnen nicht erlaubt.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    konflikt = get_object_or_404(GeratKonflikt, pk=konflikt_id, gerat=gerat)
    nehmen = request.POST.get("nehmen", "")
    try:
        services.konflikt_loesen(konflikt, nehmen, ausgefuehrt_von=request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    meldung_success(request, f"Konflikt zu „{konflikt.feld}“ gelöst.")
    return redirect("/geraete/" + gerat.inventarnummer + "/")


# --- Arbeitsliste (F-88) ----------------------------------------------------------

@login_required
def arbeitsliste(request):
    """Geräte mit Datenlücken oder offenem Konflikt (F-88)."""
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    return redirect("/geraete/?unvollstaendig=1")


# --- M3 Lebenszyklus ----------------------------------------------------------

@login_required
def ausgeben(request, inventarnummer: str):
    """Gerät ausgeben (F-20 bis F-23, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratAusgabeForm(request.POST)
        if form.is_valid():
            ziel = form.cleaned_data.get("ziel_person") or form.cleaned_data.get("ziel_ort")
            try:
                services.gerat_ausgeben(
                    gerat,
                    ziel,
                    zurueck_am=form.cleaned_data.get("zurueck_am"),
                    anmerkung=form.cleaned_data.get("anmerkung", ""),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät ausgegeben.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratAusgabeForm()
    return render(request, "geraete/ausgabe.html", {"gerat": gerat, "form": form})


@login_required
def rueckgeben(request, inventarnummer: str):
    """Gerät zurückgeben (F-50, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratRueckgabeForm(request.POST)
        if form.is_valid():
            try:
                services.gerat_rueckgeben(
                    gerat,
                    zustand_rueckgabe=form.cleaned_data.get("zustand_rueckgabe", 2),
                    zubesehoer_komplett=form.cleaned_data.get("zubehoer_komplett", True),
                    maengel=form.cleaned_data.get("maengel", ""),
                    ziel=form.cleaned_data.get("ziel", "lager"),
                    fehlend=form.cleaned_data.get("fehlend", False),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät zurückgegeben.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratRueckgabeForm()
    return render(request, "geraete/rueckgabe.html", {"gerat": gerat, "form": form})


@login_required
def umziehen(request, inventarnummer: str):
    """Gerät umziehen (F-41, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratUmzugForm(request.POST)
        if form.is_valid():
            try:
                services.gerat_umziehen(
                    gerat,
                    form.cleaned_data.get("ziel_ort"),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät umgezogen.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratUmzugForm()
    return render(request, "geraete/umzug.html", {"gerat": gerat, "form": form})


@login_required
def reparatur_start(request, inventarnummer: str):
    """Reparatur starten (F-42, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratReparaturStartForm(request.POST)
        if form.is_valid():
            try:
                services.gerat_in_reparatur_geschickt(
                    gerat,
                    dienstleister=form.cleaned_data.get("dienstleister"),
                    vorgangsnummer=form.cleaned_data.get("vorgangsnummer"),
                    notiz=form.cleaned_data.get("notiz", ""),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Reparatur gestartet.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratReparaturStartForm()
    return render(request, "geraete/reparatur_start.html", {"gerat": gerat, "form": form})


@login_required
def reparatur_fertig(request, inventarnummer: str):
    """Reparatur abschließen (F-42, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratReparaturFertigForm(request.POST)
        if form.is_valid():
            try:
                services.gerat_reparatur_fertig(
                    gerat,
                    zustand=form.cleaned_data.get("zustand", 2),
                    ziel=form.cleaned_data.get("ziel", "lager"),
                    kosten=form.cleaned_data.get("kosten"),
                    beleg=form.cleaned_data.get("beleg", ""),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Reparatur abgeschlossen.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratReparaturFertigForm()
    return render(request, "geraete/reparatur_fertig.html", {"gerat": gerat, "form": form})


@login_required
def ausmustern(request, inventarnummer: str):
    """Gerät ausmustern (F-55 bis F-58, M3)."""
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratAusmusterungForm(request.POST)
        if form.is_valid():
            try:
                services.ausmustern(
                    gerat,
                    grund=form.cleaned_data.get("grund"),
                    datum=form.cleaned_data.get("datum"),
                    disposition=form.cleaned_data.get("disposition"),
                    loeschung_art=form.cleaned_data.get("loeschung_art", ""),
                    loeschung_nachweis=form.cleaned_data.get("loeschung_nachweis", ""),
                    bestaetigt_gemeldt=form.cleaned_data.get("bestaetigt_gemeldt", False),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät ausgemustert.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratAusmusterungForm()
    return render(request, "geraete/ausmusterung.html", {"gerat": gerat, "form": form})
