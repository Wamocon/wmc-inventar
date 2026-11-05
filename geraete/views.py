"""Ansichten für Geräte (M2 Bestand).

F-11 bis F-16 (Aufnahme, Bearbeiten, Prüfung),
F-40 bis F-42 (Auffindbarkeit, Suche, Liste),
F-84 bis F-88 (Konflikte, Datenlücken).
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.contrib.messages import error as meldung_error
from django.contrib.messages import info as meldung_info
from django.contrib.messages import success as meldung_success
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from konten.zeit import jetzt_aware
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from konten.zeit import jetzt_wie_im_entwicklungsmodus
from stammdaten.models import Kategorie, Ort, Person

from . import services
from .forms import (
    ErstinventurForm,
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
from .etiketten import format_aus_einstellungen
from .models import Gerat, GeratKonflikt, Leihe, Protokoll, Vorgang


def _qr_svg(gerat):
    """QR-Code als SVG für das Gerätedetail (F-70)."""
    from django.utils.safestring import mark_safe
    from .etiketten import qr_svg
    return mark_safe(qr_svg(gerat))


# --- Rechte -----------------------------------------------------------------

def _darf_sehen(user) -> bool:
    """Geräteliste, Gerätedetail, Historie, Dashboard, Export: Admin und Leser (Kapitel 2)."""
    return user.ist_admin or user.ist_leser


def _darf_ändern(user) -> bool:
    """Erfassen, Ändern, Vorgänge: nur Admin (Kapitel 2, F-112, N-02)."""
    return user.ist_admin


def _darf_sehen_raumplan(user) -> bool:
    """/arbeitsplaetze/…: Admin und Leser (F-110), nie Mitarbeiter (Kap. 3)."""
    return user.ist_admin or user.ist_leser


def _keine_berechtigung(request, pfad: str):
    """403 für Mitarbeiter auf /arbeitsplaetze/… (Kapitel 3 der Testschnittstelle).

    ``pfad`` ist die absolute Adresse, die im Satz vorkommt.

    """
    raise PermissionDenied(f"Zugriff verweigert: {pfad}")


# --- Grundriss (F-65, A-0913 Teil 2) -------------------------------------------

def _inhalt_typ_datei(pfad) -> str:
    """Inhaltstyp nach Dateiendung, sonst oktalstrom (A-0913)."""
    klein = str(pfad).lower()
    if klein.endswith(".svg"):
        return "image/svg+xml"
    if klein.endswith(".png"):
        return "image/png"
    if klein.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if klein.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


@login_required
def grundriss_zeige(request, plan_id: int):
    """Grundriss-Datei eines Plans aus der DATEIABLAGE liefern (F-65, A-0913).

    Adresse /arbeitsplaetze/plan/<id>/grundriss/ (TESTSCHNITTSTELLE Kapitel 4).
    Angemeldet: Admin und Mitarbeiter 200, sonst 403; ohne Anmeldung
    leitet die Anmeldung ein. Die Datei kommt aus der DATEIABLAGE, die
    Adresse bleibt stabil, wenn sich der Ablagepfad ändert.
    """
    from stammdaten.models import Plan

    if not _darf_sehen_raumplan(request.user):
        _keine_berechtigung(request, f"/arbeitsplaetze/plan/{plan_id}/grundriss/")
    plan = get_object_or_404(Plan, id=plan_id)
    if not plan.grundriss:
        raise Http404("Kein Grundriss hinterlegt.")
    datei = plan.grundriss
    pfad = datei.name
    inhalt = datei.open("rb")
    antwort = HttpResponse(inhalt, content_type=_inhalt_typ_datei(pfad))
    antwort["Content-Disposition"] = f'inline; filename="{datei.name.split("/")[-1]}"'
    if str(pfad).lower().endswith(".svg"):
        # N-02: SVG nie mit Skripten ausliefern, auch nicht beim direkten Aufruf.
        from stammdaten.uploads import CSP_SVG
        antwort["Content-Security-Policy"] = CSP_SVG
    return antwort



# --- Liste (F-41) -------------------------------------------------------------

def _geraete_export(request, geraete: list, format_export: str):
    """F-103: Liste der Geräte mit aktuellem Filter als .csv oder .xlsx."""
    from . import export as _export
    kopfzeile = [
        "Inventarnummer", "Status", "Hersteller", "Modell", "Gerätename", "Seriennummer",
        "Person", "Ort", "Kategorie", "Kaufdatum", "Garantie bis", "Fehlende Angaben",
    ]
    daten = []
    for gerat in geraete:
        daten.append({
            "Inventarnummer": gerat.inventarnummer,
            "Status": gerat.status_anzeige,
            "Hersteller": gerat.hersteller,
            "Modell": gerat.modell,
            "Gerätename": gerat.geraetename,
            "Seriennummer": gerat.seriennummer,
            "Fehlende Angaben": gerat.datenluecken_text(),
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


def _suche(q: str) -> Q:
    """F-44: Treffer nach Inventarnummer, Seriennummer, Modell, Hostname und Person.

    Bei der Person muss jedes Wort im Vor- oder Nachnamen stehen: „Anna Becker“
    trifft Vorname und Nachname, auch in anderer Reihenfolge.
    """
    person = Q()
    for wort in q.split():
        person &= Q(person__vorname__icontains=wort) | Q(person__nachname__icontains=wort)
    return (
        Q(inventarnummer__icontains=q)
        | Q(geraetename__icontains=q)
        | Q(seriennummer__icontains=q)
        | Q(modell__icontains=q)
        | person
    )


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
    archiv = request.GET.get("archiv") == "1"

    # Kapitel 3: Filter kombinierbar. Ausgemusterte Geräte nur mit archiv=1 (F-58).
    alle = Gerat.objects.select_related("person", "ort", "kategorie", "zuletzt_geprueft_von")
    qs = alle.filter(status=Gerat.STATUS_AUSGEMUSTERT) if archiv \
        else alle.exclude(status=Gerat.STATUS_AUSGEMUSTERT)
    if status:
        qs = qs.filter(status=status)
    if ort_id:
        # Ort-Filter: Kennung (Kapitel 3) oder Datenbanknummer (ältere Links).
        if ort_id.isdigit():
            qs = qs.filter(ort_id=ort_id)
        else:
            qs = qs.filter(ort__kennung=ort_id)
    if kategorie_id:
        # Kategorie-Filter: Name (Kapitel 3) oder Datenbanknummer (ältere Links).
        if kategorie_id.isdigit():
            qs = qs.filter(kategorie_id=kategorie_id)
        else:
            qs = qs.filter(kategorie__name__iexact=kategorie_id)
    if person_id:
        qs = qs.filter(person_id=person_id) if person_id.isdigit() else qs.none()

    archiv_treffer = 0
    if q:
        treffer = _suche(q)
        # Ohne archiv=1 erscheint das ausgemusterte Gerät nicht; die Zahl führt hin.
        if not archiv:
            archiv_treffer = alle.filter(treffer, status=Gerat.STATUS_AUSGEMUSTERT).distinct().count()
        qs = qs.filter(treffer).distinct()

    aufsteigend = request.GET.get("sort") != "absteigend"
    qs = qs.order_by("inventarnummer" if aufsteigend else "-inventarnummer")

    if unvollstaendig:
        qs = [g for g in qs if g.ist_unvollstaendig()]
    else:
        qs = list(qs)
    anzahl = len(qs)
    # Prototyp: Status mit ihren Zahlen über der Liste; nur Links auf den Filter.
    status_chips = [
        {"code": code, "label": label, "zahl": Gerat.objects.filter(status=code).count()}
        for code, label in Gerat.STATUSES if code != Gerat.STATUS_AUSGEMUSTERT
    ]

    # F-103 (A-0907, M7 Teil 3): Export der Liste mit aktuellem Filter.
    format_export = (request.GET.get("format") or "").strip().lower()
    if format_export in ("csv", "xlsx"):
        return _geraete_export(request, qs, format_export)

    # Erstinventur-Fortschritt je Ort, sobald nach ort gefiltert (F-89, Kap. 4):
    # Markierung ``inventur-fortschritt`` mit ``ist`` und ``gesamt``.
    fortschritt = None
    ort = None
    if ort_id:
        ort = Ort.objects.filter(pk=ort_id).first() if ort_id.isdigit() \
            else Ort.objects.filter(kennung=ort_id).first()
    if ort:
        fortschritt = services.fortschritt_des_orts(ort)
    kategorie = None
    if kategorie_id:
        kategorie = Kategorie.objects.filter(pk=kategorie_id).first() if kategorie_id.isdigit() \
            else Kategorie.objects.filter(name__iexact=kategorie_id).first()

    # Export und Filter bleiben beieinander (F-103).
    filter_werte = {
        "q": q, "status": status, "ort": ort_id, "kategorie": kategorie_id, "person": person_id,
        "unvollstaendig": "1" if unvollstaendig else "", "archiv": "1" if archiv else "",
    }

    return render(
        request,
        "geraete/liste.html",
        {
            "geraete": qs,
            "anzahl": anzahl,
            "suche": q,
            "status_filter": status,
            "ort_filter": ort.kennung if ort else "",
            "kategorie_filter": kategorie.name if kategorie else "",
            "person_filter": person_id,
            "unvollstaendig": unvollstaendig,
            "archiv": archiv,
            "archiv_treffer": archiv_treffer,
            "archiv_zahl": Gerat.objects.filter(status=Gerat.STATUS_AUSGEMUSTERT).count(),
            "filter_query": urlencode({k: v for k, v in filter_werte.items() if v}),
            "aufsteigend": aufsteigend,
            "statuser": [c for c in Gerat.STATUSES if c[0] != Gerat.STATUS_AUSGEMUSTERT],
            "status_chips": status_chips,
            "status_gesamt": sum(c["zahl"] for c in status_chips),
            "orte": Ort.objects.all(),
            "kategorien": sorted(Kategorie.objects.all(), key=lambda k: k.name),
            "personen": Person.objects.all(),
            "koennen_aendern": _darf_ändern(request.user),
            "fortschritt": fortschritt,
            "etikett_pro_bogen": format_aus_einstellungen().pro_bogen,
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
    doppelte_serien = gerat.seriennummer_auch_bei()
    # F-14 (A-0099): Löschen ist nur für Admin, solange außer Aufnahme
    # kein Vorgang existiert; sonst fehlt die Aktion im HTML.
    kann_loeschen = (
        request.user.ist_admin
        and gerat.vorgaenge.exclude(typ=Vorgang.TYP_AUFNAHME).count() == 0
        and not gerat.alle_protokolle().exists()
        and not gerat.leihen.exists()
    )
    return render(
        request,
        "geraete/detail.html",
        {
            "gerat": gerat,
            "offene_konflikte": offene_konflikte,
            "doppelte_namen": doppelte_namen,
            "doppelte_serien": doppelte_serien,
            "datenluecken": gerat.datenluecken_text(),
            "koennen_aendern": _darf_ändern(request.user),
            "ist_admin": request.user.ist_admin,
            "kann_loeschen": kann_loeschen,
            "inventur": _inventur(request, gerat),
            # F-70: QR-Code im Gerätedetail
            "qr_inhalt": f"{settings.BASIS_URL}/g/{gerat.inventarnummer}",
            "qr_svg": _qr_svg(gerat),
            # F-72, Kapitel 6: Etiketten sind ein Bildschirm des Admins, der Leser ändert nichts.
            "kann_etikett_sehen": request.user.ist_admin,
            "protokolle": gerat.alle_protokolle(),
            "reparatur_offen": gerat.vorgaenge.filter(typ=Vorgang.TYP_REPARATUR, abschliesst=False).order_by("-id").first()
            if gerat.status == Gerat.STATUS_IN_REPARATUR else None,
            "ausmusterung": gerat.vorgaenge.filter(typ=Vorgang.TYP_AUSMUSTERUNG).order_by("-id").first()
            if gerat.status == Gerat.STATUS_AUSGEMUSTERT else None,
            "loeschung_arten": services.LOESCHUNG_ARTEN,
            "platz_im_plan": _platz_im_plan(gerat),
        },
    )


def _inventur(request, gerat: Gerat) -> dict | None:
    """Was die mobile Detailseite nach dem Scan für die Erstinventur braucht (F-89)."""
    if not request.user.ist_admin or gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        return None
    fortschritt = services.fortschritt_des_orts(gerat.ort) if gerat.ort_id else None
    naechstes = None
    if gerat.ort_id:
        offene = Gerat.objects.filter(
            ort_id=gerat.ort_id, zuletzt_geprueft_am__isnull=True,
        ).exclude(pk=gerat.pk).exclude(status=Gerat.STATUS_AUSGEMUSTERT)
        naechstes = min(
            offene,
            key=lambda g: (not g.geraetename, g.geraetename.lower(), g.inventarnummer),
            default=None,
        )
    return {
        "fortschritt": fortschritt,
        "naechstes": naechstes,
        "orte": Ort.objects.order_by("kennung"),
        "zustaende": Gerat.ZUSTAENDE,
        "seriennummer_fehlt": not gerat.seriennummer,
        "kaufdatum_fehlt": not gerat.kaufdatum and not gerat.kaufdatum_nicht_ermittelbar,
        "garantie_fehlt": not gerat.garantie_bis and not gerat.garantie_nicht_ermittelbar,
    }


def _platz_im_plan(gerat: Gerat) -> Ort | None:
    """F-69: Wo steht das Gerät im Raumplan?

    Der eigene Ort, sonst der feste Platz der Person, etwa beim Notebook. Ohne
    Plan und Position (Lager) gibt es nichts zu zeigen.
    """
    if gerat.ort_id:
        return gerat.ort if gerat.ort.plan_id and gerat.ort.hat_position else None
    if gerat.person_id:
        return gerat.person.feste_plaetze.filter(
            plan_id__isnull=False, position_x__isnull=False, position_y__isnull=False
        ).order_by("kennung").first()
    return None


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
    """Seriennummern aus dem POST (F-11, A-0112).

    Das Textfeld ``seriennummern`` enthält zeilenweise die Seriennummern, leere
    Zeilen zählen nicht. Steht dazu etwas im Einzelfeld ``seriennummer``, kommt
    es als erste Nummer dazu, statt ohne Hinweis zu verschwinden.
    """
    zeilen = [z.strip() for z in (request.POST.get("seriennummern") or "").splitlines()]
    liste = [z for z in zeilen if z]
    einzeilig = (request.POST.get("seriennummer") or "").strip()
    if einzeilig and einzeilig not in liste:
        liste.insert(0, einzeilig)
    return liste


@login_required
@require_POST
def neu_anlegen(request):
    """Speichern (F-10 bis F-13).

    F-11: Es entstehen so viele Geräte wie Zeilen, oder bei einem Fehler gar keins;
    die Eingaben bleiben im Formular stehen. F-12: „Speichern und Etikett drucken“
    liefert das PDF für alle neuen Geräte.
    """
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Anlegen ist Ihnen nicht erlaubt.")
    form = GeratForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "geraete/neu.html", {"form": form})
    daten = _stammdaten_aus_form(dict(form.cleaned_data))
    # Kapitel 4: Auf Lager heißt Lagerort.
    daten["ort"] = daten.get("ort") or services.standard_lager()
    serienliste = _seriennummern_auetzen(request)
    try:
        with transaction.atomic():
            erstellte = [
                services.gerat_anlegen(
                    erzeugt_von=request.user, pruefen=True, seriennummer=seriennummer, **daten,
                )
                for seriennummer in (serienliste or [""])
            ]
    except services.GeratFehler as fehler:
        form.add_error(None, str(fehler))
        return render(request, "geraete/neu.html", {"form": form})
    etikett = request.POST.get("aktion") == "etikett"
    if len(erstellte) == 1:
        meldung_success(request, f"Gerät {erstellte[0].inventarnummer} angelegt.")
    else:
        meldung_success(request, f"{len(erstellte)} Geräte angelegt.")
    if etikett:
        from .etiketten import bogen_pdf, etikett_pdf
        if len(erstellte) == 1:
            pdf, name = etikett_pdf(erstellte[0]), f"etikett-{erstellte[0].inventarnummer}.pdf"
        else:
            pdf, name = bogen_pdf(erstellte, startposition=1), f"etiketten-bogen-{len(erstellte)}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{name}"'
        return response
    if len(erstellte) == 1:
        return redirect("/geraete/" + erstellte[0].inventarnummer + "/")
    return redirect("/geraete/")


@login_required
def neu_anzeigen(request):
    """Formularseite für ein neues Gerät (F-11 bis F-14, A-0112).

    F-13: ``?vorlage=<Inventarnummer>`` übernimmt die Stammdaten des
    genannten Geräts; die Seriennummer bleibt leer.
    """
    if not _darf_ändern(request.user):
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
                "ort": vorlage.ort if vorlage.ort and vorlage.ort.typ == Ort.TYP_LAGER else None,
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
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Ändern ist Ihnen nicht erlaubt.")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    # F-58 (A-0097): Ausgemusterte Geräte sind nicht mehr änderbar.
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        meldung_error(request, "Ausgemusterte Geräte sind nicht mehr änderbar.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    if request.method == "POST":
        form = GeratForm(request.POST, instance=gerat)
        if form.is_valid():
            try:
                werte = dict(form.cleaned_data)
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
    # F-69: ?hervorheben=<Kennung> öffnet den Plan des Orts, auf jedem Plan.
    # Die ältere Form Standort|Kennung bleibt gültig.
    kennung = request.GET.get("hervorheben", "").rsplit("|", 1)[-1].strip()
    ort_hervor = Ort.objects.filter(kennung=kennung).first() if kennung else None
    plan = next((p for p in plane if ort_hervor and p.id == ort_hervor.plan_id), None)
    hervorheben = ort_hervor.kennung if plan else ""
    if plan is None:
        param_plan = request.GET.get("plan", "")
        if "|" in param_plan:
            standort, etage = param_plan.split("|", 1)
            plan = services.plan_finde(standort, etage)
        elif param_plan:
            plan = next((p for p in plane if str(p.id) == param_plan), None)
        if plan is None and plane:
            plan = plane[0]
    if plan is None:
        plaetze, raumorte, ohne_pos = [], [], []
    else:
        plaetze = services.plaetze_des_plans(plan)
        raumorte = services.raumorte_des_plans(plan)
        ohne_pos = services.ohne_position(plan)
    anzeige = request.GET.get("ansicht", "raumplan")
    if anzeige not in ("raumplan", "liste"):
        anzeige = "raumplan"
    nur_unvollstaendig = bool(request.GET.get("unvollstaendig"))

    def _platz_zusatz(p):
        """Klasse, Symbol, Text (F-62, TESTSCHNITTSTELLE 5), data-soll-ist (Kapitel 4)."""
        ergebnis = p["abgleich"]["ergebnis"]
        if ergebnis == "vollstaendig":
            return "vollstaendig", "✓", "vollständig", "vollstaendig"
        if ergebnis == "mehr-als-soll":
            return "zuviel", "+", "mehr als Soll", "mehr"
        return "fehlt", "−", "unvollständig", "unvollstaendig"

    plaetze_reich = []
    for p in plaetze:
        klasse, zeichen, text, soll_ist = _platz_zusatz(p)
        fehlt = ", ".join(f"fehlt: {a} × {k.name}" for k, a in p["abgleich"]["fehlend"])
        plaetze_reich.append(
            {
                **p,
                "klasse": klasse,
                "zeichen": zeichen,
                "text": text,
                "soll_ist": soll_ist,
                # F-65: Screenreader hören dasselbe wie das Bild zeigt.
                "beschriftung": ", ".join(
                    t for t in (f"Arbeitsplatz {p['ort'].kennung}", text, fehlt) if t
                ),
            }
        )
    for raum in raumorte:
        raum.geraete_anzahl = len(services.gerate_am_ort(raum))

    unvollstaendig = [p for p in plaetze_reich if p["abgleich"]["ergebnis"] == "unvollstaendig"]
    plaetze_anzeige = unvollstaendig if anzeige == "liste" and nur_unvollstaendig else plaetze_reich
    return render(
        request,
        "geraete/raumplan.html",
        {
            "plane": plane,
            "plan_auswahl": plan,
            "plaetze": plaetze_anzeige,
            "plaetze_gesamt": len(plaetze_reich),
            "raumorte": raumorte,
            "ohne_pos": ohne_pos,
            "ohne_position": ohne_pos,
            "unvollstaendig": unvollstaendig,
            "hervorheben": hervorheben,
            "koennen_aendern": _darf_ändern(request.user),
            "bearbeiten_kann": _darf_ändern(request.user),
            "anzeige": anzeige,
            "anzeige_raumplan": anzeige == "raumplan",
            "anzeige_liste": anzeige == "liste",
            "nur_unvollstaendig": nur_unvollstaendig,
            # Wie im Prototyp: Mehr als Soll hat seine Soll-Ausstattung.
            "ok_anzahl": len(plaetze_reich) - len(unvollstaendig),
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

    # F-103: Export der Liste, dieselbe Adresse mit format= (Kapitel 3).
    format_export = (request.GET.get("format") or "").strip().lower()
    if format_export in ("csv", "xlsx"):
        from . import export as _export
        kopfzeile = ["Kennung", "Raum", "Feste Person", "Profil", "Soll-Ist", "Fehlt", "Mehr"]
        ergebnis_text = {"vollstaendig": "vollständig", "unvollstaendig": "unvollständig",
                         "mehr-als-soll": "mehr als Soll"}
        daten = [{
            "Kennung": z["ort"].kennung,
            "Raum": z["ort"].raum,
            "Feste Person": z["ort"].feste_person.voller_name() if z["ort"].feste_person else "",
            "Profil": z["ort"].profil.name if z["ort"].profil else "",
            "Soll-Ist": ergebnis_text.get(z["abgleich"]["ergebnis"], ""),
            "Fehlt": [f"{a} × {k.name}" for k, a in z["abgleich"]["fehlend"]],
            "Mehr": [f"{a} × {k.name}" for k, a in z["abgleich"]["zuviel"]],
        } for z in zeilen]
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, "arbeitsplaetze")
        return _export.antwort_xlsx(kopfzeile, daten, "arbeitsplaetze")

    return render(
        request,
        "geraete/arbeitsplaetze_liste.html",
        {
            "zeilen": zeilen,
            # F-63: Liste aller Plätze und daneben die Summe je Kategorie.
            "uebersicht": services.bedarf_uebersicht(),
            "koennen_aendern": _darf_ändern(request.user),
        },
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
            "etage": _etage_des_orts(ort),
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

    # F-103: Export der Liste, dieselbe Adresse mit format= (Kapitel 3).
    format_export = (request.GET.get("format") or "").strip().lower()
    if format_export in ("csv", "xlsx"):
        from . import export as _export
        kopfzeile = ["Kategorie", "Fehlt", "Auf Lager"]
        daten = [{
            "Kategorie": kategorie.name,
            "Fehlt": anzahl,
            "Auf Lager": uebersicht["lagerbestand"].get(kategorie, 0),
        } for kategorie, anzahl in uebersicht["summe"].items()]
        if format_export == "csv":
            return _export.antwort_csv(kopfzeile, daten, "bedarf")
        return _export.antwort_xlsx(kopfzeile, daten, "bedarf")

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
    # F-89: Gesamt heißt alle Geräte, auch die ohne Ort (nur bei einer Person).
    aktive = Gerat.objects.exclude(status=Gerat.STATUS_AUSGEMUSTERT)
    total_geprueft = aktive.filter(zuletzt_geprueft_am__isnull=False).count()
    total_alle = aktive.count()
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
    ort.aktualisiert_am = jetzt_aware()
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
            "etage": _etage_des_orts(ort),
            "abgleich": abgleich,
            "gerate": gerate,
            "personen_gerate": personen_gerate,
            "koennen_aendern": _darf_ändern(request.user),
        },
    )


def _etage_des_orts(ort: Ort) -> str:
    """Etage aus dem Plan des Orts, für die Kopfzeile des Pop-ups (F-66)."""
    from stammdaten.models import Plan

    plan = Plan.objects.filter(pk=ort.plan_id).first() if ort.plan_id else None
    return plan.etage if plan else ""


@login_required
def platz_ausgeben(request, kennung: str):
    """F-66: „Fehlendes vom Lager ausgeben“ für einen Arbeitsplatz.

    Adresse /arbeitsplaetze/<Kennung>/ausgeben/. GET zeigt je fehlender Kategorie
    die freien Lagergeräte, die nötigen sind vorbelegt; POST gibt die gewählten aus.
    """
    if not _darf_ändern(request.user):
        _keine_berechtigung(request, f"/arbeitsplaetze/{kennung}/ausgeben/")
    ort = get_object_or_404(Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ), kennung=kennung)
    if request.method == "POST":
        try:
            anzahl = services.fehlendes_ausgeben(
                ort, request.POST.getlist("gerat"), ausgefuehrt_von=request.user
            )
        except services.GeratFehler as fehler:
            meldung_error(request, str(fehler))
            return redirect(f"/arbeitsplaetze/{ort.kennung}/ausgeben/")
        meldung_success(request, f"{anzahl} Gerät(e) an {ort.kennung} ausgegeben.")
        return redirect(f"/arbeitsplaetze/{ort.kennung}/")
    return render(
        request,
        "geraete/platz_ausgeben.html",
        {"ort": ort, "zeilen": services.fehlendes_vom_lager(ort)},
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    # F-58: Ausgemusterte Geräte sind nicht mehr änderbar.
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        meldung_error(request, "Ausgemusterte Geräte sind nicht mehr änderbar.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    if request.method == "POST":
        form = GeratNotizForm(request.POST)
        if form.is_valid():
            services.gerat_bearbeiten(
                gerat, werte={"notiz": form.cleaned_data.get("notiz", "")}, erzeugt_von=request.user,
            )
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    # F-89: Der Dialog auf der Detailseite trägt nach, was fehlt; ohne Felder nur „Geprüft“.
    form = ErstinventurForm(request.POST)
    if not form.is_valid():
        for fehler_liste in form.errors.values():
            for fehler in fehler_liste:
                meldung_error(request, fehler)
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    daten = form.cleaned_data
    werte = {}
    if daten["seriennummer"] and not gerat.seriennummer:
        werte["seriennummer"] = daten["seriennummer"].strip()
    if daten["zustand"] and daten["zustand"] != gerat.zustand:
        werte["zustand"] = daten["zustand"]
    for feld in ("kaufdatum", "garantie_bis"):
        if daten[feld] and not getattr(gerat, feld):
            werte[feld] = daten[feld]
    for feld in ("kaufdatum_nicht_ermittelbar", "garantie_nicht_ermittelbar"):
        if daten[feld]:
            werte[feld] = True
    try:
        services.erstinventur_bestaetigen(
            gerat, werte=werte, ziel_ort=daten["ziel_ort"], geprueft_von=request.user,
        )
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    meldung_success(request, f"Prüfung für {gerat.inventarnummer} erfasst.")
    return redirect("/geraete/" + gerat.inventarnummer + "/")


# --- Konflikt lösen (F-86) ----------------------------------------------------------

@login_required
@require_POST
def konflikt_loesen(request, inventarnummer: str, konflikt_id: int):
    """Konflikt: alten Wert behalten oder neuen übernehmen (F-86)."""
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    konflikt = get_object_or_404(GeratKonflikt, pk=konflikt_id, gerat=gerat)
    nehmen = request.POST.get("nehmen", "")
    try:
        services.konflikt_loesen(konflikt, nehmen, ausgefuehrt_von=request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
        return redirect("/geraete/" + gerat.inventarnummer + "/")
    meldung_success(request, f"Konflikt zu „{konflikt.feld_anzeige}“ gelöst.")
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratAusgabeForm(request.POST, gerat=gerat)
        if form.is_valid():
            ziel_person = form.cleaned_data.get("ziel_person")
            ziel_ort = form.cleaned_data.get("ziel_ort")
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
            if ziel_person is not None:
                _fotos_anhaengen(request, gerat.alle_protokolle().first(), gerat)
            meldung_success(request, "Gerät ausgegeben.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratAusgabeForm(gerat=gerat)
    return render(request, "geraete/ausgabe.html", {"gerat": gerat, "form": form})


def _fotos_anhaengen(request, protokoll, gerat=None) -> None:
    """Fotos aus dem Dialog (F-134). Ein abgelehntes Foto hält den Vorgang nicht auf."""
    from . import protokoll as protokoll_services

    if protokoll is None:
        return
    for datei in request.FILES.getlist("fotos"):
        try:
            protokoll_services.foto_hochladen(
                protokoll, datei, request.user,
                inventarnummer=gerat.inventarnummer if gerat is not None else "",
            )
        except services.GeratFehler as fehler:
            meldung_error(request, f"{datei.name}: {fehler}")


@login_required
def sammelausgabe(request):
    """Mehrere Geräte aus der Liste ausgeben, mit einem Protokoll (F-20, F-24)."""
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    daten = request.POST if request.method == "POST" else request.GET
    # Aus der Geräteliste kommt nur die Auswahl, ausgefüllt wird danach.
    nur_auswahl = request.POST.get("aktion") == "waehlen"
    gewaehlt = list(
        Gerat.objects.filter(inventarnummer__in=daten.getlist("auswahl"))
        .select_related("kategorie").order_by("inventarnummer")
    )
    geraete = [g for g in gewaehlt if not services.ausgabe_sperrgrund(g)]
    gesperrt = [(g, services.ausgabe_sperrgrund(g)) for g in gewaehlt if services.ausgabe_sperrgrund(g)]
    form = GeratAusgabeForm(None if nur_auswahl else (request.POST or None), initial={
        "ziel_person": request.GET.get("person"), "ziel_ort": request.GET.get("ort"),
    })
    # Die Zeilen tragen Zustand, Zubehör und Bemerkung je Gerät, nicht die Felder des Einzeldialogs.
    del form.fields["zustand"], form.fields["zubehoer_komplett"], form.fields["anmerkung"]
    if request.method == "POST" and not nur_auswahl and form.is_valid():
        ziel_person = form.cleaned_data.get("ziel_person")
        ziel_ort = form.cleaned_data.get("ziel_ort")
        eingaben = {
            g.inventarnummer: {
                "zustand": request.POST.get(f"zustand-{g.inventarnummer}") or g.zustand,
                "zubehoer_komplett": request.POST.get(f"zubehoer-{g.inventarnummer}", "ja") == "ja",
                "anmerkung": request.POST.get(f"anmerkung-{g.inventarnummer}", ""),
            }
            for g in geraete
        }
        try:
            protokoll = services.geraete_ausgeben(
                geraete,
                ziel_person or ziel_ort,
                ziel_ort=ziel_ort,
                eingaben=eingaben,
                ausgefuehrt_von=request.user,
                unterschrift=form.cleaned_data.get("unterschrift", "papier"),
            )
        except services.GeratFehler as fehler:
            form.add_error(None, str(fehler))
        else:
            meldung_success(request, f"{len(geraete)} Geräte ausgegeben.")
            if protokoll is not None:
                return redirect(f"/protokolle/{protokoll.nr}/")
            return redirect("/geraete/")
    return render(request, "geraete/sammelausgabe.html", {
        "form": form,
        "geraete": geraete,
        "gesperrt": gesperrt,
        "zustaende": Gerat.ZUSTAENDE,
    })


@login_required
def rueckgeben(request, inventarnummer: str):
    """Gerät zurückgeben (F-50, F-51, F-141)."""
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    if request.method == "POST":
        form = GeratRueckgabeForm(request.POST, gerat=gerat)
        if form.is_valid():
            # F-50, F-57: „Fehlt“ führt in den Dialog, die Meldung bestätigt dort ein Mensch.
            if form.cleaned_data.get("fehlend"):
                return redirect(f"/geraete/{gerat.inventarnummer}/ausmustern/?grund=verloren")
            person = gerat.person
            try:
                services.gerat_rueckgeben(
                    gerat,
                    zustand_rueckgabe=form.cleaned_data.get("zustand_rueckgabe", 2),
                    zubesehoer_komplett=form.cleaned_data.get("zubehoer_komplett") == "ja",
                    maengel=form.cleaned_data.get("maengel", ""),
                    ziel=form.cleaned_data.get("ziel", "lager"),
                    ausgefuehrt_von=request.user,
                    unterschrift=form.cleaned_data.get("unterschrift") or "tool",
                    empfaenger=form.cleaned_data.get("empfaenger", ""),
                    lagerort=form.cleaned_data.get("lager_ort"),
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            if person is not None:
                _fotos_anhaengen(request, gerat.alle_protokolle().first(), gerat)
            meldung_success(request, "Gerät zurückgegeben.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratRueckgabeForm(gerat=gerat)
    return render(request, "geraete/rueckgabe.html", {"gerat": gerat, "form": form})


@login_required
def umziehen(request, inventarnummer: str):
    """Gerät umziehen (F-41, M3)."""
    if not _darf_ändern(request.user):
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
    gerat = get_object_or_404(Gerat, inventarnummer=inventarnummer)
    # Kapitel 4: Den Umzug kennt nur „In Benutzung“.
    if gerat.status != Gerat.STATUS_IN_BENUTZUNG:
        meldung_error(request, "Nur Geräte in Benutzung können umgezogen werden.")
        return redirect("/geraete/" + gerat.inventarnummer + "/")
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
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
                    lagerort=form.cleaned_data.get("lager_ort"),
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
        raise PermissionDenied("Zugriff verweigert: Vorgänge macht die IT.")
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
                    loeschung_datei=form.cleaned_data.get("loeschung_datei"),
                    bestaetigt_gemeldt=form.cleaned_data.get("bestaetigt_gemeldt", False),
                    ausgefuehrt_von=request.user,
                )
            except services.GeratFehler as fehler:
                meldung_error(request, str(fehler))
                return redirect("/geraete/" + gerat.inventarnummer + "/")
            meldung_success(request, "Gerät ausgemustert.")
            return redirect("/geraete/" + gerat.inventarnummer + "/")
    else:
        form = GeratAusmusterungForm(gerat=gerat, initial={"grund": request.GET.get("grund", "")})
    return render(request, "geraete/ausmusterung.html", {"gerat": gerat, "form": form})


@login_required
def nachweis_zeigen(request, inventarnummer: str, vorgang_id: int):
    """Löschnachweis am Gerät (F-56), für Admin und Leser."""
    if not _darf_sehen(request.user):
        raise PermissionDenied("Zugriff verweigert.")
    vorgang = get_object_or_404(Vorgang, pk=vorgang_id, gerat__inventarnummer=inventarnummer)
    if not vorgang.nachweis_datei:
        raise Http404
    from .protokoll import _typ_am_inhalt
    with vorgang.nachweis_datei.open("rb") as handle:
        roh = handle.read()
    antwort = HttpResponse(roh, content_type=_typ_am_inhalt(roh) or "application/octet-stream")
    antwort["Content-Disposition"] = f'attachment; filename="{vorgang.nachweis_datei.name.rsplit("/", 1)[-1]}"'
    return antwort


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
    # Ein offener Entwurf oder eine Anfrage darf nicht still mitverschwinden.
    if gerat.alle_protokolle().exists() or gerat.leihen.exists():
        meldung_error(request, "Für das Gerät gibt es ein Protokoll oder eine Leihe. Bitte zuerst dort klären.")
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

    Für den Admin (Kapitel 6: Bildschirm Etiketten; Testschnittstelle 3: /etiketten/).
    """
    if not request.user.ist_admin:
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

    POST mit einem Feld auswahl je Kästchen (auch kommagetrennt) und startposition.
    Mit vorschau=1 die Druckvorschau (Kapitel 6) statt des PDF.
    Für Admin (Kapitel 6 der Anforderungen: Bildschirm Etiketten nur für den Admin).
    """
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return render(request, "konten/keine_berechtigung.html", status=403)

    if request.method != "POST":
        meldung_error(request, "Bitte die Auswahl mit POST an /etiketten/auswahl/ übermitteln.")
        return redirect("/geraete/")

    # Jedes Kästchen schickt ein eigenes Feld; alle zählen, je Nummer einmal.
    inventarnummern = list(dict.fromkeys(
        nr.strip()
        for auswahl in request.POST.getlist("auswahl")
        for nr in auswahl.split(",")
        if nr.strip()
    ))
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

    from .etiketten import bogen_pdf, startposition_lesen, vorschau_seiten
    fmt = format_aus_einstellungen()
    try:
        start_int = startposition_lesen(request.POST.get("startposition"), fmt)
    except ValueError as fehler:
        meldung_error(request, str(fehler))
        return redirect("/geraete/")

    if request.POST.get("vorschau"):
        return render(request, "geraete/etiketten.html", {
            "format": fmt,
            "startposition": start_int,
            "auswahl_nummern": [g.inventarnummer for g in geraete],
            "anzahl_etiketten": len(geraete),
            "seiten": vorschau_seiten(geraete, start_int, fmt),
        })

    pdf = bogen_pdf(geraete, startposition=start_int, fmt=fmt)
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
    Mit ?ort=<Kennung>: der Bogen für diesen Ort als application/pdf,
    mit zusätzlich vorschau=1 die Druckvorschau (Kapitel 6).
    """
    if not request.user.ist_admin:
        meldung_error(request, "Zugriff verweigert: Diese Ansicht ist Ihnen nicht erlaubt.")
        return render(request, "konten/keine_berechtigung.html", status=403)

    from .etiketten import bogen_pdf, etiketten_fuer_ort, startposition_lesen, vorschau_seiten

    fmt = format_aus_einstellungen()
    orte = list(
        Ort.objects.filter(typ__in=(Ort.TYP_ARBEITSPLATZ, Ort.TYP_LAGER)).order_by("kennung")
    )
    kontext = {
        "orte": orte,
        "anzahl_orte": len(orte),
        "ausgewaehlt": request.GET.get("ort", ""),
        "format": fmt,
        "startposition": 1,
    }
    ort_kennung = (request.GET.get("ort") or "").strip()
    if ort_kennung:
        ort = Ort.objects.filter(kennung=ort_kennung).first()
        if ort is None:
            meldung_error(request, f"Ort {ort_kennung} wurde nicht gefunden.")
            return redirect("/geraete/")

        geraete = etiketten_fuer_ort(ort)
        if not geraete:
            meldung_error(request, f"Keine Geräte am Ort {ort.kennung}.")
            return redirect("/etiketten/")

        try:
            start_int = startposition_lesen(request.GET.get("startposition"), fmt)
        except ValueError as fehler:
            meldung_error(request, str(fehler))
            return redirect("/etiketten/")

        if request.GET.get("vorschau"):
            kontext.update(
                startposition=start_int,
                anzahl_etiketten=len(geraete),
                seiten=vorschau_seiten(geraete, start_int, fmt),
            )
            return render(request, "geraete/etiketten.html", kontext)

        pdf = bogen_pdf(geraete, startposition=start_int, fmt=fmt)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="etiketten-{ort.kennung}.pdf"'
        return response

    return render(request, "geraete/etiketten.html", kontext)


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
    form = VerleihForm(
        request.POST or None,
        initial={"rueckgabe_bis": jetzt_wie_im_entwicklungsmodus().date() + timedelta(days=7)},
    )

    fehler = ""

    if request.method == "POST" and form.is_valid():
        try:
            person = form.cleaned_data["person"]
            rueckgabe_bis = form.cleaned_data["rueckgabe_bis"]
            zweck = form.cleaned_data["zweck"]
            unterschrift = form.cleaned_data.get("unterschrift", "papier")
            leihe = leih_gerat_ausgeben(
                gerat=gerat,
                person=person,
                rueckgabe_bis=rueckgabe_bis,
                zweck=zweck,
                ausgefuehrt_von=request.user,
                unterschrift=unterschrift,
            )
            offen = leihe.offenes_protokoll
            if offen is not None:
                meldung_success(
                    request,
                    f"Protokoll {offen.nr} angelegt. Das Gerät wird mit Ihrer Signatur verliehen.",
                )
            else:
                meldung_success(request, "Gerät wurde verliehen.")
            return redirect("geraete:detail", inventarnummer=inventarnummer)
        except GeratFehler as e:
            fehler = str(e)

    return render(
        request,
        "geraete/verleih.html",
        {
            "form": form,
            "gerat": gerat,
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

    if not _ist_admin(request):
        raise PermissionDenied

    leihen = list(
        Leihe.objects.all()
        .select_related("gerat", "person", "kat")
        .order_by("-zeitpunkt")
    )

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
        },
    )


