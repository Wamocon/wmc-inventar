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
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Ausstattungsprofil, Ort, Person, Kategorie, Plan, Einstellungen
from .forms import (
    KategorieForm, PersonForm, OrtForm, ProfilForm, ProfilpositionForm,
    EinstellungenForm,
)


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
                "Eintritt": p.eintritt or "",
                "Austritt": p.austritt or "",
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


# ---------------------------------------------------------------------------
# Raumplan pflegen (F-67, A-0107 Teil 2)
# ---------------------------------------------------------------------------

def _bild_aus_pdf(datei) -> bytes:
    """Erste Seite eines PDFs als PNG (F-67, pypdfium2)."""
    import io
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(datei.read())
    try:
        if len(doc) == 0:
            raise ValueError("Das PDF hat keine Seiten.")
        seite = doc[0]
        bild = seite.render(scale=2).to_pil()
        puffer = io.BytesIO()
        bild.save(puffer, format="PNG")
        return puffer.getvalue()
    finally:
        doc.close()


def _grundriss_speichern(plan: Plan, datei) -> None:
    """Datei für den Grundriss annehmen: PNG, JPG, SVG oder PDF (F-67).

    Die erste Seite eines PDFs wird mit pypdfium2 zu einem Bild.
    Die Datei landet in der DATEIABLAGE unter ``grundrisse/``.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    name = (datei.name or "").lower()
    if name.endswith(".png"):
        daten, dateiname = datei.read(), "grundriss.png"
    elif name.endswith((".jpg", ".jpeg")):
        daten, dateiname = datei.read(), "grundriss.jpg"
    elif name.endswith(".svg"):
        daten, dateiname = datei.read(), "grundriss.svg"
    elif name.endswith(".pdf"):
        daten, dateiname = _bild_aus_pdf(datei), "grundriss.png"
    else:
        raise ValueError("Der Grundriss muss PNG, JPG, SVG oder ein PDF sein (F-67).")
    # Alte Datei löschen, falls vorhanden
    if plan.grundriss and plan.grundriss.name:
        try:
            default_storage.delete(plan.grundriss.name)
        except OSError:
            pass
    # Neue Datei speichern: Zuerst die Standarddatei löschen, damit
    # default_storage.save() den Namen "grundriss.png" (nicht "grundriss_XXXX.png")
    # verwenden kann.
    standard_pfad = f"grundrisse/{dateiname}"
    if default_storage.exists(standard_pfad):
        default_storage.delete(standard_pfad)
    pfad = default_storage.save(standard_pfad, ContentFile(daten))
    plan.grundriss.name = pfad
    plan.save(update_fields=["grundriss"])


def plan_bearbeiten(request, plan_id: int):
    """Raumplan pflegen: Grundriss hochladen, Positionen setzen (F-67).

    Adresse /arbeitsplaetze/plan/<id>/bearbeiten/ (TESTSCHNITTSTELLE 3).
    Für Admins 200, für Leser und Mitarbeiter 403 (TESTSCHNITTSTELLE 2).
    """
    user = request.user
    if not user.is_authenticated or not user.ist_admin:
        return _keine_berechtigung(request)
    try:
        plan = Plan.objects.get(pk=plan_id)
    except Plan.DoesNotExist:
        from django.http import Http404
        raise Http404

    meldung = None
    datei = request.FILES.get("grundriss")
    pfad = request.path

    if request.method == "POST":
        # Position speichern (x, y in Prozent vom Mittelpunkt, TESTSCHNITTSTELLE 2)
        von = request.POST.get("ort", "")
        if von:
            try:
                ort = Ort.objects.get(pk=int(von), plan_id=plan.id)
            except Ort.DoesNotExist:
                ort = None
            if ort is not None:
                try:
                    ort.position_x = round(float(request.POST.get("x", "0")), 1)
                    ort.position_y = round(float(request.POST.get("y", "0")), 1)
                except (ValueError, TypeError):
                    ort.position_x = None
                    ort.position_y = None
                ort.aktualisiert_am = timezone.now()
                ort.save()
                meldung = f"Position von {ort.kennung} gespeichert."
                return redirect(pfad)

        # Grundriss hochladen
        if datei is not None and datei.size:
            try:
                _grundriss_speichern(plan, datei)
                meldung = "Grundriss gespeichert."
            except Exception as fehler:
                meldung = f"Fehler beim Speichern des Grundrisses: {fehler}"
            return redirect(pfad)

    grundriss_name = ""
    grundriss_typ = ""
    if plan.grundriss and plan.grundriss.name:
        grundriss_name = plan.grundriss.name
        if "." in plan.grundriss.name:
            grundriss_typ = plan.grundriss.name.rsplit(".", 1)[-1].lower()
    plaetze = (
        Ort.objects.filter(
            plan_id=plan.id,
            typ__in=(Ort.TYP_ARBEITSPLATZ, Ort.TYP_RAUM),
        ).order_by("kennung")
    )
    return render(
        request,
        "geraete/plan_bearbeiten.html",
        {
            "plan": plan,
            "plaetze": plaetze,
            "meldung": meldung,
            "grundriss_name": grundriss_name,
            "grundriss_typ": grundriss_typ,
        },
    )


# ---------------------------------------------------------------------------
# Einstellungen (F-122, F-90, F-96, F-130, N-02) — M7 Teil 1 (A-0905)
# ---------------------------------------------------------------------------

def _logo_aufnehmen( Einstellungen_obj, datei):
    """Logo als PNG oder SVG speichern (N-02).

    Alte Datei wird gelöscht. SVG bleibt eine Datei, die per
    ``<img src=...>`` eingebunden wird — nie als Inline-SVG.
    """
    from django.core.files.storage import default_storage

    if not datei or not datei.size:
        return
    name = (datei.name or "").lower()
    if name.endswith(".png"):
        dateiname = "logo.png"
    elif name.endswith(".svg"):
        dateiname = "logo.svg"
    else:
        raise ValueError("Das Logo muss eine PNG- oder SVG-Datei sein (N-02).")

    # Alte Datei löschen
    if Einstellungen_obj.logo and Einstellungen_obj.logo.name:
        try:
            default_storage.delete(Einstellungen_obj.logo.name)
        except OSError:
            pass

    daten = datei.read()
    pfad = default_storage.save(f"logo/{dateiname}", ContentFile(daten))
    Einstellungen_obj.logo.name = pfad
    Einstellungen_obj.save(update_fields=["logo"])


def _testmail_senden(einstellungen: Einstellungen, empfaenger: str) -> bool:
    """F-90: Testmail senden.

    Erzeugt eine Mail in der Mailablage (``MAILDIR``) oder nutzt
    den konfigurierten SMTP-Zugang. Rückgabe: True bei Erfolg.
    """
    import os
    from email.message import EmailMessage
    from pathlib import Path

    absender = einstellungen.smtp_absender or einstellungen.email_it or "it@beispiel.test"
    firma = einstellungen.firmenname or "Wamocon GmbH"
    zeile = einstellungen.absenderzeile or f"{firma} · IT"

    msg = EmailMessage()
    msg["From"] = f"{zeile} <{absender}>"
    msg["To"] = empfaenger
    msg["Subject"] = f"Testmail aus WMC Inventar — {firma}"
    msg.set_content(
        "Dies ist eine Testmail aus den Einstellungen von WMC Inventar.\n"
        "Die Verbindung zum Mailserver wurde geprüft (F-90).\n"
        f"\nAbsenderzeile: {zeile}\nFirma: {firma}\nTelefon: {einstellungen.telefon or '—'}\nE-Mail IT: {einstellungen.email_it or '—'}\n"
    )

    maildir = os.environ.get("MAILDIR", "")
    if maildir:
        # Ablage: MAILDIR/<empfaenger>/<timestamp>.eml
        ablage = Path(maildir) / empfaenger.replace("@", "_at_").replace(".", "_")
        ablage.mkdir(parents=True, exist_ok=True)
        stempel = timezone.now().strftime("%Y%m%d_%H%M%S")
        pfad = ablage / f"{stempel}.eml"
        pfad.write_bytes(msg.as_bytes())
        return True

    # Fallback: Django MailBackend
    from django.core.mail import EmailMessage as DJEmail
    mail = DJEmail(
        subject=msg["Subject"],
        body=msg.get_content(),
        from_email=absender,
        to=[empfaenger],
    )
    mail.send()
    return True


def einstellungen_sehen(request):
    """/einstellungen/ — Einstellungen anzeigen und pflegen.

    Nur Admin (TESTSCHNITTSTELLE.md Kapitel 3).
    Für Admin 200, für Leser und Mitarbeiter 403.
    """
    user = request.user
    if not user.is_authenticated or not user.ist_admin:
        return _keine_berechtigung(request)

    einstellungen = Einstellungen.aktuelles()

    if request.method == "POST":
        form = EinstellungenForm(request.POST, request.FILES, instance=einstellungen)
        if form.is_valid():
            data = form.cleaned_data

            # Passwort: leer = unverändert
            if not data.get("smtp_passwort"):
                # Altes Passwort beibehalten
                data["smtp_passwort"] = einstellungen.smtp_passwort
            # Logo-Datei aus den FILES extrahieren
            logo_datei = request.FILES.get("logo")
            instanz = form.save()
            if logo_datei is not None:
                try:
                    _logo_aufnehmen(instanz, logo_datei)
                except ValueError as fehler:
                    messages.error(request, str(fehler))
                    form.add_error("logo", str(fehler))
                    return render(request, "stammdaten/einstellungen.html", {
                        "form": form,
                        "einstellungen": Einstellungen.aktuelles(),
                        "testmail_ok": False,
                        "testmail_aktuell": False,
                    })
            messages.success(request, "Einstellungen gespeichert.")
            return redirect(reverse("stammdaten:einstellungen"))
        # Fehler: Formular neu rendern
        return render(request, "stammdaten/einstellungen.html", {
            "form": form,
            "einstellungen": Einstellungen.aktuelles(),
            "testmail_ok": False,
            "testmail_aktuell": False,
        })
    else:
        form = EinstellungenForm(instance=einstellungen)

    return render(request, "stammdaten/einstellungen.html", {
        "form": form,
        "einstellungen": einstellungen,
        "testmail_ok": False,
        "testmail_aktuell": False,
    })


@require_POST
def einstellungen_testmail(request):
    """F-90: „Testmail senden" — erzeugt eine Mail in der Mailablage.

    POST /einstellungen/testmail/ mit Feld "empfaenger".
    Nur Admin. Antwort: leitet an /einstellungen/ zurück mit meldung oder fehler.
    """
    user = request.user
    if not user.is_authenticated or not user.ist_admin:
        return _keine_berechtigung(request)

    empfaenger = request.POST.get("empfaenger", "").strip()
    if not empfaenger or "@" not in empfaenger:
        return render(request, "stammdaten/einstellungen.html", {
            "einstellungen": Einstellungen.aktuelles(),
            "testmail_fehler": "Bitte eine gültige E-Mail-Adresse angeben.",
        })

    einstellungen = Einstellungen.aktuelles()
    try:
        _testmail_senden(einstellungen, empfaenger)
        return render(request, "stammdaten/einstellungen.html", {
            "einstellungen": einstellungen,
            "testmail_meldung": f"Testmail an {empfaenger} gesendet.",
        })
    except Exception as fehler:
        return render(request, "stammdaten/einstellungen.html", {
            "einstellungen": einstellungen,
            "testmail_fehler": f"Testmail fehlgeschlagen: {fehler}",
        })


@require_POST
def einstellungen_speichern(request):
    """Einstellungen speichern (POST /einstellungen/).

    Wird von der Formularseite aufgerufen; leitet an /einstellungen/ um.
    """
    user = request.user
    if not user.is_authenticated or not user.ist_admin:
        return _keine_berechtigung(request)

    einstellung = Einstellungen.aktuelles()
    form = EinstellungenForm(request.POST, request.FILES, instance=einstellung)
    if not form.is_valid():
        return render(request, "stammdaten/einstellungen.html", {
            "form": form,
            "einstellungen": einstellung,
            "testmail_ok": False,
            "testmail_aktuell": False,
        })

    data = form.cleaned_data
    # Passwort: leer = unverändert
    if not data.get("smtp_passwort"):
        data["smtp_passwort"] = einstellung.smtp_passwort

    instanz = form.save()

    # Logo
    logo_datei = request.FILES.get("logo")
    if logo_datei is not None:
        try:
            _logo_aufnehmen(instanz, logo_datei)
        except ValueError as fehler:
            messages.error(request, str(fehler))
            return redirect(reverse("stammdaten:einstellungen"))

    messages.success(request, "Einstellungen gespeichert.")
    return redirect(reverse("stammdaten:einstellungen"))
