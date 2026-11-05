"""Views für Stammdaten: Kategorien, Personen, Orte (F-60, F-120, F-121).

Rechte (Kapitel 2):
  - Kategorien: Admin ändert, Leser liest
  - Personen: Admin ändert, Leser liest
  - Orte: Admin ändert, Leser liest
Serverseitige Prüfung (AGENTS.md).
"""
from __future__ import annotations

from django.contrib import messages
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Ausstattungsprofil, Ort, Person, Kategorie, Plan, Einstellungen
from .forms import (
    KategorieForm, PersonForm, OrtForm, ProfilForm, ProfilPositionenFormSet,
    EinstellungenForm, PlanForm,
)
from .uploads import CSP_SVG, UploadFehler, bild_aus_pdf, datei_pruefen


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
    """Liste der Kategorien (F-120). Admin und Leser dürfen lesen.

    F-103: format=csv oder format=xlsx liefert die Liste als Datei.
    """
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    format_export = request.GET.get("format", "")
    if format_export in ("csv", "xlsx"):
        from geraete import export as _export
        kopfzeile = ["Name", "hat Datenträger", "Seriennummer Pflicht"]
        daten = []
        for k in Kategorie.objects.all().order_by("name"):
            daten.append({
                "Name": k.name,
                "hat Datenträger": "ja" if k.hat_datentraeger else "nein",
                "Seriennummer Pflicht": "ja" if k.seriennummer_pflicht else "nein",
            })
        dateiname = "kategorien"
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, dateiname)
        return _export.antwort_xlsx(kopfzeile, daten, dateiname)
    return render(
        request,
        "stammdaten/kategorien_liste.html",
        {
            "kategorien": Kategorie.objects.annotate(
                geraete_anzahl=Count("geraete", distinct=True),
                profile_anzahl=Count("profilpositionen", distinct=True),
            ),
            "ist_admin": request.user.ist_admin,
        },
    )


def kategorien_anlegen(request):
    """Neue Kategorie anlegen (F-120)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = KategorieForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        kat = form.save()
        messages.success(request, f"Kategorie {kat.name} angelegt.")
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
        messages.success(request, f"Kategorie {kat.name} geändert.")
        return redirect(reverse("stammdaten:kategorien-liste"))
    return render(request, "stammdaten/kategorie_aendern.html", {"form": form, "kategorie": kat})


def kategorien_loeschen(request, pk):
    """Kategorie löschen (F-120): GET fragt nach, POST löscht.

    Kategorien mit Geräten sind nicht löschbar; das sichert auch das Modell
    (PROTECT), genauso für Kategorien in einem Ausstattungsprofil.
    """
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        kat = Kategorie.objects.get(pk=pk)
    except Kategorie.DoesNotExist:
        raise Http404
    liste = reverse("stammdaten:kategorien-liste")
    grund = ""
    if kat.geraete.exists():
        grund = f"Die Kategorie {kat.name} hat noch {kat.geraete.count()} Gerät(e) und ist nicht löschbar."
    elif kat.profilpositionen.exists():
        grund = f"Die Kategorie {kat.name} steht in einem Ausstattungsprofil und ist nicht löschbar."
    if grund:
        messages.error(request, grund)
        return redirect(liste)
    if request.method == "POST":
        try:
            kat.delete()
        except ProtectedError:
            messages.error(request, f"Die Kategorie {kat.name} ist nicht löschbar.")
            return redirect(liste)
        messages.success(request, f"Kategorie {kat.name} gelöscht.")
        return redirect(liste)
    return render(request, "stammdaten/kategorie_loeschen.html", {"kategorie": kat})


# ---------------------------------------------------------------------------
# Personen (F-121)
# ---------------------------------------------------------------------------

def personen_liste(request):
    """Liste der Personen (F-121). Admin und Leser dürfen lesen.

    F-103: format=csv oder format=xlsx liefert die Liste als Datei.
    """
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    format_export = request.GET.get("format", "")
    if format_export in ("csv", "xlsx"):
        from geraete import export as _export
        kopfzeile = ["Name", "E-Mail", "Abteilung", "Eintritt", "Austritt", "aktiv"]
        daten = []
        for p in Person.objects.all().order_by("nachname", "vorname"):
            daten.append({
                "Name": p.voller_name(),
                "E-Mail": p.email,
                "Abteilung": p.abteilung,
                "Eintritt": p.eintritt.strftime("%d.%m.%Y") if p.eintritt else "",
                "Austritt": p.austritt.strftime("%d.%m.%Y") if p.austritt else "",
                "aktiv": "ja" if p.aktiv else "nein",
            })
        dateiname = "personen"
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, dateiname)
        return _export.antwort_xlsx(kopfzeile, daten, dateiname)
    return render(
        request,
        "stammdaten/personen_liste.html",
        {
            "personen": Person.objects.prefetch_related("feste_plaetze"),
            "ist_admin": request.user.ist_admin,
        },
    )


def personen_anlegen(request):
    """Neue Person anlegen (F-121)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = PersonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        person = form.save()
        messages.success(request, f"{person.voller_name()} angelegt.")
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
    return render(
        request,
        "stammdaten/person_detail.html",
        {
            "person": person,
            # F-64: fester Arbeitsplatz; Kapitel 6: Detail mit Geräten.
            "plaetze": person.feste_plaetze.order_by("kennung"),
            "gerate": _geraete_beim_austritt(person),
        },
    )