# --- M5 Teil 2: Anfrage und Entscheidung (A-0118) ---------------------------

def _eigene_person(request):
    """Kapitel 3: /meine-geraete/… für Mitarbeiter, für Admin und Leser mit Person."""
    if not _ist_mitarbeiter(request):
        if not (request.user.ist_admin or request.user.ist_leser):
            raise PermissionDenied
        if request.user.person is None:
            raise PermissionDenied
    return request.user.person


def _datum_oder_nichts(text):
    """Datum aus einem Formularwert; was keines ist, zählt als nicht gewählt."""
    if isinstance(text, date):
        return text
    try:
        return parse_date(text or "")
    except ValueError:
        return None


def _leihpool_anfragbar():
    """F-31: Geräte, die in der Anfrage wählbar sind: Leihpool ohne Ausgemusterte."""
    return (
        Gerat.objects.filter(leihpool=True)
        .exclude(status=Gerat.STATUS_AUSGEMUSTERT)
        .select_related("kategorie")
        .order_by("inventarnummer")
    )


def _anfrage_auswahl(kategorie, von, bis):
    """F-31: Anzeige der freien Geräte und Einträge für „Inventarnummer (optional)“."""
    if kategorie is None:
        return {"text": "", "art": "info", "frei": 0, "gesamt": 0, "geraete": []}
    stand = services.leihe_verfuegbarkeit(kategorie, von, bis)
    geraete = stand["frei"] if stand["text"] else stand["einsetzbar"]
    return {
        "text": stand["text"],
        "art": stand["art"],
        "frei": len(stand["frei"]),
        "gesamt": stand["gesamt"],
        "geraete": [
            {"id": g.pk, "text": services.leihgeraet_bezeichnung(g)} for g in geraete
        ],
    }


