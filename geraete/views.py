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
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
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
    GeratNotizForm,
    GeratReparaturFertigForm,
    GeratReparaturStartForm,
    GeratRueckgabeForm,
    GeratUmzugForm,
)
from .models import Gerat, GeratKonflikt, Leihe, Protokoll, Vorgang


def _qr_svg(gerat):
    """QR-Code als SVG für das Gerätedetail (F-70)."""
    from django.utils.safestring import mark_safe
    from .etiketten import qr_svg
    return mark_safe(qr_svg(gerat))


# --- Rechte -----------------------------------------------------------------

def _darf_sehen(user) -> bool:
    return user.ist_admin or user.ist_mitarbeiter or user.ist_leser


def _darf_ändern(user) -> bool:
    return user.ist_admin or user.ist_mitarbeiter


def _darf_sehen_raumplan(user) -> bool:
    """/arbeitsplaetze/…: Admin und Leser (F-110), nie Mitarbeiter (Kap. 3)."""
    return user.ist_admin or user.ist_leser


def _keine_berechtigung(request, pfad: str):
    """403 für Mitarbeiter auf /arbeitsplaetze/… (Kapitel 3 der Testschnittstelle).

    ``pfad`` ist die absolute Adresse, die im Satz vorkommt.
    """
    meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
    raise PermissionDenied(f"Zugriff verweigert: {pfad}")


# --- Liste (F-41) -------------------------------------------------------------

def _geraete_export(request, geraete: list, format_export: str):
    """F-103: Liste der Geräte mit aktuellem Filter als .csv oder .xlsx."""
    from . import export as _export
    kopfzeile = [
        "Inventarnummer", "Status", "Hersteller", "Modell", "Person",
        "Ort", "Kategorie", "Kaufdatum", "Garantie bis",
    ]
    daten = []
    for gerat in geraete:
        daten.append({
            "Inventarnummer": gerat.inventarnummer,
            "Status": gerat.status_anzeige,
            "Hersteller": gerat.hersteller,
            "Modell": gerat.modell,
            "Person": (
                f"{gerat.person.vorname} {gerat.person.nachname}".strip()
                if gerat.person
                else ""
            ),
            "Ort": gerat.ort.kennung if gerat.ort else "",
            "Kategorie": gerat.kategorie.name if gerat.kategorie else "",
            "Kaufdatum": gerat.kaufdatum or "",
            "Garantie bis": gerat.garantie_bis or "",
        })
    if format_export == "csv":
        return _export.antwort_csv(kopfzeile, daten, "geraete")
    return _export.antwort_xlsx(kopfzeile, daten, "geraete")


@login_required
def liste(request):
    """Liste aller Geräte (F-41): Standard aufsteigend nach Inventarnummer,
    Filter nach Status, Ort, Kategorie, Person, Gerätename (F-40).

    Für Mitarbeiter: 403 „Keine Berechtigung" (F-112, Kapitel 2) –
    auch für eigene Geräte; eigene Geräte stehen unter /meine-geraete/.
    """
    if not request.user.darf_geraete_sehen():
        return render(request, "konten/keine_berechtigung.html", status=403)

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
        # Ort-Filter: Datenbanknummer (bestehend) oder Kennung (F-89, Kapitel 4).
        if ort_id.isdigit():
            qs = qs.filter(ort_id=ort_id)
        else:
            qs = qs.filter(ort__kennung=ort_id)
    if kategorie_id:
        qs = qs.filter(kategorie_id=kategorie_id)
    if person_id:
        qs = qs.filter(person_id=person_id)

    if q:
        # F-44 (A-0098): Suche nach Inventarnummer, Seriennummer, Modell,
        # Hostname (Gerätename) und Person (Vor- und Nachname).
        qs = qs.filter(
            Q(inventarnummer__icontains=q)
            | Q(geraetename__icontains=q)
            | Q(seriennummer__icontains=q)
            | Q(modell__icontains=q)
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

    # F-103 (A-0907, M7 Teil 3): Export der Liste mit aktuellem Filter.
    format_export = (request.GET.get("format") or "").strip().lower()
    if format_export in ("csv", "xlsx"):
        return _geraete_export(request, qs, format_export)

    # Erstinventur-Fortschritt je Ort, sobald nach ort gefiltert (F-89, Kap. 4):
    # Markierung ``inventur-fortschritt`` mit ``ist`` und ``gesamt``.
    fortschritt = None
    if ort_id and not ort_id.isdigit():
        ort = Ort.objects.filter(kennung=ort_id).first()
        if ort:
            fortschritt = services.fortschritt_des_orts(ort)

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
            "fortschritt": fortschritt,
        },
    )


# --- Detail (F-16) -------------------------------------------------------------

@login_required
def detail(request, inventarnummer: str):
    """Gerät anzeigen (F-16: Prüfung, letzte Daten, Konflikte)."""
    if not _darf_sehen(request.user):
        return render(request, "konten/keine_berechtigung.html", status=403)
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
    # F-14 (A-0099): Löschen ist nur für Admin, solange außer Aufnahme
    # kein Vorgang existiert; sonst fehlt die Aktion im HTML.
    kann_loeschen = (
        request.user.ist_admin
        and gerat.vorgaenge.exclude(typ=Vorgang.TYP_AUFNAHME).count() == 0
    )
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
            "kann_loeschen": kann_loeschen,
            # F-70: QR-Code im Gerätedetail
            "qr_inhalt": f"{settings.BASIS_URL}/g/{gerat.inventarnummer}",
            "qr_svg": _qr_svg(gerat),
            "kann_etikett_sehen": request.user.ist_admin or request.user.ist_leser,
        },
    )


# --- Neu anlegen (F-11 bis F-14) -------------------------------------------------

def _stammdaten_aus_form(daten: dict) -> dict:
    """Zieht die Stammdaten aus dem cleaned_data, ohne Seriennummer.

    F-11 (A-0112): Die Seriennummer kommt aus dem Textfeld ``seriennummern``
    (zeilenweise) oder aus dem Einzel-Feld ``seriennummer``. Hier bleiben
    nur die übrigen Stammdaten.
    """
    daten.pop("status", None)
    daten.pop("seriennummer", None)
    daten.pop("seriennummern", None)
    return daten


def _seriennummern_auetzen(request) -> list[str]:
    """Seriennummern aus dem POST auetzen (F-11, A-0112).

    Das Textfeld ``seriennummern`` enthält zeilenweise die Seriennummern.
    Leere Zeilen werden verworfen. Fehlt das Feld, fällt man auf das
    Einzel-Feld ``seriennummer`` zurück (ein Element oder leere Liste).
    """
    roh = (request.POST.get("seriennummern") or "").strip()
    if roh:
        zeilen = [z.strip() for z in roh.splitlines()]
        return [z for z in zeilen if z]
    einzeilig = (request.POST.get("seriennummer") or "").strip()
    return [einzeilig] if einzeilig else []