def _geraete_beim_austritt(person: Person) -> list:
    """F-53: Alle Geräte, die der Person noch zugeordnet sind.

    Auch Geräte in Reparatur, denn sie behalten die Zuordnung und kommen zurück;
    nur ausgemusterte zählen nicht mehr.
    """
    from geraete.models import Gerat
    return list(
        Gerat.objects.filter(person=person)
        .exclude(status=Gerat.STATUS_AUSGEMUSTERT)
        .select_related("kategorie")
        .order_by("inventarnummer")
    )


def _ist_person_aktiv_nach_austritt(austritt) -> bool:
    """F-53: Die Person bleibt bis zum Austrittstag aktiv; dann setzt sie der Tageslauf."""
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    return austritt is None or austritt > jetzt_wie_im_entwicklungsmodus().date()


def offboarding(request, pk):
    """Offboarding-Ansicht (F-52): alle Geräte und offenen Leihen der Person."""
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from geraete import services
    from geraete.forms import GeratAusgabeForm
    from geraete.models import Gerat, Leihe
    gerate = services.geraete_fuers_offboarding(person)
    for gerat in gerate:
        gerat.zustand_damals = services.zustand_bei_ausgabe(gerat)
    leihen = Leihe.objects.filter(
        person=person,
        status__in=[Leihe.STATUS_ANGEFRAGT, Leihe.STATUS_GENEHMIGT, Leihe.STATUS_AUSGEGEBEN],
    ).select_related("gerat", "kat").order_by("-id")
    return render(
        request,
        "stammdaten/offboarding.html",
        {
            "person": person,
            "gerate": gerate,
            "leihen": leihen,
            "zustaende": Gerat.ZUSTAENDE,
            "unterschriften": GeratAusgabeForm.UNTERSCHRIFT,
            "lagerorte": Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung"),
        },
    )


