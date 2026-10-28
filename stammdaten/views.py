"""Views für Stammdaten: Kategorien, Personen, Orte (F-60, F-120, F-121).

Rechte (Kapitel 2):
  - Kategorien: Admin ändert, Leser liest
  - Personen: Admin ändert, Leser liest
  - Orte: Admin ändert, Leser liest
Serverseitige Prüfung (AGENTS.md).
"""
from __future__ import annotations

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Ausstattungsprofil, Ort, Person, Kategorie
from .forms import KategorieForm, PersonForm, OrtForm, ProfilForm, ProfilpositionForm


def _keine_berechtigung(request):
    """F-112: Antwort 403 mit Seite „Keine Berechtigung“."""
    return render(request, "konten/keine_berechtigung.html", status=403)


def _nur_admin(request):
    if not request.user.is_authenticated or not request.user.ist_admin:
        return None
    return request.user


def _darf_lesen(request):
    """Admin und Leser dürfen lesen (Kapitel 2)."""
    return request.user.is_authenticated and request.user.darf_stammdaten_sehen()


# ---------------------------------------------------------------------------
# Kategorien (F-120)
# ---------------------------------------------------------------------------

def kategorien_liste(request):
    """Liste der Kategorien (F-120). Admin und Leser dürfen lesen."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    return render(
        request,
        "stammdaten/kategorien_liste.html",
        {
            "kategorien": Kategorie.objects.all(),
            "ist_admin": request.user.ist_admin,
        },
    )


def kategorien_anlegen(request):
    """Neue Kategorie anlegen (F-120)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = KategorieForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:kategorien-liste"))
    return render(request, "stammdaten/kategorie_anlegen.html", {"form": form})


def kategorien_aendern(request, pk):
    """Kategorie ändern (F-120). Kategorien mit Geräten sind nicht löschbar."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        kat = Kategorie.objects.get(pk=pk)
    except Kategorie.DoesNotExist:
        from django.http import Http404
        raise Http404
    form = KategorieForm(request.POST or None, instance=kat)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:kategorien-liste"))
    return render(request, "stammdaten/kategorie_aendern.html", {"form": form, "kategorie": kat})


# ---------------------------------------------------------------------------
# Personen (F-121)
# ---------------------------------------------------------------------------

def personen_liste(request):
    """Liste der Personen (F-121). Admin und Leser dürfen lesen."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    return render(
        request,
        "stammdaten/personen_liste.html",
        {
            "personen": Person.objects.all(),
            "ist_admin": request.user.ist_admin,
        },
    )


def personen_anlegen(request):
    """Neue Person anlegen (F-121)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = PersonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:personen-liste"))
    return render(request, "stammdaten/person_anlegen.html", {"form": form})


def personen_detail(request, pk):
    """Detail einer Person (F-121, F-52 Offboarding-Ansicht)."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    return render(request, "stammdaten/person_detail.html", {"person": person})


def offboarding(request, pk):
    """Offboarding-Ansicht (F-52, A-0099).

    Zeigt alle Geräte der Person (Inventarnummer und Modell oder
    Gerätename) und deren offene Leihen.
    """
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from geraete.services import gerate_der_person
    gerate = gerate_der_person(person)
    return render(
        request,
        "stammdaten/offboarding.html",
        {"person": person, "gerate": gerate},
    )


def offboarding_zuruecknehmen(request, pk):
    """Alle Geräte der Person zurücknehmen (F-52, A-0099).

    POST-Handler für den Button „Alle zurücknehmen“.
    """
    if not request.user.is_authenticated or not request.user.ist_admin:
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from geraete import services
    anzahl = services.person_alle_zuruecknehmen(person, ausgefuehrt_von=request.user)
    from django.contrib.messages import success as meldung_success
    meldung_success(request, f"{anzahl} Gerät(e) zurückgenommen.")
    return redirect(reverse("stammdaten:personen-detail", kwargs={"pk": pk}))


def austritt_eintragen(request, pk):
    """Austritt eintragen (F-53, A-0099).

    Zeigt einen Dialog mit Austrittsdatum. Sind der Person noch Geräte
    zugeordnet, zeigt die Warnung diese an.
    """
    if not request.user.is_authenticated or not request.user.ist_admin:
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from geraete.services import gerate_der_person
    gerate = gerate_der_person(person)
    return render(
        request,
        "stammdaten/austritt.html",
        {"person": person, "gerate": gerate},
    )


def austritt_speichern(request, pk):
    """Austritt speichern (F-53, A-0099).

    POST-Handler für den Austrittsdialog.
    """
    if not request.user.is_authenticated or not request.user.ist_admin:
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from django.utils.dateparse import parse_date
    datum = request.POST.get("austrittsdatum", "")
    parsed = parse_date(datum) if datum else None
    if parsed is None:
        from django.contrib.messages import error as meldung_error
        meldung_error(request, "Bitte ein gültiges Austrittsdatum angeben.")
        return redirect(reverse("stammdaten:austritt-eintragen", kwargs={"pk": pk}))
    person.austritt = parsed
    person.aktiv = False
    person.save(update_fields=["austritt", "aktiv"])
    from django.contrib.messages import success as meldung_success
    meldung_success(request, f"Austritt am {datum} eingetragen.")
    return redirect(reverse("stammdaten:personen-detail", kwargs={"pk": pk}))


def personen_aendern(request, pk):
    """Person ändern (F-121)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    form = PersonForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:personen-detail", kwargs={"pk": pk}))
    return render(request, "stammdaten/person_aendern.html", {"form": form, "person": person})


# ---------------------------------------------------------------------------
# Orte (F-60)
# ---------------------------------------------------------------------------

def orte_liste(request):
    """Liste der Orte (F-60). Admin und Leser dürfen lesen."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    return render(
        request,
        "stammdaten/orte_liste.html",
        {
            "orte": Ort.objects.all(),
            "ist_admin": request.user.ist_admin,
        },
    )


def orte_anlegen(request):
    """Neuen Ort anlegen (F-60)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = OrtForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:orte-liste"))
    return render(request, "stammdaten/orr_anlegen.html", {"form": form})


def orte_aendern(request, pk):
    """Ort ändern (F-60)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        ort = Ort.objects.get(pk=pk)
    except Ort.DoesNotExist:
        from django.http import Http404
        raise Http404
    form = OrtForm(request.POST or None, instance=ort)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:orte-liste"))
    return render(request, "stammdaten/orr_aendern.html", {"form": form, "ort": ort})


# ---------------------------------------------------------------------------
# Ausstattungsprofile (F-61)
# ---------------------------------------------------------------------------

def profile_liste(request):
    """Liste der Profile (F-61)."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    return render(
        request,
        "stammdaten/profile_liste.html",
        {
            "profile": Ausstattungsprofil.objects.all(),
            "ist_admin": request.user.ist_admin,
        },
    )


def profil_anlegen(request):
    """Neues Profil anlegen (F-61)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = ProfilForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(reverse("stammdaten:profile-liste"))
    return render(request, "stammdaten/profil_anlegen.html", {"form": form})