@login_required
def meine_geraete_zeige(request):
    """/meine-geraete/ – Meine Geräte (F-110, F-111, Kapitel 3).

    Zeigt die eigenen Geräte mit Inventarnummer, Ausgabedatum und
    Protokoll-PDF, die eigenen Protokolle und „Meine Leihen“ mit Stand,
    Rückgabedatum und dem Weg zu „Leihgerät anfragen“.
    Kapitel 3: 200 für Mitarbeiter; 200 auch für Admin und Leser,
    wenn das Konto eine Person hat; sonst 403.
    """
    person = _eigene_person(request)

    # Ohne Person gäbe filter(person=None) die Geräte ohne Zuordnung aus (F-112).
    geräte = list(Gerat.objects.filter(person=person).order_by("inventarnummer")) if person else []

    ausgaben = {}
    protokoll_je_gerat = {}
    for vorgang in Vorgang.objects.filter(
        typ=Vorgang.TYP_AUSGABE, gerat__in=geräte
    ).order_by("-zeitpunkt"):
        if vorgang.gerat_id not in ausgaben:
            ausgaben[vorgang.gerat_id] = vorgang

    def _eintrag(gerat):
        vorgang_ausgabe = ausgaben.get(gerat.id)
        protokoll = (
            # Auch ein Gerät, das nicht das erste im Protokoll ist (F-20, Sammelausgabe).
            gerat.alle_protokolle().filter(person=person, art=Protokoll.ART_AUSGABE)
            .first()
        )
        return {
            "gerat": gerat,
            "ausgabe_datum": timezone.localdate(vorgang_ausgabe.zeitpunkt) if vorgang_ausgabe else None,
            "protokoll": protokoll,
            "leihe": Leihe.objects.filter(
                gerat=gerat, person=person, status=Leihe.STATUS_AUSGEGEBEN
            ).first(),
        }

    gerate_eintraege = [_eintrag(gerat) for gerat in geräte]

    protokolle = list(
        Protokoll.objects.filter(person=person)
        .order_by("-datum")
    )

    leihen = [
        leihe
        for leihe in Leihe.objects.filter(person=person)
        .select_related("gerat", "kat")
        .order_by("-zeitpunkt")
        # Ein Direktverleih ist erst mit der Signatur eine Leihe der Person (F-30).
        if not leihe.ist_direktentwurf
    ]
    vorschlag_basis = jetzt_wie_im_entwicklungsmodus().date()
    for leihe in leihen:
        # Vorbelegung wie im Prototyp: eine Woche über das spätere von Frist und heute.
        leihe.verlaengerung_vorschlag = max(
            leihe.rueckgabe_bis or vorschlag_basis, vorschlag_basis
        ) + timedelta(days=7)

    return render(
        request,
        "geraete/meine_geraete.html",
        {
            "geraete": gerate_eintraege,
            "protokolle": protokolle,
            "leihen": leihen,
            # Kapitel 2: Der Leser fragt nicht an und ändert nichts.
            "darf_anfragen": not request.user.ist_leser,
        },
    )