@login_required
@require_POST
def neu_anlegen(request):
    """Speichern (F-11, F-12, F-13, F-14, A-0112).

    F-11: Das Textfeld ``seriennummern`` trägt zeilenweise Seriennummern;
    es entstehen so viele Geräte wie Zeilen, je mit eigener Inventarnummer
    und Vorgang Aufnahme. Ohne Seriennummer entsteht ein Gerät wie bisher.
    F-13: Die Stammdaten werden aus der Vorlage übernommen (``?vorlage=``).
    """
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
        raise PermissionDenied("Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
    form = GeratForm(request.POST, request.FILES)
    if form.is_valid():
        daten = _stammdaten_aus_form(dict(form.cleaned_data))
        serienliste = _seriennummern_auetzen(request)
        try:
            erstellte = []
            for seriennummer in (serienliste if serienliste else [""]):
                gerat = services.gerat_anlegen(
                    erzeugt_von=request.user,
                    pruefen=True,
                    seriennummer=seriennummer,
                    **daten,
                )
                erstellte.append(gerat)
        except services.GeratFehler as fehler:
            meldung_error(request, str(fehler))
            return redirect("/geraete/neu/")
        if len(erstellte) == 1:
            meldung_success(request, f"Gerät {erstellte[0].inventarnummer} angelegt.")
            # F-12: "Speichern und Etikett drucken" — Button-Name im POST prüfen.
            if request.POST.get("aktion") == "etikett":
                from .etiketten import etikett_pdf
                pdf = etikett_pdf(erstellte[0])
                response = HttpResponse(pdf, content_type="application/pdf")
                response["Content-Disposition"] = (
                    f'inline; filename="etikett-{erstellte[0].inventarnummer}.pdf"'
                )
                return response
            return redirect("/geraete/" + erstellte[0].inventarnummer + "/")
        meldung_success(request, f"{len(erstellte)} Geräte angelegt.")
        return redirect("/geraete/")
    return render(request, "geraete/neu.html", {"form": form})


@login_required
def neu_anzeigen(request):
    """Formularseite für ein neues Gerät (F-11 bis F-14, A-0112).

    F-13: ``?vorlage=<Inventarnummer>`` übernimmt die Stammdaten des
    genannten Geräts; die Seriennummer bleibt leer.
    """
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
        raise PermissionDenied("Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
    vorlage_inventarnummer = (request.GET.get("vorlage") or "").strip()
    initial = {}
    if vorlage_inventarnummer:
        vorlage = Gerat.objects.filter(inventarnummer=vorlage_inventarnummer).first()
        if vorlage:
            initial = {
                "kategorie": vorlage.kategorie,
                "hersteller": vorlage.hersteller,
                "modell": vorlage.modell,
                "seriennummer": "",
                "zustand": vorlage.zustand,
                "leihpool": vorlage.leihpool,
                "person": None,
                "ort": vorlage.ort,
                "geraetename": vorlage.geraetename,
                "standardzuehoer": vorlage.standardzuehoer,
                "technische_daten": vorlage.technische_daten,
                "kaufdatum": vorlage.kaufdatum,
                "kaufpreis_netto": vorlage.kaufpreis_netto,
                "lieferant": vorlage.lieferant,
                "rechnungsnummer": vorlage.rechnungsnummer,
                "garantie_bis": vorlage.garantie_bis,
                "notiz": vorlage.notiz,
            }
    return render(
        request,
        "geraete/neu.html",
        {"form": GeratForm(initial=initial or None), "vorlage": vorlage_inventarnummer},
    )


# --- Bearbeiten (F-15) ------------------------------------------------------------

@login_required
def bearbeiten(request, inventarnummer: str):
    """Änderungen eintragen (F-15). Inventarnummer bleibt unverändert (F-12)."""
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    # F-58 (A-0097): Ausgemusterte Geräte sind nicht mehr änderbar.
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        meldung_error(request, "Ausgemusterte Geräte sind nicht mehr änderbar.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Ändern ist Ihnen nicht erlaubt.")
        raise PermissionDenied("Zugriff verweigert: Ändern ist Ihnen nicht erlaubt.")
    if request.method == "POST":
        form = GeratForm(request.POST, instance=gerat)
        if form.is_valid():
            try:
                werte = dict(form.cleaned_data)
                werte.pop("status", None)
                werte.pop("seriennummern", None)
                # A-0112 (F-40): form.is_valid() schreibt die neuen Werte schon
                # in die Instanz (construct_instance). Wir holen ein frisches
                # Exemplar aus der Datenbank, damit gerat_bearbeiten den alten
                # Stand vergleicht.
                gerat_frisch = Gerat.objects.get(pk=gerat.pk)
                services.gerat_bearbeiten(
                    gerat_frisch,
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


# --- M4 Arbeitsplätze und Raumplan (F-62 bis F-69, F-89) ---------------------

@login_required
def arbeitsplaetze(request):
    """Raumplan: Plan je Standort und Etage (F-65, F-67, F-68, F-69).

    Adresse /arbeitsplaetze/ (TESTSCHNITTSTELLE Kapitel 3, 4).
    Für Admin und Leser 200, für Mitarbeiter 403.
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, "/arbeitsplaetze/")
    plane = services.plan_auswahl()
    param_hervor = request.GET.get("hervorheben", "")
    if param_hervor:
        if "|" in param_hervor:
            standort, etage = param_hervor.split("|", 1)
            plan = services.plan_finde(standort, etage) or (plane[0] if plane else None)
        else:
            plan = (plane[0] if plane else None)
        hervorheben = param_hervor.split("|", 1)[1] if "|" in param_hervor else ""
    else:
        param_plan = request.GET.get("plan", "")
        if param_plan:
            if "|" in param_plan:
                standort, etage = param_plan.split("|", 1)
                plan = services.plan_finde(standort, etage) or (plane[0] if plane else None)
            else:
                plan = (plane[0] if plane else None)
        else:
            plan = plane[0] if plane else None
        hervorheben = ""
    if plan is None:
        plaetze, raumorte, ohne_pos = [], [], []
    else:
        plaetze = services.plaetze_des_plans(plan)
        raumorte = services.raumorte_des_plans(plan)
        ohne_pos = services.ohne_position(plan)
    return render(
        request,
        "geraete/raumplan.html",
        {
            "plane": plane,
            "plan": plan,
            "plaetze": plaetze,
            "raumorte": raumorte,
            "ohne_pos": ohne_pos,
            "hervorheben": hervorheben,
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


@login_required
def arbeitsplaetze_liste(request):
    """Alle Arbeitsplätze als Liste mit Soll-Ist-Ergebnis (F-62).

    Adresse /arbeitsplaetze/liste/ (TESTSCHNITTSTELLE Kapitel 3).
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, "/arbeitsplaetze/liste/")
    orte = list(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).select_related(
            "profil", "feste_person"
        ).order_by("kennung")
    )
    zeilen = []
    for ort in orte:
        abgleich = services.soll_ist_abgleich(ort)
        zeilen.append({"ort": ort, "abgleich": abgleich})
    return render(
        request,
        "geraete/arbeitsplaetze_liste.html",
        {"zeilen": zeilen, "koennen_aendern": _darf_ändern(request.user)},
    )


@login_required
def arbeitsplatz_detail(request, kennung: str):
    """Ein Arbeitsplatz: Soll, Ist, Fehlliste, Mehrliste (F-62, F-64).

    Adresse /arbeitsplaetze/<Kennung>/ (z. B. /arbeitsplaetze/WMC-WP-01/).
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, f"/arbeitsplaetze/{kennung}/")
    ort = get_object_or_404(
        Ort.objects.filter(
            typ=Ort.TYP_ARBEITSPLATZ
        ).select_related("profil", "feste_person"),
        kennung=kennung,
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
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


@login_required
def arbeitsplatz_popup(request, kennung: str):
    """Pop-up eines Platzes (F-66): Kennung, Raum, Person, Profil,
    Soll-Ist mit Fehlliste, Geräte am Platz, Geräte der festen Person.

    Adresse /arbeitsplaetze/<Kennung>/popup/ (HTMX-Fragment, Kapitel 4).
    """
    if not _darf_sehen_raumplan(request.user):
        return HttpResponse(status=403)
    ort = get_object_or_404(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).select_related(
            "profil", "feste_person"
        ),
        kennung=kennung,
    )
    abgleich = services.soll_ist_abgleich(ort)
    gerate = services.gerate_am_ort(ort)
    personen_gerate = (
        services.gerate_der_person(ort.feste_person) if ort.feste_person else []
    )
    return render(
        request,
        "geraete/platz_popup.html",
        {
            "ort": ort,
            "abgleich": abgleich,
            "gerate": gerate,
            "personen_gerate": personen_gerate,
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


@login_required
def raum_popup(request, kennung: str):
    """Pop-up eines Raums (F-68): dieselbe Geräteliste wie im Platz-Pop-up.

    Adresse /arbeitsplaetze/raum/<Kennung>/popup/ (Kapitel 4).
    """
    if not _darf_sehen_raumplan(request.user):
        return HttpResponse(status=403)
    ort = get_object_or_404(Ort.objects.filter(typ=Ort.TYP_RAUM), kennung=kennung)
    gerate = services.gerate_am_ort(ort)
    return render(
        request,
        "geraete/platz_popup.html",
        {
            "ort": ort,
            "abgleich": None,
            "gerate": gerate,
            "personen_gerate": [],
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


@login_required
def bedarf(request):
    """Bedarf: fehlende Ausstattung je Kategorie mit Lagerbestand (F-63).

    Adresse /arbeitsplaetze/bedarf/ (TESTSCHNITTSTELLE Kapitel 3).
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, "/arbeitsplaetze/bedarf/")
    uebersicht = services.bedarf_uebersicht()
    return render(
        request,
        "geraete/bedarf.html",
        {"uebersicht": uebersicht, "koennen_aendern": _darf_ändern(request.user)},
    )