@require_POST
def offboarding_zuruecknehmen(request, pk):
    """Geräte der Person zurücknehmen, in einem Vorgang mit einem Protokoll (F-52, F-141)."""
    if not request.user.is_authenticated or not request.user.ist_admin:
        return _keine_berechtigung(request)
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        from django.http import Http404
        raise Http404
    from django.contrib.messages import error as meldung_error, success as meldung_success
    from geraete import services
    gerate = services.geraete_fuers_offboarding(person)
    if request.POST.get("aktion") == "auswahl":
        gewaehlt = set(request.POST.getlist("auswahl"))
        gerate = [g for g in gerate if g.inventarnummer in gewaehlt]
    lagerort = Ort.objects.filter(pk=request.POST.get("lager_ort") or None, typ=Ort.TYP_LAGER).first()
    posten = [
        {
            "gerat": g,
            "zustand_rueckgabe": request.POST.get(f"zustand-{g.inventarnummer}") or g.zustand,
            "zubehoer_komplett": request.POST.get(f"zubehoer-{g.inventarnummer}", "ja"),
            "maengel": request.POST.get(f"maengel-{g.inventarnummer}", ""),
            "ziel": request.POST.get(f"ziel-{g.inventarnummer}", "lager"),
            "lagerort": lagerort,
        }
        for g in gerate
    ]
    if not posten:
        meldung_error(request, "Kein Gerät gewählt.")
        return redirect(reverse("stammdaten:offboarding", kwargs={"pk": pk}))
    try:
        protokoll = services.geraete_zuruecknehmen(
            person,
            posten,
            ausgefuehrt_von=request.user,
            unterschrift=request.POST.get("unterschrift") or "tool",
            empfaenger=request.POST.get("empfaenger", ""),
        )
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
        return redirect(reverse("stammdaten:offboarding", kwargs={"pk": pk}))
    meldung_success(request, f"{len(posten)} Gerät(e) zurückgenommen, Protokoll {protokoll.nr}.")
    return redirect(f"/protokolle/{protokoll.nr}/")


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
    return render(
        request,
        "stammdaten/austritt.html",
        {"person": person, "gerate": _geraete_beim_austritt(person)},
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
    try:
        parsed = parse_date(datum) if datum else None
    except ValueError:
        parsed = None
    if parsed is None:
        from django.contrib.messages import error as meldung_error
        meldung_error(request, "Bitte ein gültiges Austrittsdatum angeben.")
        return redirect(reverse("stammdaten:austritt-eintragen", kwargs={"pk": pk}))
    person.austritt = parsed
    person.aktiv = _ist_person_aktiv_nach_austritt(parsed)
    person.save(update_fields=["austritt", "aktiv"])
    from django.contrib.messages import success as meldung_success
    meldung_success(request, f"Austritt am {parsed:%d.%m.%Y} eingetragen.")
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
    austritt_vorher = person.austritt
    form = PersonForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        austritt = form.cleaned_data["austritt"]
        if austritt and austritt != austritt_vorher:
            # F-53: Auch hier nur nach Bestätigung, wenn noch Geräte zugeordnet sind.
            gerate = _geraete_beim_austritt(person)
            if gerate and "austritt_bestaetigt" not in request.POST:
                return render(
                    request,
                    "stammdaten/person_aendern.html",
                    {"form": form, "person": person, "gerate": gerate},
                )
            person.aktiv = form.cleaned_data["aktiv"] and _ist_person_aktiv_nach_austritt(austritt)
        form.save()
        messages.success(request, f"{person.voller_name()} gespeichert.")
        return redirect(reverse("stammdaten:personen-detail", kwargs={"pk": pk}))
    return render(request, "stammdaten/person_aendern.html", {"form": form, "person": person})


# ---------------------------------------------------------------------------
# Orte (F-60)
# ---------------------------------------------------------------------------

def orte_liste(request):
    """Liste der Orte (F-60). Admin und Leser dürfen lesen.

    F-103: format=csv oder format=xlsx liefert die Liste als Datei.
    """
    if not _darf_lesen(request):
        return _keine_berechtigung(request)
    format_export = request.GET.get("format", "")
    if format_export in ("csv", "xlsx"):
        from geraete import export as _export
        kopfzeile = ["Kennung", "Name", "Typ", "Standort", "Raum", "Feste Person", "Notiz"]
        daten = []
        for o in Ort.objects.all().order_by("kennung"):
            daten.append({
                "Kennung": o.kennung,
                "Name": o.name,
                "Typ": o.get_typ_display(),
                "Standort": o.standort,
                "Raum": o.raum,
                "Feste Person": o.feste_person.voller_name() if o.feste_person else "",
                "Notiz": o.notiz,
            })
        dateiname = "orte"
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, dateiname)
        return _export.antwort_xlsx(kopfzeile, daten, dateiname)
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
        ort = form.save()
        messages.success(request, f"Ort {ort.kennung} angelegt.")
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
        ort = form.save()
        messages.success(request, f"Ort {ort.kennung} geändert.")
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
            "profile": Ausstattungsprofil.objects.prefetch_related(
                "positionen__kategorie", "plaetze"
            ),
            "ist_admin": request.user.ist_admin,
        },
    )


def _profil_formular(request, profil, titel):
    """F-61: Profil mit seinen Positionen (Kategorie und Anzahl) anlegen oder ändern."""
    form = ProfilForm(request.POST or None, instance=profil)
    positionen = ProfilPositionenFormSet(
        request.POST or None, instance=profil, prefix="positionen"
    )
    if request.method == "POST" and form.is_valid() and positionen.is_valid():
        with transaction.atomic():
            gespeichert = form.save()
            positionen.instance = gespeichert
            positionen.save()
        messages.success(request, f"Profil {gespeichert.name} gespeichert.")
        return redirect(reverse("stammdaten:profile-liste"))
    return render(
        request,
        "stammdaten/profil_formular.html",
        {"form": form, "positionen": positionen, "titel": titel},
    )


def profil_anlegen(request):
    """Neues Profil anlegen (F-61)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    return _profil_formular(request, None, "Neues Profil")


def profil_aendern(request, pk):
    """Profil ändern (F-61): Name und Positionen."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        profil = Ausstattungsprofil.objects.get(pk=pk)
    except Ausstattungsprofil.DoesNotExist:
        raise Http404
    return _profil_formular(request, profil, f"Profil {profil.name}")


# ---------------------------------------------------------------------------
# Raumplan pflegen (F-67, A-0107 Teil 2)
# ---------------------------------------------------------------------------