@login_required
def meine_geraete_leihe_neu(request):
    """/meine-geraete/leihe/neu/ – Leihgerät anfragen (F-31, Kapitel 3).

    GET: Formular mit Leihkategorien und der Anzahl freier Geräte der
    Kategorie im Zeitraum. POST: Anfrage speichern, danach mit data-stand
    „angefragt\" in /verleih/ (O-12). Der Leser sieht die Seite
    (TESTSCHNITTSTELLE 3), fragt aber nicht an (Kapitel 2).
    """
    from .forms import LeiheAnfrageForm
    from .services import GeratFehler, leihe_anfragen

    person = _eigene_person(request)
    if person is None:
        raise PermissionDenied
    if request.method == "POST" and request.user.ist_leser:
        raise PermissionDenied

    heute = jetzt_wie_im_entwicklungsmodus().date()
    form = LeiheAnfrageForm(
        request.POST or None,
        leihpool_geraete=_leihpool_anfragbar(),
        initial={
            "beginn": heute + timedelta(days=2),
            "ende": heute + timedelta(days=4),
        },
    )

    fehler = ""
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
            meldung_success(request, "Anfrage gesendet. Die IT entscheidet und meldet sich per E-Mail.")
            return redirect("/meine-geraete/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    # Anzeige wie auf dem Bildschirm: gewählte Werte, sonst die Vorbelegung.
    kategorien = form.fields["kat"].queryset
    kat = str(form["kat"].value() or "")
    kategorie = kategorien.filter(pk=kat).first() if kat.isdigit() else None
    kategorie = kategorie or kategorien.first()
    von = _datum_oder_nichts(form["beginn"].value())
    bis = _datum_oder_nichts(form["ende"].value())
    if von and bis and bis < von:
        von = bis = None

    return render(
        request,
        "geraete/leihe_neu.html",
        {
            "form": form,
            "fehler": fehler,
            "auswahl": _anfrage_auswahl(kategorie, von, bis),
            "gewaehlt": str(form["gerat"].value() or ""),
            "darf_anfragen": not request.user.ist_leser,
        },
    )


@login_required
def meine_geraete_leihe_frei(request):
    """F-31: Freie Geräte der Kategorie im Zeitraum, für das Formular der Anfrage.

    Liefert nur Anzahl, Inventarnummer und Modell, keine Personen (F-112).
    """
    from django.http import JsonResponse

    if _eigene_person(request) is None:
        raise PermissionDenied
    kat = request.GET.get("kat", "")
    kategorie = Kategorie.objects.filter(pk=kat).first() if kat.isdigit() else None
    von = _datum_oder_nichts(request.GET.get("beginn"))
    bis = _datum_oder_nichts(request.GET.get("ende"))
    if von and bis and bis < von:
        von = bis = None
    return JsonResponse(_anfrage_auswahl(kategorie, von, bis))


@login_required
def meine_geraete_leihe_zurueckziehen(request, leih_id):
    """Leihe zurückziehen (F-37, Kapitel 3).

    POST: Leihe auf „zurueckgezogen\" setzen; die Reservierung endet
    damit. GET: Seite mit dem Knopf. Wer anfragen darf, darf die eigene
    Anfrage zurückziehen (Kapitel 2): Mitarbeiter und Admin, nicht der Leser.
    """
    from .forms import LeiheZurueckziehenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_zurueckziehen

    if request.user.ist_leser:
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    if request.user.person_id is None or leihe.person_id != request.user.person_id:
        raise PermissionDenied
    form = LeiheZurueckziehenForm(request.POST if request.method == "POST" else None)

    meldung = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_zurueckziehen(leihe, ausgefuehrt_von=request.user)
            meldung_success(request, f"Anfrage {leihe.nr} zurückgezogen.")
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
@require_POST
def meine_geraete_leihe_verlaengern(request, leih_id):
    """F-35, F-111: Verlängerung der eigenen Leihe anfragen, die IT gewährt.

    Kapitel 2: Mitarbeiter und Admin dürfen anfragen, der Leser nicht.
    """
    from .forms import LeiheVerlaengerungAnfragenForm
    from .models import Leihe
    from .services import GeratFehler, leihe_verlaengerung_anfragen

    if request.user.ist_leser:
        raise PermissionDenied

    leihe = get_object_or_404(Leihe, id=leih_id)
    if request.user.person_id is None or leihe.person_id != request.user.person_id:
        raise PermissionDenied

    form = LeiheVerlaengerungAnfragenForm(request.POST)
    if not form.is_valid():
        meldung_error(request, "Bitte das neue Rückgabedatum angeben.")
        return redirect("/meine-geraete/")
    try:
        leihe_verlaengerung_anfragen(leihe, form.cleaned_data["rueckgabe_bis_neu"])
    except GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        bis = leihe.verlaengerung_bis.strftime("%d.%m.%Y")
        meldung_success(request, f"Verlängerung bis {bis} bei der IT angefragt.")
    return redirect("/meine-geraete/")


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
            meldung_success(
                request,
                f"Genehmigt und {leihe.gerat.inventarnummer} reserviert. "
                f"{leihe.person.voller_name()} wird per E-Mail informiert.",
            )
            return redirect("/verleih/")
        except GeratFehler as fehler_vorgang:
            fehler = str(fehler_vorgang)

    # F-32, F-34: Ausgemustertes, Reparatur und fest Ausgegebenes stehen nicht in
    # der Auswahl. Belegte Geräte stehen gekennzeichnet dahinter, die Prüfung
    # beim Genehmigen lehnt sie mit Meldung ab.
    stand = services.leihe_verfuegbarkeit(leihe.kat, leihe.beginn, leihe.ende, ohne=leihe)
    gewaehlt = str(form["gerat"].value() or leihe.gerat_id or "")
    auswahl = [
        {"id": g.pk, "text": services.leihgeraet_bezeichnung(g)}
        for g in stand["frei"]
    ] + [
        {"id": g.pk, "text": f"{services.leihgeraet_bezeichnung(g)} (im Zeitraum belegt)"}
        for g in stand["belegt"]
    ]

    return render(
        request,
        "geraete/leihe_genehmigen.html",
        {
            "form": form,
            "leihe": leihe,
            "fehler": fehler,
            "auswahl": auswahl,
            "gewaehlt": gewaehlt,
            "frei_anzahl": len(stand["frei"]),
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
    form = LeiheAusgebenForm(
        request.POST if request.method == "POST" else None,
        initial={"unterschrift": "tool"},
    )
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_ausgeben(
                leihe,
                ausgefuehrt_von=request.user,
                unterschrift=form.cleaned_data.get("unterschrift") or "papier",
            )
            offen = leihe.offenes_protokoll
            if offen is not None:
                meldung_success(
                    request,
                    f"Protokoll {offen.nr} angelegt. Das Gerät wird mit Ihrer Signatur verliehen.",
                )
            else:
                meldung_success(request, "Gerät wurde verliehen.")
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
    # Vorbelegung: was der Mitarbeiter wünscht, sonst eine Woche wie im Prototyp.
    heute = jetzt_wie_im_entwicklungsmodus().date()
    vorschlag = leihe.verlaengerung_bis or (
        max(leihe.rueckgabe_bis or heute, heute) + timedelta(days=7)
    )
    form = LeiheVerlaengernForm(request.POST or None, vorschlag=vorschlag)
    fehler = ""
    if request.method == "POST" and form.is_valid():
        try:
            leihe_verlaengern(
                leihe,
                rueckgabe_bis_neu=form.cleaned_data["rueckgabe_bis_neu"],
                ausgefuehrt_von=request.user,
            )
            bis = leihe.rueckgabe_bis.strftime("%d.%m.%Y")
            meldung_success(request, f"Leihe bis {bis} verlängert.")
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
                begruendung=form.cleaned_data["begruendung"],
                ausgefuehrt_von=request.user,
            )
            meldung_success(
                request,
                f"Abgelehnt. {leihe.person.voller_name()} wird per E-Mail informiert.",
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
    """Lesen (TESTSCHNITTSTELLE 3): Admin und Leser immer, Mitarbeiter nur das eigene."""
    if request.user.ist_admin or request.user.ist_leser:
        return
    person = protokoll.person
    if request.user.person is None:
        raise PermissionDenied
    if person is None or request.user.person_id != person.id:
        raise PermissionDenied


def _protokoll_schreibrecht(request) -> None:
    """Checkliste, Foto, Scan, Signatur, Abbrechen, Korrektur, Code: nur Admin (Kapitel 2).

    Die Person gegenzeichnet über den Link unter /signieren/, nicht hier.
    """
    if not request.user.ist_admin:
        raise PermissionDenied("Zugriff verweigert: Vorgänge am Protokoll macht die IT.")


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
        for schluessel, text in protokoll.punkte_zum_anzeigen("zugaenge")
    ]
    offboarding = []
    for schluessel, text in protokoll.punkte_zum_anzeigen("offboarding"):
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
    from . import pdf as pdf_modul
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
            "positionen": pdf_modul._positionen(protokoll),
            "titel": pdf_modul._titel(protokoll),
            # F-135: Nach der Signatur ist der Inhalt gesperrt; bedienen darf nur die IT.
            "editierbar": request.user.ist_admin and not protokoll.ist_gesperrt
            and protokoll.stand in (Protokoll.STAND_BEARBEITER_OFFEN, Protokoll.STAND_SCAN_OFFEN),
            "pdf_moeglich": bool(protokoll.scan_datei) or not pdf_modul._offene_punkte(protokoll),
            "ersetzt_durch": protokoll.korrekturen.order_by("-id").first(),
            "link_gegenzeichnung": services._link_gegenzeichnung(protokoll.gegenzeichnung_token)
            if protokoll.gegenzeichnung_token else "",
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

    # F-22, F-110: Beim Papierweg ist der Scan das unterschriebene Dokument.
    if protokoll.scan_datei and not protokoll.pdf_baubar:
        with protokoll.scan_datei.open("rb") as scan:
            roh = scan.read()
        if roh.startswith(b"%PDF"):
            art, endung = "application/pdf", "pdf"
        elif roh.startswith(b"\xff\xd8"):
            art, endung = "image/jpeg", "jpg"
        elif roh.startswith(b"\x89PNG"):
            art, endung = "image/png", "png"
        else:
            art, endung = "application/octet-stream", "heic"
        antwort = HttpResponse(roh, content_type=art)
        antwort["Content-Disposition"] = (
            f"attachment; filename={protokoll.nr}-scan.{endung}"
        )
        return antwort

    from . import pdf as protokoll_pdf_modul
    # F-22: Beim Papierweg ist der Scan das Protokoll.
    if protokoll.scan_datei:
        from .protokoll import _typ_am_inhalt
        with protokoll.scan_datei.open("rb") as handle:
            roh = handle.read()
        antwort = HttpResponse(roh, content_type=_typ_am_inhalt(roh) or "application/octet-stream")
        antwort["Content-Disposition"] = f'attachment; filename="{protokoll.scan_datei.name.rsplit("/", 1)[-1]}"'
        return antwort
    try:
        # F-139: Das versiegelte PDF wird nicht neu gebaut, sonst wäre es ein anderes.
        inhalt = bytes(protokoll.pdf_siegel) if protokoll.pdf_siegel else protokoll_pdf_modul.pdf_fertig_bauen(protokoll, versiegeln=False)
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
    _protokoll_schreibrecht(request)

    from . import protokoll as protokoll_services

    werte = {}
    bemerkungen = {}
    # TESTSCHNITTSTELLE Kapitel 4: value = ausgegeben oder nicht-zutreffend.
    for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE:
        roh = request.POST.get(f"checkliste.{schluessel}")
        if roh in ("1", "ausgegeben"):
            werte[schluessel] = 1
        elif roh in ("0", "nicht-zutreffend"):
            werte[schluessel] = 0
        bemerkungen[schluessel] = request.POST.get(f"checkliste.{schluessel}.bemerkung", "")
    try:
        protokoll_services.checkliste_beantworten(protokoll, werte, request.user, bemerkungen=bemerkungen)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Checkliste gespeichert.")
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
    _protokoll_schreibrecht(request)

    from . import protokoll as protokoll_services

    werte = {}
    for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE:
        roh = (request.POST.get(f"offboarding.{schluessel}") or "").replace("-", "_")
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
        meldung_success(request, "Prüfpunkte gespeichert.")
    return redirect(f"/protokolle/{protokoll_nr}/")


@login_required
@require_POST
def protokoll_foto_hochladen(request, protokoll_nr):
    """POST /protokolle/<Nummer>/foto/ – Foto (F-134).

    JPG, PNG oder HEIC bis 10 MB; verkleinert als Anlage hinter dem
    Protokoll.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_schreibrecht(request)

    from . import protokoll as protokoll_services

    datei = request.FILES.get("foto")
    if datei is None:
        meldung_error(request, "Kein Foto übergeben.")
        return redirect(f"/protokolle/{protokoll_nr}/")
    try:
        protokoll_services.foto_hochladen(
            protokoll, datei, request.user, inventarnummer=request.POST.get("inventarnummer", ""),
        )
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Foto als Anlage gespeichert.")
    return redirect(f"/protokolle/{protokoll_nr}/")


@login_required
@require_POST
def protokoll_scan_hochladen(request, protokoll_nr):
    """POST /protokolle/<Nummer>/scan/ – Scan (F-22).

    Der hochgeladene Scan setzt das Protokoll auf „abgeschlossen".
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_schreibrecht(request)

    from . import protokoll as protokoll_services

    datei = request.FILES.get("scan")
    if datei is None:
        meldung_error(request, "Kein Scan übergeben.")
        return redirect(f"/protokolle/{protokoll_nr}/")
    try:
        protokoll_services.scan_hochladen(protokoll, datei, request.user)
    except services.GeratFehler as fehler:
        meldung_error(request, str(fehler))
    else:
        meldung_success(request, "Scan hochgeladen, Protokoll abgeschlossen.")
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
    _protokoll_schreibrecht(request)

    if protokoll.stand != Protokoll.STAND_BEARBEITER_OFFEN:
        meldung_error(request, "Nur Protokolle auf 'bearbeiter-offen' können abgebrochen werden.")
        return redirect(f"/protokolle/{protokoll_nr}/")
    # Eine Korrektur verwerfen hieße, das ersetzte Original ohne Nachfolger zu lassen.
    if protokoll.ist_korrektur:
        meldung_error(request, "Eine neue Fassung lässt sich nicht verwerfen, nur signieren.")
        return redirect(f"/protokolle/{protokoll_nr}/")
    ziel = f"/geraete/{protokoll.geraet.inventarnummer}/"

    # A-0128: Bei Verleih (F-30, F-33) gehört die Leihe dazu: Der Direktverleih
    # verschwindet, damit das Gerät wieder ausgebbar ist; eine genehmigte Anfrage
    # bleibt genehmigt (F-21: ein verworfener Entwurf ändert nichts).
    leihe = protokoll.leihe
    protokoll.delete()
    meldung_success(request, "Protokoll abgebrochen. Das Gerät bleibt unverändert.")
    if leihe is not None:
        services.leihe_entwurf_verworfen(leihe)
        return redirect("/verleih/")
    return redirect(ziel)


@require_POST
@login_required
def protokoll_signieren(request, protokoll_nr: str):
    """F-135: POST /protokolle/<Nummer>/signieren/

    Bearbeiter signiert das Protokoll mit erneuter Passwortabfrage.
    Danach: Inhalt gesperrt, Stand → gegenzeichnung-offen,
    Mail mit Link in die Mailablage.
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_schreibrecht(request)

    password = request.POST.get("passwort", "")
    if not password:
        meldung_error(request, "Passwort fehlt.")
        return redirect(f"/protokolle/{protokoll_nr}/")

    try:
        _, erfolg = services.protokoll_bearbeiter_signieren(
            protokoll, password, request, konto=request.user
        )
    except services.GeratFehler as fehler:
        meldung_error(request, f"Signatur fehlgeschlagen: {fehler}")
        return redirect(f"/protokolle/{protokoll_nr}/")

    if not erfolg:
        from . import pdf as pdf_modul
        offene = pdf_modul._offene_punkte(protokoll)
        if protokoll.stand != Protokoll.STAND_BEARBEITER_OFFEN:
            meldung_error(request, "Dieses Protokoll wartet nicht auf die Signatur des Bearbeiters.")
        elif offene:
            meldung_error(
                request,
                f"Die Checkliste ist noch nicht vollständig beantwortet "
                f"({len(offene)} Punkte offen); die Signatur wird abgelehnt."
            )
        else:
            meldung_error(request, "Passwort ungültig.")
    elif not protokoll.gegenzeichnung_empfaenger:
        meldung_success(request, "Protokoll signiert. Für diese Person ist keine E-Mail hinterlegt: bitte eine Adresse eintragen oder vor Ort am Tablet gegenzeichnen.")
    elif getattr(protokoll, "mail_ging_nicht", False):
        meldung_error(request, "Protokoll signiert, die Mail ließ sich aber nicht senden. Bitte den Link neu senden oder vor Ort am Tablet gegenzeichnen.")
    else:
        meldung_success(request, "Protokoll signiert. Mail mit Link gesendet.")
    return redirect(f"/protokolle/{protokoll_nr}/")


@require_POST
@login_required
def protokoll_code_senden(request, protokoll_nr: str):
    """F-136: POST /protokolle/<Nummer>/code-senden/

    Erzeugt einen 6-stelligen Einmalcode (10 Min., 5 Versuche) und
    schickt eine Mail mit der Zeile „Einmalcode: <code>".
    """
    protokoll = get_object_or_404(Protokoll, nr=protokoll_nr)
    _protokoll_schreibrecht(request)

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
    _protokoll_schreibrecht(request)

    _, erfolg, meldung = services.protokoll_link_neu_senden(protokoll, request.POST.get("empfaenger", ""))
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
    _protokoll_schreibrecht(request)

    neue, erfolg = services.protokoll_korrigieren(protokoll, request.user)
    if not erfolg:
        meldung_error(request, "Korrektur nicht möglich: Protokoll nicht signiert.")
        return redirect(f"/protokolle/{protokoll_nr}/")

    meldung_success(
        request,
        f"Neue Fassung {neue.nr} erzeugt."
    )
    return redirect(f"/protokolle/{neue.nr}/")


def _signieren_hinweis(request, titel: str, text: str, status: int = 200):
    return render(request, "geraete/signieren_hinweis.html", {"titel": titel, "text": text}, status=status)


def _signieren_protokoll(request, token: str):
    """Liefert (Protokoll, None) oder (None, Antwort), wenn der Link nicht gilt (F-136)."""
    protokoll = None
    if token:
        protokoll = Protokoll.objects.filter(gegenzeichnung_token=token).select_related("person", "geraet").first()
    if protokoll is None:
        return None, _signieren_hinweis(request, "Unbekannter Link", "Dieser Link ist ungültig oder durch einen neueren ersetzt.", 404)
    if protokoll.stand == Protokoll.STAND_ABGESCHLOSSEN:
        return None, _signieren_hinweis(request, "Gegenzeichnung abgeschlossen", f"Protokoll {protokoll.nr} ist bereits signiert. Das versiegelte PDF haben Sie per Mail erhalten.")
    if protokoll.gegenzeichnung_abgelaufen:
        return None, _signieren_hinweis(request, "Link abgelaufen", "Dieser Link ist nicht mehr gültig. Bitte wenden Sie sich an die IT, sie sendet Ihnen einen neuen.", 410)
    return protokoll, None


def signieren_link(request, token: str):
    """F-136: GET /signieren/<token>/ – ohne Anmeldung; POST prüft den Einmalcode."""
    protokoll, antwort = _signieren_protokoll(request, token)
    if protokoll is None:
        return antwort

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        if not code:
            return render(
                request, "geraete/signieren.html",
                {"protokoll": protokoll, "token": token, "fehler": "Code fehlt."}, status=400,
            )
        protokoll_2, erfolg, meldung = services.protokoll_gegenzeichnen(token, code, request)
        if protokoll_2 is None:
            return _signieren_hinweis(request, "Unbekannter Link", "Dieser Link ist ungültig.", 404)
        if erfolg:
            return _signieren_hinweis(request, "Gegenzeichnung abgeschlossen", f"Vielen Dank. Protokoll {protokoll_2.nr} ist signiert, das versiegelte PDF kommt per Mail.")
        return render(
            request, "geraete/signieren.html",
            {"protokoll": protokoll_2, "token": token, "fehler": meldung or "Code ungültig."}, status=400,
        )

    return render(request, "geraete/signieren.html", {"protokoll": protokoll, "token": token})


@require_POST
def signieren_code_senden(request, token: str):
    """F-136: POST /signieren/<token>/code-senden/ – ohne Anmeldung.

    Schickt einen neuen Einmalcode per Mail an die Person.
    """
    protokoll, antwort = _signieren_protokoll(request, token)
    if protokoll is None:
        return antwort

    erfolg, meldung = services.protokoll_code_senden(protokoll)
    if erfolg:
        return render(
            request,
            "geraete/signieren.html",
            {
                "protokoll": protokoll,
                "token": token,
                "meldung": "Code per Mail gesendet.",
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
    """F-136: GET /signieren/<token>/pdf/ – das Protokoll zum Ansehen, solange der Link gilt."""
    from . import pdf as pdf_modul
    protokoll, antwort = _signieren_protokoll(request, token)
    if protokoll is None:
        return antwort
    pdf_bytes = pdf_modul.pdf_fertig_bauen(protokoll, versiegeln=False)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Protokoll-{protokoll.nr}.pdf"'
    return response