@login_required
def erstinventur(request):
    """Erstinventur: Fortschritt je Ort (F-89, AUFTRAG M4).

    Adresse /arbeitsplaetze/pruefen/ (Prüfen, Kapitel 3).
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, "/arbeitsplaetze/pruefen/")
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
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


@login_required
@require_POST
def ort_pruefen(request, kennung: str):
    """Ort als geprüft markieren (F-89 Fortschritt je Ort)."""
    if not _darf_ändern(request.user):
        _keine_berechtigung(request, f"/arbeitsplaetze/{kennung}/pruefen/")
    ort = get_object_or_404(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ), kennung=kennung
    )
    ort.aktualisiert_am = timezone.now()
    ort.save(update_fields=["aktualisiert_am"])
    meldung_success(request, f"Ort {ort.kennung} als geprüft markiert.")
    return redirect("/arbeitsplaetze/" + kennung + "/")


@login_required
def platz_popup(request, kennung: str):
    """Pop-up-Inhalt eines Platzes (F-66): Kennung, Raum, Person, Profil,
    Soll-Ist mit Fehlliste, Geräte am Platz, Geräte der Person.

    Adresse /arbeitsplaetze/<Kennung>/popup/ (HTMX-Fragment).
    """
    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, f"/arbeitsplaetze/{kennung}/popup/")
    ort = get_object_or_404(
        Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).select_related(
            "profil", "feste_person"
        ),
        kennung=kennung,
    )
    abgleich = services.soll_ist_abgleich(ort)
    gerate = services.gerate_am_ort(ort)
    personen_gerate = services.gerate_der_person(ort.feste_person) if ort.feste_person else []
    return render(
        request,
        "geraete/platz_popup.html",
        {
            "ort": ort,
            "abgleich": abgleich,
            "gerate": gerate,
            "personen_gerate": personen_gerate,
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


# --- Notiz am Gerät (F-74, A-0111 Teil 4) ------------------------------------

@login_required
def notiz_zeigen(request, inventarnummer: str):
    """Notiz am Gerät eintragen (F-74, A-0111 Teil 4).

    Dialog ``data-name="notiz"`` mit ``speichern`` (TESTSCHNITTSTELLE
    Kapitel 4). Die Notiz steht danach am Gerät (F-74).
    """
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if not _darf_ändern(request.user):
        meldung_error(request, "Zugriff verweigert: Notiz eintragen ist Ihnen nicht erlaubt.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    if request.method == "POST":
        form = GeratNotizForm(request.POST)
        if form.is_valid():
            gerat.notiz = form.cleaned_data.get("notiz", "")
            gerat.save(update_fields=["notiz"])
            meldung_success(request, f"Notiz für {gerat.inventarnummer} gespeichert.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratNotizForm(initial={"notiz": gerat.notiz})
    return render(request, "geraete/notiz.html", {"gerat": gerat, "form": form})


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
        form = GeratAusgabeForm(request.POST, gerat=gerat)
        if form.is_valid():
            ziel_person = form.cleaned_data.get("ziel_person")
            ziel_ort = form.cleaned_data.get("ziel_ort")
            if ziel_person is None and ziel_ort is None:
                meldung_error(request, "Ziel muss eine Person oder ein Ort sein.")
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            try:
                services.gerat_ausgeben(
                    gerat,
                    ziel=ziel_person or ziel_ort,
                    ziel_ort=ziel_ort,
                    zustand=form.cleaned_data.get("zustand"),
                    zubehoer_komplett=form.cleaned_data.get("zubehoer_komplett") == "ja",
                    anmerkung=form.cleaned_data.get("anmerkung", ""),
                    ausgefuehrt_von=request.user,
                    unterschrift=form.cleaned_data.get("unterschrift", "papier"),
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät ausgegeben.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratAusgabeForm(gerat=gerat)
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
        form = GeratAusmusterungForm(request.POST, request.FILES, gerat=gerat)
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
        form = GeratAusmusterungForm(gerat=gerat)
    return render(request, "geraete/ausmusterung.html", {"gerat": gerat, "form": form})


# --- F-14 (A-0099): Löschen ----------------------------------------------------

@login_required
def loeschen_zeigen(request, inventarnummer: str):
    """Bestätigungsdialog für „Gerät löschen“ (F-14, A-0099)."""
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Löschen ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    return render(request, "geraete/loeschen.html", {"gerat": gerat})


@login_required
@require_POST
def loeschen(request, inventarnummer: str):
    """Gerät löschen (F-14, A-0099).

    Nur für Admin und nur, solange außer Aufnahme kein Vorgang existiert.
    """
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Löschen ist Ihnen nicht erlaubt.")
        return redirect("/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if gerat.vorgaenge.exclude(typ=Vorgang.TYP_AUFNAHME).count() > 0:
        meldung_error(request, "Das Gerät hat schon Vorgänge und kann nicht gelöscht werden.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    gerat.delete()
    meldung_success(request, f"Gerät {inventarnummer} gelöscht.")
    return redirect("/geraete/")


# --- QR-Code und Etiketten (F-12, F-70 bis F-73, F-89) -------------------------

@login_required
def gerat_kurz(request, inventarnummer: str):
    """/g/<Inventarnummer>: Kurzansicht für Mitarbeiter (F-113).

    Zeigt Kategorie, Modell, Inventarnummer und
    „Ihnen zugeordnet" oder „nicht Ihnen zugeordnet" – sonst nichts.
    Für Admin und Leser leitet weiter zu /geraete/<Inventarnummer>/ (F-70).
    """
    if not _darf_sehen(request.user):
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return redirect("/")
    if request.user.ist_mitarbeiter:
        gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
        person = request.user.person
        Ihnen_zugeordnet = person is not None and gerat.person_id == person.id
        return render(
            request,
            "geraete/kurzansicht.html",
            {"gerat": gerat, "Ihnen_zugeordnet": Ihnen_zugeordnet},
        )
    return redirect(f"/geraete/{inventarnummer}/")


@login_required
def etikett_drucken(request, inventarnummer: str):
    """/geraete/<Inventarnummer>/etikett/: Einzelnes Etikett als PDF (F-72).

    Für Admin und Leser.
    """
    if not (request.user.ist_admin or request.user.ist_leser):
        _keine_berechtigung(request, f"/geraete/{inventarnummer}/etikett/")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    from .etiketten import etikett_pdf
    pdf = etikett_pdf(gerat)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="etikett-{gerat.inventarnummer}.pdf"'
    return response


@login_required
def etiketten_auswahl(request):
    """Etikettenbogen für eine Auswahl aus der Geräteliste (F-72, F-73).

    POST mit auswahl=Inventarnummern (kommagetrennt) und startposition.
    Für Admin (Kapitel 6 der Anforderungen: Bildschirm Etiketten nur für den Admin).
    """
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return render(request, "konten/keine_berechtigung.html", status=403)

    if request.method != "POST":
        meldung_error(request, "Bitte die Auswahl mit POST an /etiketten/auswahl/ übermitteln.")
        return redirect("/geraete/")

    auswahl = (request.POST.get("auswahl") or "").strip()
    start = request.POST.get("startposition") or "1"

    inventarnummern = [nr.strip() for nr in auswahl.split(",") if nr.strip()]
    if not inventarnummern:
        meldung_error(request, "Keine Geräte ausgewählt.")
        return redirect("/geraete/")

    geraete = list(
        Gerat.objects.filter(inventarnummer__in=inventarnummern)
        .select_related("kategorie")
    )
    # Reihenfolge wie im POST beibehalten
    best = {g.inventarnummer: g for g in geraete}
    geraete = [best[nr] for nr in inventarnummern if nr in best]

    if not geraete:
        meldung_error(request, "Die ausgewählten Geräte wurden nicht gefunden.")
        return redirect("/geraete/")

    try:
        start_int = max(1, min(24, int(start)))
    except (ValueError, TypeError):
        start_int = 1

    from .etiketten import bogen_pdf
    pdf = bogen_pdf(geraete, startposition=start_int)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="etiketten-bogen-{len(geraete)}.pdf"'
    return response


@login_required
def etiketten_ort(request):
    """/etiketten/: Etiketten je Ort, sortiert nach bisheriger Kennung (F-89).

    Für Admin (Kapitel 6 der Anforderungen: Bildschirm Etiketten nur für den
    Admin). Leser und Mitarbeiter: 403 mit „Keine Berechtigung“.

    Ohne Parameter: Auswahlseite mit den Arbeitsplätzen und Lagerorten,
    wählbarer Startposition (F-73) und „Bogen drucken“.
    Mit ?ort=<Kennung>: der Bogen für diesen Ort als application/pdf.
    """
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return render(request, "konten/keine_berechtigung.html", status=403)

    ort_kennung = (request.GET.get("ort") or "").strip()
    if ort_kennung:
        ort = Ort.objects.filter(kennung=ort_kennung).first()
        if ort is None:
            meldung_error(request, f"Ort {ort_kennung} wurde nicht gefunden.")
            return redirect("/geraete/")

        from .etiketten import etiketten_fuer_ort, bogen_pdf
        geraete = etiketten_fuer_ort(ort)
        if not geraete:
            meldung_error(request, f"Keine Geräte am Ort {ort.kennung}.")
            return redirect("/etiketten/")

        try:
            start_int = max(1, min(24, int(request.GET.get("startposition") or "1")))
        except (ValueError, TypeError):
            start_int = 1

        pdf = bogen_pdf(geraete, startposition=start_int)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="etiketten-{ort.kennung}.pdf"'
        return response

    orte = list(
        Ort.objects.filter(typ__in=(Ort.TYP_ARBEITSPLATZ, Ort.TYP_LAGER)).order_by("kennung")
    )
    return render(
        request,
        "geraete/etiketten.html",
        {
            "orte": orte,
            "anzahl_orte": len(orte),
            "ausgewaehlt": request.GET.get("ort", ""),
        },
    )


# --- M5 Verleih (F-30, F-36) ---------------------------------------------------

def _ist_admin(request) -> bool:
    return bool(request.user.ist_admin)


def _ist_mitarbeiter(request) -> bool:
    """Kapitel 3: Mitarbeiter sehen /meine-geraete/… (F-95, F-112)."""
    return bool(request.user.ist_mitarbeiter)


@login_required
def verleih_zeige(request, inventarnummer):
    """Dialog „Gerät verleihen" am Gerätedetail (F-30, TESTSCHNITTSTELLE 4).

    GET: Formular anzeigen.
    POST: Verleih abschließen.
    """
    from .models import Gerat
    from .services import leih_gerat_ausgeben, GeratFehler
    from .forms import VerleihForm

    if not _ist_admin(request):
        raise PermissionDenied

    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    form = VerleihForm(request.POST or None)

    meldung = ""
    fehler = ""

    if request.method == "POST" and form.is_valid():
        try:
            person = form.cleaned_data["person"]
            rueckgabe_bis = form.cleaned_data["rueckgabe_bis"]
            zweck = form.cleaned_data["zweck"]
            unterschrift = form.cleaned_data.get("unterschrift", "papier")
            leih_gerat_ausgeben(
                gerat=gerat,
                person=person,
                rueckgabe_bis=rueckgabe_bis,
                zweck=zweck,
                ausgefuehrt_von=request.user,
                unterschrift=unterschrift,
            )
            meldung = "Gerät wurde verliehen."
            return redirect("geraete:detail", inventarnummer=inventarnummer)
        except GeratFehler as e:
            fehler = str(e)

    return render(
        request,
        "geraete/verleih.html",
        {
            "form": form,
            "gerat": gerat,
            "meldung": meldung,
            "fehler": fehler,
        },
    )


@login_required
def verleih_liste(request):
    """/verleih/ – Leihen-Übersicht (F-36, TESTSCHNITTSTELLE 3).

    Zeigt aktive und überfällige Leihen.
    Nur für Admin (403 für Mitarbeiter, F-112).
    F-103: format=csv oder format=xlsx liefert die Liste als Datei.
    """
    from .models import Leihe
    from .services import leihen_ueberfaellig

    if not _ist_admin(request):
        raise PermissionDenied

    leihen = list(
        Leihe.objects.all()
        .select_related("gerat", "person", "kat")
        .order_by("-zeitpunkt")
    )
    ueberfaellige = {l.id for l in services.leihen_ueberfaellig()}

    format_export = request.GET.get("format", "")
    if format_export in ("csv", "xlsx"):
        from . import export as _export
        kopfzeile = ["Leihnummer", "Gerät", "Person", "Kategorie", "Beginn", "Ende", "Rückgabe bis", "Zweck", "Status"]
        daten = []
        for leihe in leihen:
            daten.append({
                "Leihnummer": leihe.nr,
                "Gerät": leihe.gerat.inventarnummer if leihe.gerat else "",
                "Person": leihe.person.voller_name() if leihe.person else "",
                "Kategorie": leihe.kat.name if leihe.kat else "",
                "Beginn": leihe.beginn or "",
                "Ende": leihe.ende or "",
                "Rückgabe bis": leihe.rueckgabe_bis or "",
                "Zweck": leihe.zweck,
                "Status": leihe.stand_anzeige,
            })
        dateiname = "verleih"
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, dateiname)
        return _export.antwort_xlsx(kopfzeile, daten, dateiname)

    return render(
        request,
        "geraete/verleih_liste.html",
        {
            "leihen": leihen,
            "ueberfaellige": ueberfaellige,
        },
    )


# --- M5 Teil 2: Anfrage und Entscheidung (A-0118) ---------------------------

def _freie_je_kategorie(beginn, ende, pool_qs):
    """F-31: Freie Geräte je Kategorie im Leihpool im Zeitraum.

    Ein Gerät ist frei, wenn es im Leihpool steht und in dem Zeitraum
    nicht schon genehmigt (O-12, F-34).
    """
    from .services import _gerat_ist_reserviert

    freie = {}
    for gerat in pool_qs.select_related("kategorie"):
        if _gerat_ist_reserviert(gerat, beginn, ende):
            continue
        kat = gerat.kategorie
        if kat is None:
            continue
        freie[kat.id] = (kat, freie.get(kat.id, (None, 0))[1] + 1)
    return [
        (kat, anzahl)
        for (kat, anzahl) in sorted(freie.values(), key=lambda t: t[0].name)
    ]


@login_required
def meine_geraete_zeige(request):
    """/meine-geraete/ – Meine Geräte (F-110, F-111, Kapitel 3).

    Zeigt die eigenen Geräte mit Inventarnummer, Ausgabedatum und
    Protokoll-PDF, die eigenen Protokolle und „Meine Leihen“ mit Stand,
    Rückgabedatum und dem Weg zu „Leihgerät anfragen“.
    Kapitel 3: 200 für Mitarbeiter; 200 auch für Admin und Leser,
    wenn das Konto eine Person hat; sonst 403.
    """
    if not _ist_mitarbeiter(request):
        if not (request.user.ist_admin or request.user.ist_leser):
            raise PermissionDenied
        if request.user.person is None:
            raise PermissionDenied
    person = request.user.person

    geräte = list(Gerat.objects.filter(person=person).order_by("inventarnummer"))

    ausgaben = {}
    protokoll_je_gerat = {}
    for vorgang in Vorgang.objects.filter(
        typ=Vorgang.TYP_AUSGABE, gerat__person=person
    ).order_by("-zeitpunkt"):
        if vorgang.gerat_id not in ausgaben:
            ausgaben[vorgang.gerat_id] = vorgang

    def _eintrag(gerat):
        vorgang_ausgabe = ausgaben.get(gerat.id)
        protokoll = (
            Protokoll.objects.filter(geraet=gerat, person=person)
            .order_by("-datum", "-id")
            .first()
        )
        return {
            "gerat": gerat,
            "ausgabe_datum": vorgang_ausgabe.zeitpunkt.date() if vorgang_ausgabe else None,
            "protokoll": protokoll,
        }

    gerate_eintraege = [_eintrag(gerat) for gerat in geräte]

    protokolle = list(
        Protokoll.objects.filter(person=person)
        .order_by("-datum")
    )

    leihen = list(
        Leihe.objects.filter(person=person).order_by("-zeitpunkt")
    )
    ueberfaellige = {l.id for l in services.leihen_ueberfaellig()}
    for leihe in leihen:
        leihe.ueberfaellig = leihe.id in ueberfaellige

    return render(
        request,
        "geraete/meine_geraete.html",
        {
            "geraete": gerate_eintraege,
            "protokolle": protokolle,
            "leihen": leihen,
        },
    )


@login_required
def meine_geraete_alle_zeige(request):
    """/meine-geraete/alle/ – Alle Geräte (F-112)."""
    if not _ist_mitarbeiter(request):
        raise PermissionDenied
    geräte = Gerat.objects.all().order_by("inventarnummer")
    return render(
        request,
        "geraete/alle_geraete.html",
        {"geraete": geräte},
    )


@login_required
def meine_geraete_leihe_neu(request):
    """/meine-geraete/leihe/neu/ – Leihgerät anfragen (F-31, Kapitel 3).

    GET: Formular mit Leihkategorien und freien Geräten je Kategorie
    im Leihpool im gewählten Zeitraum. POST: Anfrage speichern,
    danach mit data-stand „angefragt\" in /verleih/ (O-12).
    """
    from stammdaten.models import Person

    from .forms import LeiheAnfrageForm
    from .services import GeratFehler, leihe_anfragen

    if not _ist_mitarbeiter(request):
        if not (request.user.ist_admin or request.user.ist_leser):
            raise PermissionDenied
        if request.user.person is None:
            raise PermissionDenied

    person = request.user.person
    if person is None:
        person = Person.objects.filter(konten=request.user).first()
    if person is None:
        raise PermissionDenied

    pool_qs = Gerat.objects.filter(
        leihpool=True
    ).select_related("kategorie")

    form = LeiheAnfrageForm(request.POST or None, leihpool_geraete=pool_qs)
    freie = []
    if form.is_bound and form.is_valid():
        beginn = form.cleaned_data.get("beginn")
        ende = form.cleaned_data.get("ende")
        if beginn and ende and beginn <= ende:
            freie = _freie_je_kategorie(beginn, ende, pool_qs)

    meldung = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_anfragen(
                person=person,
                kat=form.cleaned_data["kat"],
                beginn=form.cleaned_data["beginn"],
                ende=form.cleaned_data["ende"],
                zweck=form.cleaned_data["zweck"],
                gerat=form.cleaned_data.get("gerat"),
                erzeugt_von=request.user,
            )
            meldung_success(request, "Leihanfrage gesendet. Sie ist mit dem Status 'angefragt' angelegt.")
            return redirect("/meine-geraete/")
        except GeratFehler as fehler_vorgang:
            meldung = str(fehler_vorgang)

    return render(
        request,
        "geraete/leihe_neu.html",
        {
            "form": form,
            "freie": freie,
            "meldung": meldung,
        },
    )


@login_required
def meine_geraete_leihe_zurueckziehen(request, leih_id):
    """Leihe zurückziehen (F-37, Kapitel 3).

    POST: Leihe auf „zurueckgezogen\" setzen; die Reservierung endet
    damit. GET: Formular mit Bestätigung.
    """
    from .forms import LeiheZurueckziehenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_zurueckziehen

    if not _ist_mitarbeiter(request):
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    if leihe.person_id != request.user.person_id:
        raise PermissionDenied
    form = LeiheZurueckziehenForm(request.POST or None)

    meldung = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_zurueckziehen(leihe, ausgefuehrt_von=request.user)
            return redirect("/meine-geraete/")
        except GeratFehler as fehler:
            meldung = str(fehler)

    return render(
        request,
        "geraete/leihe_zurueckziehen.html",
        {
            "form": form,
            "leihe": leihe,
            "meldung": meldung,
        },
    )


@login_required
def leihe_genehmigen_zeige(request, leih_id):
    """Dialog „Leihe genehmigen" in /verleih/ (F-32, Kapitel 4).

    GET: Formular mit Geräten aus dem Leihpool der Kategorie.
    POST: Leihe genehmigen – Überschneidung schlägt in fehler fehl (F-34).
    """
    from .forms import LeiheGenehmigenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_genehmigen

    if not _ist_admin(request):
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    if leihe.kat is None:
        raise PermissionDenied
    pool_qs = Gerat.objects.filter(
        kategorie=leihe.kat, leihpool=True
    ).order_by("inventarnummer")
    form = LeiheGenehmigenForm(request.POST or None, leihpool_geraete=pool_qs)
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_genehmigen(
                leihe,
                gerat=form.cleaned_data["gerat"],
                ausgefuehrt_von=request.user,
            )
            return redirect("/verleih/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    return render(
        request,
        "geraete/leihe_genehmigen.html",
        {
            "form": form,
            "leihe": leihe,
            "fehler": fehler,
        },
    )


@login_required
def leihe_ausgeben_zeige(request, leih_id):
    """Dialog „Leihe ausgeben" in /verleih/ (F-33, Kapitel 4).

    GET: Formular anzeigen.
    POST: Leihe ausgeben – Gerät wird „Verliehen", Protokoll entsteht.
    """
    from .forms import LeiheAusgebenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_ausgeben

    if not _ist_admin(request):
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    form = LeiheAusgebenForm(request.POST or None)
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_ausgeben(leihe, ausgefuehrt_von=request.user)
            return redirect("/verleih/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    return render(
        request,
        "geraete/leihe_ausgeben.html",
        {
            "form": form,
            "leihe": leihe,
            "fehler": fehler,
        },
    )


@login_required
def leihe_verlaengern_zeige(request, leih_id):
    """Dialog „Verlängerung" in /verleih/ (F-35, Kapitel 4).

    GET: Formular mit neuem Rückgabedatum.
    POST: Verlängerung genehmigen – bei Folgereservierung mit fehler abgelehnt.
    """
    from .forms import LeiheVerlaengernForm
    from .models import Leihe
    from .services import GeratFehler, leihe_verlaengern

    if not _ist_admin(request):
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    form = LeiheVerlaengernForm(request.POST or None, leihe=leihe)
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_verlaengern(
                leihe,
                rueckgabe_bis_neu=form.cleaned_data["rueckgabe_bis_neu"],
                ausgefuehrt_von=request.user,
            )
            return redirect("/verleih/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    return render(
        request,
        "geraete/leihe_verlaengern.html",
        {
            "form": form,
            "leihe": leihe,
            "fehler": fehler,
        },
    )


@login_required
def leihe_ablehnen_zeige(request, leih_id):
    """Dialog „Leihe ablehnen\" in /verleih/ (F-32, Kapitel 4).

    POST mit leerer Begründung wird nicht gespeichert (F-32).
    """
    from .forms import LeiheAblehnenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_ablehnen

    if not _ist_admin(request):
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    form = LeiheAblehnenForm(request.POST or None)
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_ablehnen(
                leihe,
                begruendung=form.cleaned_data["begründung"],
                ausgefuehrt_von=request.user,
            )
            return redirect("/verleih/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    return render(
        request,
        "geraete/leihe_ablehnen.html",
        {
            "form": form,
            "leihe": leihe,
            "fehler": fehler,
        },
    )


# --- M6 Teil 1: Protokoll (F-130, F-132, F-133, F-134, F-22) ------------------

def _protokoll_berechtigt(protokoll: Protokoll, request) -> None:
    """Rechte (TESTSCHNITTSTELLE 3): 200 für die Person, Admin und Leser
    mit Person; sonst 403.
    """
    if request.user.ist_admin:
        return
    person = protokoll.person
    if request.user.ist_leser:
        if request.user.person is not None:
            return
        raise PermissionDenied
    if request.user.person is None:
        raise PermissionDenied
    if person is None or request.user.person_id != person.id:
        raise PermissionDenied


@login_required
def protokoll_detail(request, protokoll_nr):
    """/protokolle/<Nummer>/ – Protokoll-Detail (F-130, F-132, F-134).

    Zeigt Aufbau und Wortlaut der Vorlage, die Checkliste, die Fotos
    und den Stand. Kapitel 3: 403 für ein fremdes Konto.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    checkliste = [
        {"schluessel": schluessel, "text": text, "wert": (protokoll.checkliste or {}).get(schluessel)}
        for schluessel, text in Protokoll.CHECKLISTE_PUNKTE
    ]
    offboarding = []
    for schluessel, text in Protokoll.OFFBOARDING_PUNKTE:
        wert = (protokoll.offboarding or {}).get(schluessel)
        if isinstance(wert, dict):
            offboarding.append({
                "schluessel": schluessel,
                "text": text,
                "wert": wert.get("status"),
                "datum": wert.get("datum", ""),
                "kuerzel": wert.get("kuerzel", ""),
                "bemerkung": wert.get("bemerkung", ""),
            })
        elif wert is True:
            offboarding.append({
                "schluessel": schluessel, "text": text, "wert": "erledigt",
                "datum": "", "kuerzel": "", "bemerkung": "",
            })
        elif wert is False:
            offboarding.append({
                "schluessel": schluessel, "text": text, "wert": "nicht_zutreffend",
                "datum": "", "kuerzel": "", "bemerkung": "",
            })
        else:
            offboarding.append({
                "schluessel": schluessel, "text": text, "wert": None,
                "datum": "", "kuerzel": "", "bemerkung": "",
            })
    return render(
        request,
        "geraete/protokoll_detail.html",
        {
            "protokoll": protokoll,
            "geraet": protokoll.geraet,
            "person": protokoll.person,
            "checkliste": checkliste,
            "offboarding": offboarding,
            "anhaenge": protokoll.anhaenge_liste(),
        },
    )