def _grundriss_speichern(plan: Plan, datei) -> None:
    """Datei für den Grundriss annehmen: PNG, JPG, SVG oder PDF (F-67, N-02).

    Erst prüfen, dann ersetzen: Eine abgelehnte Datei lässt den alten Plan stehen.
    Jeder Plan hat seine eigene Datei, die erste Seite eines PDFs wird zum Bild.
    """
    art, daten = datei_pruefen(
        datei,
        ("png", "jpg", "svg", "pdf"),
        "Der Grundriss muss PNG, JPG, SVG oder ein PDF sein (F-67).",
    )
    if art == "pdf":
        art, daten = "png", bild_aus_pdf(daten)
    alt = plan.grundriss.name if plan.grundriss else ""
    # Ein alter Stand kann dieselbe Datei für mehrere Pläne eingetragen haben.
    if alt and not Plan.objects.exclude(pk=plan.pk).filter(grundriss=alt).exists():
        default_storage.delete(alt)
    pfad = f"grundrisse/plan-{plan.pk}.{art}"
    if default_storage.exists(pfad):
        default_storage.delete(pfad)
    plan.grundriss.name = default_storage.save(pfad, ContentFile(daten))
    plan.save(update_fields=["grundriss"])


def _orte_des_plans(plan: Plan):
    """Plätze und Räume eines Plans, dazu noch keinem Plan zugeordnete am selben Standort."""
    from django.db.models import Q
    return Ort.objects.filter(
        Q(plan_id=plan.id) | Q(plan_id__isnull=True, standort=plan.standort),
        typ__in=(Ort.TYP_ARBEITSPLATZ, Ort.TYP_RAUM),
    ).order_by("kennung")


def _position_speichern(request, plan: Plan, ort_id: str) -> None:
    """Position eines Orts in Prozent vom Mittelpunkt (F-67, TESTSCHNITTSTELLE 2)."""
    try:
        ort = _orte_des_plans(plan).get(pk=int(ort_id))
        x = round(float(request.POST.get("x", "")), 1)
        y = round(float(request.POST.get("y", "")), 1)
    except (Ort.DoesNotExist, ValueError):
        messages.error(request, "Position nicht gespeichert: Angaben sind ungültig.")
        return
    if not (0 <= x <= 100 and 0 <= y <= 100):
        messages.error(request, "Position nicht gespeichert: x und y müssen zwischen 0 und 100 liegen.")
        return
    ort.plan_id = plan.id
    ort.position_x = x
    ort.position_y = y
    ort.save(update_fields=["plan_id", "position_x", "position_y"])
    messages.success(request, f"Position von {ort.kennung} gespeichert.")


def plan_bearbeiten(request, plan_id: int):
    """Raumplan pflegen: Grundriss hochladen, Positionen setzen (F-67).

    Adresse /arbeitsplaetze/plan/<id>/bearbeiten/ (TESTSCHNITTSTELLE 3).
    Für Admins 200, für Leser und Mitarbeiter 403 (TESTSCHNITTSTELLE 2).
    """
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    try:
        plan = Plan.objects.get(pk=plan_id)
    except Plan.DoesNotExist:
        raise Http404

    # Auswahl „Raumplan“ oben auf der Seite: zum anderen Plan wechseln.
    wechsel = request.GET.get("plan_id", "")
    if wechsel.isdigit() and int(wechsel) != plan.id and Plan.objects.filter(pk=wechsel).exists():
        return redirect(reverse("plan-bearbeiten", kwargs={"plan_id": int(wechsel)}))

    if request.method == "POST":
        datei = request.FILES.get("grundriss")
        if request.POST.get("ort"):
            _position_speichern(request, plan, request.POST["ort"])
        elif datei is None or not datei.size:
            messages.error(request, "Bitte eine Datei auswählen.")
        else:
            try:
                _grundriss_speichern(plan, datei)
                messages.success(request, "Grundriss gespeichert. Die Positionen bleiben erhalten.")
            except UploadFehler as fehler:
                messages.error(request, f"Grundriss nicht gespeichert: {fehler}")
        return redirect(request.path)

    orte = list(_orte_des_plans(plan))
    return render(
        request,
        "geraete/plan_bearbeiten.html",
        {
            "plan": plan,
            "plane": Plan.objects.all(),
            "auf_dem_plan": [o for o in orte if o.hat_position and o.plan_id == plan.id],
            "ohne_position": [o for o in orte if not o.hat_position or o.plan_id != plan.id],
            "hat_grundriss": bool(plan.grundriss),
        },
    )


