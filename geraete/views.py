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
from django.views.decorators.http import require_POST

from stammdaten.models import Kategorie, Ort, Person

from . import services
from .forms import GeratForm
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