@login_required
def protokoll_pdf(request, protokoll_nr):
    """/protokolle/<Nummer>/pdf/ – PDF-Download (F-130, F-132).

    F-132: das PDF entsteht erst, wenn jeder Punkt der Checkliste
    beantwortet ist. Antwortet application/pdf.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    from . import pdf as protokoll_pdf_modul
    try:
        inhalt = protokoll_pdf_modul.pdf_fertig_bauen(protokoll)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
        return redirect(f"/protokolle/{protokoll_nr}/")

    antwort = HttpResponse(inhalt, content_type="application/pdf")
    antwort[
        "Content-Disposition"
    ] = f"attachment; filename={protokoll_pdf_modul.dateiname_protokoll(protokoll)}"
    return antwort


@login_required
@require_POST
def protokoll_checkliste_beantworten(request, protokoll_nr):
    """POST /protokolle/<Nummer>/checkliste/ – Checkliste (F-132).

    Die sechs Punkte ja/nein. Nur solange das Protokoll „scan-offen"
    ist (F-22).
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    from . import protokoll as protokoll_services

    werte = {}
    for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
        roh = request.POST.get(f"checkliste.{schluessel}")
        if roh in ("0", "1"):
            werte[schluessel] = int(roh)
    try:
        protokoll_services.checkliste_beantworten(protokoll, werte, request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Checkliste gespeichert (F-132).")
    return redirect(f"/protokolle/{protokoll_nr}/")


@login_required
@require_POST
def protokoll_offboarding_beantworten(request, protokoll_nr):
    """POST /protokolle/<Nummer>/offboarding/ – Prüfpunkte IT-Offboarding (F-133).

    Die 13 Punkte: je Punkt erledigt, in Klärung oder nicht zutreffend,
    dazu Datum, Kürzel und Bemerkung. Punkt 13 „Rückgabe im
    Hardware-Inventar dokumentiert" setzt das Tool selbst (F-133).
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    from . import protokoll as protokoll_services

    werte = {}
    for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE:
        roh = request.POST.get(f"offboarding.{schluessel}")
        if roh in ("erledigt", "in_klaerung", "nicht_zutreffend"):
            werte[schluessel] = roh
            werte[f"{schluessel}.datum"] = request.POST.get(
                f"offboarding.{schluessel}.datum", ""
            )
            werte[f"{schluessel}.kuerzel"] = request.POST.get(
                f"offboarding.{schluessel}.kuerzel", ""
            )
            werte[f"{schluessel}.bemerkung"] = request.POST.get(
                f"offboarding.{schluessel}.bemerkung", ""
            )
    try:
        protokoll_services.offboarding_beantworten(
            protokoll, werte, request.user
        )
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Prüfpunkte gespeichert (F-133).")
    return redirect(f"/protokolle/{protokoll_nr}/")


@login_required
@require_POST
def protokoll_foto_hochladen(request, protokoll_nr):
    """POST /protokolle/<Nummer>/foto/ – Foto (F-134).

    JPG, PNG oder HEIC bis 10 MB; verkleinert als Anlage hinter dem
    Protokoll.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    from . import protokoll as protokoll_services

    datei = request.FILES.get("foto")
    if datei is None:
        meldung_error(request, "Kein Foto übergeben (F-134).")
        return redirect(f"/protokolle/{protokoll_nr}/")
    try:
        protokoll_services.foto_hochladen(protokoll, datei, request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Foto als Anlage gespeichert (F-134).")
    return redirect(f"/protokolle/{protokoll_nr}/")


@login_required
@require_POST
def protokoll_scan_hochladen(request, protokoll_nr):
    """POST /protokolle/<Nummer>/scan/ – Scan (F-22).

    Der hochgeladene Scan setzt das Protokoll auf „abgeschlossen".
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    from . import protokoll as protokoll_services

    datei = request.FILES.get("scan")
    if datei is None:
        meldung_error(request, "Kein Scan übergeben (F-22).")
        return redirect(f"/protokolle/{protokoll_nr}/")
    try:
        protokoll_services.scan_hochladen(protokoll, datei, request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Scan hochgeladen, Protokoll abgeschlossen (F-22).")
    return redirect(f"/protokolle/{protokoll_nr}/")


# --- A-0125 M6 Teil 2: Signatur, Gegenzeichnung (F-135, F-136, F-137) --------
#
# F-135: Bearbeiter signiert mit erneuter Passwortabfrage.
# F-136: Person signiert per Token-Link mit Einmalcode.
# F-137: Prüfprotokoll als letzte Seite im PDF.
# F-141: Rücknahme erst mit Signatur abgeschlossen.


@require_POST
@login_required
def protokoll_abbrechen(request, protokoll_nr: str):
    """A-0127: POST /protokolle/<Nummer>/abbrechen/

    Verwirft das Protokoll. Gerät bleibt unverändert (Status war
    nicht gesetzt, weil Signatur noch fehlt).
    Bei Verleih (F-30, F-33): die Leihe wird ebenfalls entfernt,
    damit das Gerät wieder ausgebbar ist.
    Nur für Protokolle auf "bearbeiter-offen".
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    if protokoll.stand != Protokoll.STAND_BEARBEITER_OFFEN:
        meldung_error(request, "Nur Protokolle auf 'bearbeiter-offen' können abgebrochen werden.")
        return redirect(f"/protokolle/{protokoll_nr}/")

    # A-0128: Bei Verleih (F-30, F-33) auch die Leihe entfernen,
    # damit das Gerät wieder ausgebbar ist.
    if protokoll.leihe is not None:
        protokoll.leihe.delete()

    protokoll.delete()
    meldung_success(request, "Protokoll abgebrochen. Das Gerät bleibt unverändert.")
    return redirect("/meine-geraete/")


@require_POST
@login_required
def protokoll_signieren(request, protokoll_nr: str):
    """F-135: POST /protokolle/<Nummer>/signieren/

    Bearbeiter signiert das Protokoll mit erneuter Passwortabfrage.
    Danach: Inhalt gesperrt, Stand → gegenzeichnung-offen,
    Mail mit Link in die Mailablage.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    password = request.POST.get("passwort", "")
    if not password:
        meldung_error(request, "Passwort fehlt (F-135).")
        return redirect(f"/protokolle/{protokoll_nr}/")

    try:
        _, erfolg = services.protokoll_bearbeiter_signieren(
            protokoll, password, request
        )
    except Exception as fehler:
        meldung_error(request, f"Signatur fehlgeschlagen: {fehler}")
        return redirect(f"/protokolle/{protokoll_nr}/")

    if not erfolg:
        offene = protokoll.checkliste_unbeantwortet()
        if offene:
            meldung_error(
                request,
                f"Die Checkliste ist noch nicht vollständig beantwortet "
                f"({len(offene)} Punkte offen, F-132); die Signatur wird abgelehnt."
            )
        else:
            meldung_error(request, "Passwort ungültig (F-135).")
    else:
        meldung_success(request, "Protokoll signiert. Mail mit Link gesendet (F-135, F-136).")
    return redirect(f"/protokolle/{protokoll_nr}/")


@require_POST
@login_required
def protokoll_code_senden(request, protokoll_nr: str):
    """F-136: POST /protokolle/<Nummer>/code-senden/

    Erzeugt einen 6-stelligen Einmalcode (10 Min., 5 Versuche) und
    schickt eine Mail mit der Zeile „Einmalcode: <code>".
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    empfaenger = request.POST.get("empfaenger", "").strip()
    erfolg, meldung = services.protokoll_code_senden(
        protokoll, empfaenger or None, request
    )
    if erfolg:
        meldung_success(request, meldung)
    else:
        meldung_error(request, meldung or "Code konnte nicht gesendet werden.")
    return redirect(f"/protokolle/{protokoll_nr}/")


@require_POST
@login_required
def protokoll_link_neu_senden(request, protokoll_nr: str):
    """F-140: POST /protokolle/<Nummer>/link-neu-senden/

    Abgelaufener Link wird neu gesendet (neuer Token, neue Mail).
    Erinnerung am dritten Tag kommt mit dem Tageslauf in M7.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    _, erfolg, meldung = services.protokoll_link_neu_senden(protokoll)
    if erfolg:
        meldung_success(request, meldung)
    else:
        meldung_error(request, meldung or "Link konnte nicht neu gesendet werden.")
    return redirect(f"/protokolle/{protokoll_nr}/")


@require_POST
@login_required
def protokoll_korrigieren(request, protokoll_nr: str):
    """F-135: POST /protokolle/<Nummer>/korrigieren/

    Erzeugt eine neue Fassung mit neuer Nummer.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_berechtigt(protokoll, request)

    neue, erfolg = services.protokoll_korrigieren(protokoll, request.user)
    if not erfolg:
        meldung_error(request, "Korrektur nicht möglich: Protokoll nicht signiert (F-135).")
        return redirect(f"/protokolle/{protokoll_nr}/")

    meldung_success(
        request,
        f"Neue Fassung {neue.nr} erzeugt (F-135)."
    )
    return redirect(f"/protokolle/{neue.nr}/")


def signieren_link(request, token: str):
    """F-136: GET /signieren/<token>/ – ohne Anmeldung.

    Zeigt das PDF und ein Formular zum Eingeben des Einmalcodes.
    POST /signieren/<token>/ – Einmalcode prüfen.
    """
    from .models import Protokoll
    protokoll = Protokoll.objects.filter(
        gegenzeichnung_token=token
    ).select_related("person", "geraet").first()
    if protokoll is None:
        return HttpResponse(
            "<html><body><h1>Unbekannter Link</h1>"
            "<p>Dieser Link ist ungültig oder abgelaufen.</p></body></html>",
            status=404,
        )

    if protokoll.gegenzeichnung_abgelaufen:
        return HttpResponse(
            "<html><body><h1>Link abgelaufen</h1>"
            "<p>Dieser Link ist nicht mehr gültig.</p>"
            "<p>Bitte wenden Sie sich an die IT.</p></body></html>",
            status=410,
        )

    if protokoll.stand == Protokoll.STAND_ABGESCHLOSSEN:
        return HttpResponse(
            "<html><body><h1>Gegenzeichnung abgeschlossen</h1>"
            f"<p>Protokoll {protokoll.nr} wurde bereits signiert.</p></body></html>",
            status=200,
        )

    # POST: Code prüfen (F-136).
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        if not code:
            return render(
                request,
                "geraete/signieren.html",
                {"protokoll": protokoll, "token": token, "fehler": "Code fehlt."},
                status=400,
            )
        from .services import protokoll_gegenzeichnen
        protokoll_2, erfolg, meldung = protokoll_gegenzeichnen(token, code, request)
        if protokoll_2 is None:
            return HttpResponse(
                "<html><body><h1>Unbekannter Link</h1></body></html>",
                status=404,
            )
        if erfolg:
            return HttpResponse(
                "<html><body><h1>Gegenzeichnung abgeschlossen</h1>"
                f"<p>Vielen Dank. Ihr Protokoll {protokoll_2.nr} ist signiert.</p>"
                "</body></html>",
                status=200,
            )
        return render(
            request,
            "geraete/signieren.html",
            {
                "protokoll": protokoll_2,
                "token": token,
                "fehler": meldung or "Code ungültig.",
            },
            status=400,
        )

    # GET: PDF und Code-Formular anzeigen.
    from . import protokoll as protokoll_modul
    from . import pdf as pdf_modul
    try:
        pdf_bytes = pdf_modul.pdf_bauen(protokoll)
    except Exception:
        pdf_bytes = b""

    return render(
        request,
        "geraete/signieren.html",
        {
            "protokoll": protokoll,
            "token": token,
        },
    )


@require_POST
def signieren_code_senden(request, token: str):
    """F-136: POST /signieren/<token>/code-senden/ – ohne Anmeldung.

    Schickt einen neuen Einmalcode per Mail an die Person.
    """
    from .models import Protokoll
    protokoll = Protokoll.objects.filter(
        gegenzeichnung_token=token
    ).select_related("person", "geraet").first()
    if protokoll is None:
        return HttpResponse(
            "<html><body><h1>Unbekannter Link</h1></body></html>",
            status=404,
        )
    if protokoll.gegenzeichnung_abgelaufen:
        return HttpResponse(
            "<html><body><h1>Link abgelaufen</h1></body></html>",
            status=410,
        )
    if protokoll.stand == Protokoll.STAND_ABGESCHLOSSEN:
        return HttpResponse(
            "<html><body><h1>Gegenzeichnung abgeschlossen</h1></body></html>",
            status=200,
        )

    from . import services
    erfolg, meldung = services.protokoll_code_senden(protokoll)
    if erfolg:
        return render(
            request,
            "geraete/signieren.html",
            {
                "protokoll": protokoll,
                "token": token,
                "meldung": "Code per Mail gesendet (F-136).",
            },
        )
    return render(
        request,
        "geraete/signieren.html",
        {
            "protokoll": protokoll,
            "token": token,
            "fehler": meldung or "Code konnte nicht gesendet werden.",
        },
        status=400,
    )


def signieren_pdf(request, token: str):
    """F-136: GET /signieren/<token>/pdf/ – ohne Anmeldung.

    Liefert das PDF des Protokolls über den Token, ohne Anmeldung.
    """
    from .models import Protokoll
    from . import pdf as pdf_modul
    protokoll = Protokoll.objects.filter(
        gegenzeichnung_token=token
    ).select_related("person", "geraet").first()
    if protokoll is None:
        return HttpResponse(
            "<html><body><h1>Unbekannter Link</h1></body></html>",
            status=404,
        )
    try:
        pdf_bytes = pdf_modul.pdf_fertig_bauen(protokoll)
    except Exception:
        return HttpResponse(
            "<html><body><h1>PDF konnte nicht erzeugt werden</h1></body></html>",
            status=500,
        )
    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'inline; filename="Protokoll-{protokoll.nr}.pdf"'
    )
    return response