def plan_anlegen(request):
    """Kapitel 3.2, F-65: neuen Raumplan für einen Standort und eine Etage anlegen."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    form = PlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        messages.success(request, f"Plan {plan} angelegt. Jetzt den Grundriss hochladen.")
        return redirect(reverse("plan-bearbeiten", kwargs={"plan_id": plan.pk}))
    return render(request, "stammdaten/plan_anlegen.html", {"form": form})


# ---------------------------------------------------------------------------
# Einstellungen (F-122, F-90, F-96, F-130, N-02) — M7 Teil 1 (A-0905)
# ---------------------------------------------------------------------------

def _logo_ablegen(einstellungen: Einstellungen, art: str, daten: bytes) -> None:
    """Geprüftes Logo ablegen (N-02); die alte Datei geht.

    SVG bleibt eine Datei, die per ``<img src=...>`` eingebunden wird, nie als
    Inline-SVG.
    """
    if einstellungen.logo and einstellungen.logo.name:
        default_storage.delete(einstellungen.logo.name)
    pfad = f"logo/logo.{art}"
    if default_storage.exists(pfad):
        default_storage.delete(pfad)
    einstellungen.logo.name = default_storage.save(pfad, ContentFile(daten))
    einstellungen.save(update_fields=["logo"])


def einstellungen_logo(request):
    """/einstellungen/logo/: das Logo als Bild; SVG mit script-src 'none' (N-02)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.logo:
        raise Http404
    ist_svg = einstellungen.logo.name.lower().endswith(".svg")
    antwort = FileResponse(
        einstellungen.logo.open("rb"),
        content_type="image/svg+xml" if ist_svg else "image/png",
    )
    if ist_svg:
        antwort["Content-Security-Policy"] = CSP_SVG
    return antwort


def _testmail_senden(empfaenger: str) -> None:
    """F-90: Testmail über denselben Weg wie alle Mails: Mailablage oder SMTP."""
    from konten.mail import link_ins_tool, mail_absender, mail_signatur
    from .firma import firmendaten

    firma = firmendaten()
    EmailMessage(
        subject=f"Testmail aus WMC Inventar – {firma['firmenname']}",
        body=(
            "Dies ist eine Testmail aus den Einstellungen von WMC Inventar.\n"
            "Die Verbindung zum Mailserver funktioniert.\n\n"
            f"Firma: {firma['firmenname']}\n"
            f"Telefon der IT: {firma['telefon'] or '–'}\n"
            f"E-Mail der IT: {firma['email_it'] or '–'}\n\n"
            f"Einstellungen: {link_ins_tool('/einstellungen/')}\n\n"
            f"{mail_signatur()}"
        ),
        from_email=mail_absender(),
        to=[empfaenger],
    ).send()


def einstellungen_sehen(request):
    """/einstellungen/ — Einstellungen anzeigen und pflegen.

    Nur Admin (TESTSCHNITTSTELLE.md Kapitel 3).
    Für Admin 200, für Leser und Mitarbeiter 403.
    """
    if not _nur_admin(request):
        return _keine_berechtigung(request)

    einstellungen = Einstellungen.aktuelles()
    form = EinstellungenForm(request.POST or None, request.FILES or None, instance=einstellungen)
    if request.method == "POST" and form.is_valid():
        instanz = form.save()
        logo = form.cleaned_data.get("logo")
        if logo:
            _logo_ablegen(instanz, *logo)
        messages.success(request, "Einstellungen gespeichert.")
        return redirect(reverse("stammdaten:einstellungen"))
    return render(
        request,
        "stammdaten/einstellungen.html",
        {"form": form, "einstellungen": einstellungen, "testmail_an": request.user.email},
    )


@require_POST
def einstellungen_testmail(request):
    """F-90: „Testmail senden“ mit den gespeicherten Werten.

    POST /einstellungen/testmail/ mit Feld "empfaenger". Nur Admin.
    Leitet auf /einstellungen/ zurück, mit Meldung oder Fehler.
    """
    if not _nur_admin(request):
        return _keine_berechtigung(request)

    empfaenger = request.POST.get("empfaenger", "").strip()
    try:
        validate_email(empfaenger)
    except ValidationError:
        messages.error(request, "Testmail nicht gesendet: Bitte eine gültige E-Mail-Adresse angeben.")
        return redirect(reverse("stammdaten:einstellungen"))
    try:
        _testmail_senden(empfaenger)
    except OSError as fehler:
        # smtplib meldet seine Fehler als OSError, auch Zeitüberschreitung und Ablehnung.
        messages.error(request, f"Testmail fehlgeschlagen: {fehler}")
    else:
        messages.success(request, f"Testmail an {empfaenger} gesendet.")
    return redirect(reverse("stammdaten:einstellungen"))
