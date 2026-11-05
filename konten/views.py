"""Views für Anmeldung, Abmeldung, Passwort (F-01 bis F-05).

F-01: E-Mail + Passwort, neutrale Meldung bei falschen Angaben, Sperre nach 5 Fehlversuchen.
F-02: Admin legt Konten an, vergibt Rollen, deaktiviert Konten.
F-03: Passwort vergessen (Link 1 h, nur einmal).
F-04: Passwort ändern (mind. 12 Zeichen, altes Passwort).
F-05: Sitzungsende nach 8 h ohne Aktivität.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int, url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .mail import link_ins_tool, mail_absender
from .models import Konto
from .zeit import jetzt_wie_im_entwicklungsmodus
from .forms import (
    AnmeldeForm,
    KontoForm,
    PasswortAenderForm,
    PasswortSetForm,
    PasswortVergessenForm,
)



class _LinkToken(PasswordResetTokenGenerator):
    """Link zum Passwort setzen: nur einmal nutzbar, mit eigener Gültigkeit.

    Nur einmal, weil der Passwort-Hash in den Token eingeht. Die Zeit ist die
    der Anwendung (TESTSCHNITTSTELLE 1.2). Djangos Standard kennt nur eine
    Gültigkeit für alle Links und nur die echte Uhr.
    """

    gueltig_sekunden = 0

    def _now(self):
        return jetzt_wie_im_entwicklungsmodus().replace(tzinfo=None)

    def check_token(self, user, token):
        try:
            stempel = base36_to_int((token or "").split("-")[0])
        except ValueError:
            return False
        for geheim in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, stempel, geheim), token):
                return self._num_seconds(self._now()) - stempel <= self.gueltig_sekunden
        return False


class _TokenVergessen(_LinkToken):
    """F-03: Passwort vergessen, Link 1 Stunde gültig."""

    key_salt = "konten.views.TokenVergessen"
    gueltig_sekunden = 60 * 60


class _TokenEinladung(_LinkToken):
    """F-02: Einladung, Link 72 Stunden gültig."""

    key_salt = "konten.views.TokenEinladung"
    gueltig_sekunden = 72 * 60 * 60


_token_vergessen = _TokenVergessen()
_token_einladung = _TokenEinladung()


def _jetzt():
    return jetzt_wie_im_entwicklungsmodus()


# ---------------------------------------------------------------------------
# Anmeldung (F-01)
# ---------------------------------------------------------------------------

# F-01: Immer derselbe Satz, er verrät nicht, ob es das Konto gibt oder ob es gesperrt ist.
NEUTRAL = "E-Mail oder Passwort ist falsch. Nach mehreren Fehlversuchen ist die Anmeldung 15 Minuten gesperrt."


def anmelden(request):
    """Anmeldung mit E-Mail und Passwort (F-01).

    Falsche Angaben ergeben eine neutrale Meldung.
    Nach 5 Fehlversuchen ist das Konto 15 Minuten gesperrt.
    Deaktivierte Konten können sich nicht anmelden (F-02).
    """
    ziel = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(ziel, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        ziel = ""
    if request.user.is_authenticated:
        return redirect(ziel or landing_fuer(request.user))

    form = AnmeldeForm(request.POST or None)
    fehler = ""

    if request.method == "POST" and not form.is_valid():
        fehler = NEUTRAL
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        passwort = form.cleaned_data["passwort"]

        konto = None
        try:
            konto = Konto.objects.get(email__iexact=email)
        except Konto.DoesNotExist:
            konto = None

        if konto is None or not konto.aktiv or konto.ist_gesperrt(jetzt=_jetzt()):
            # Neutrale Meldung (F-01), auch bei Sperre: Sie verrät nicht, ob es das Konto gibt.
            fehler = NEUTRAL
        else:
            benutzer = authenticate(request, email=konto.email, password=passwort)
            if benutzer is None:
                konto.registriere_fehlversuch(jetzt=_jetzt())
                fehler = NEUTRAL
            else:
                # F-05: Sitzung wird bei jeder Aktivität aktualisiert
                benutzer.letzter_login = _jetzt()
                benutzer.save(update_fields=["letzter_login"])
                benutzer.setze_fehlversuche_zurueck()
                login(request, benutzer)
                return redirect(ziel or landing_fuer(benutzer))

    return render(request, "konten/anmelden.html", {"form": form, "fehler": fehler, "next": ziel})


def landing_fuer(user) -> str:
    """Ziel nach der Anmeldung (TESTSCHNITTSTELLE 3).

    Mitarbeiter werden nach /meine-geraete/ weitergeleitet.
    """
    if user.ist_mitarbeiter:
        return "/meine-geraete/"
    return "/"


def abmelden(request):
    """Abmelden (POST, TESTSCHNITTSTELLE 3)."""
    if request.method != "POST":
        return redirect(reverse("konten:anmelden"))
    logout(request)
    return redirect(reverse("konten:anmelden"))


# ---------------------------------------------------------------------------
# Passwort vergessen (F-03)
# ---------------------------------------------------------------------------

def passwort_vergessen(request):
    """Passwort vergessen (F-03): Link per E-Mail, 1 h gültig, nur einmal nutzbar."""
    form = PasswortVergessenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        try:
            konto = Konto.objects.get(email__iexact=email)
        except Konto.DoesNotExist:
            konto = None

        if konto is not None and konto.aktiv:
            token = _token_vergessen.make_token(konto)
            link = link_ins_tool(f"/passwort-setzen/{token}/")
            body = (
                "Sie haben bei WMC Inventar ein neues Passwort angefordert.\n"
                f"Öffnen Sie den Link, um ein neues Passwort zu setzen: {link}\n"
                "Der Link ist eine Stunde gültig und kann nur einmal verwendet werden.\n"
                "Wenn Sie das Passwort nicht angefordert haben, ignorieren Sie diese Mail.\n"
            )
            msg = EmailMessage(
                subject="WMC Inventar: Passwort zurücksetzen",
                body=body,
                from_email=mail_absender(),
                to=[konto.email],
            )
            # Ein Versandfehler darf nicht verraten, dass es das Konto gibt.
            msg.send(fail_silently=True)

        # Neutrale Antwort, egal ob das Konto existiert (Schutz vor Kontenaufdeckung)
        messages.success(request, "Falls die E-Mail existiert, wurde ein Link gesendet.")
        return redirect(reverse("konten:anmelden"))
    return render(request, "konten/passwort_vergessen.html", {"form": form})


def passwort_setzen(request, token):
    """Passwort setzen über Link (F-02 Einladung, F-03 Zurücksetzen).

    Der Token ist zeitlich begrenzt und nur einmal nutzbar.
    """
    if request.user.is_authenticated:
        return redirect(landing_fuer(request.user))

    # Token prüfen: aktives Konto + Gültigkeit + einmalig
    konto = None
    for k in Konto.objects.filter(aktiv=True):
        if _token_vergessen.check_token(k, token) or _token_einladung.check_token(k, token):
            konto = k
            break

    if konto is None:
        return HttpResponse(
            "Der Link ist ungültig oder abgelaufen. Bitte fordern Sie einen neuen an.",
            status=400,
        )

    form = PasswortSetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        passwort = form.cleaned_data["passwort"]
        konto.set_password(passwort)
        konto.save(update_fields=["password"])
        # Token ungültig machen (einmalig, F-03)
        konto.fehlversuche = 0
        konto.gesperrt_bis = None
        konto.save(update_fields=["fehlversuche", "gesperrt_bis"])
        messages.success(request, "Das Passwort wurde gesetzt. Bitte melden Sie sich an.")
        return redirect(reverse("konten:anmelden"))

    return render(request, "konten/passwort_setzen.html", {"form": form})


# ---------------------------------------------------------------------------
# Passwort ändern (F-04)
# ---------------------------------------------------------------------------

def passwort_aendern(request):
    """Passwort ändern (F-04): mindestens 12 Zeichen, altes Passwort."""

    form = PasswortAenderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        altes = form.cleaned_data["altes_passwort"]
        neues = form.cleaned_data["neues_passwort"]
        if not request.user.check_password(altes):
            form.add_error("altes_passwort", "Das alte Passwort ist nicht richtig.")
        else:
            request.user.set_password(neues)
            request.user.save(update_fields=["password"])
            # F-04: Die Sitzung bleibt bestehen, sonst landet man wieder auf der Anmeldung.
            update_session_auth_hash(request, request.user)
            messages.success(request, "Das Passwort wurde geändert.")
            return redirect(reverse("konten:passwort-aendern"))
    return render(request, "konten/passwort_aendern.html", {"form": form})


# ---------------------------------------------------------------------------
# Konten verwalten (F-02) – Admin
# ---------------------------------------------------------------------------

def _nur_admin(request):
    """Prüft serverseitig, dass die Anfrage von einem Admin kommt (Kapitel 2)."""
    if not request.user.is_authenticated or not request.user.ist_admin:
        return None
    return request.user


def konten_liste(request):
    """Liste der Konten (F-02)."""
    if not _nur_admin(request):
        return _keine_berechtigung(request)
    return render(
        request,
        "konten/konten_liste.html",
        {"konten": Konto.objects.all().order_by("email")},
    )


def konto_anlegen(request):
    """Neues Konto anlegen (F-02).

    Jedes neue Konto erhält die Einladungsmail mit Link (72 h), auch wenn der
    Admin ein Passwort vergibt. Ein deaktiviertes Konto bekommt keine (F-96).
    """
    admin = _nur_admin(request)
    if admin is None:
        return _keine_berechtigung(request)
    form = KontoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        konto = form.save(commit=False)
        if form.cleaned_data["passwort"]:
            konto.set_password(form.cleaned_data["passwort"])
        else:
            konto.set_unusable_password()
        konto.save()
        if not konto.aktiv:
            messages.success(request, f"Konto {konto.email} angelegt, keine Einladung: Es ist nicht aktiv.")
            return redirect(reverse("konten:konten-liste"))
        link = link_ins_tool(f"/passwort-setzen/{_token_einladung.make_token(konto)}/")
        body = (
            f"Sie haben ein Konto bei WMC Inventar erhalten.\n"
            f"Rolle: {konto.get_rolle_display()}\n"
            f"Setzen Sie Ihr Passwort über diesen Link (72 Stunden gültig): {link}\n"
        )
        try:
            EmailMessage(
                subject="WMC Inventar: Einladung",
                body=body,
                from_email=mail_absender(),
                to=[konto.email],
            ).send()
        except OSError as fehler:
            # Das Konto bleibt bestehen; „Passwort vergessen“ liefert einen neuen Link.
            messages.error(request, f"Konto {konto.email} angelegt, Einladung nicht gesendet: {fehler}")
            return redirect(reverse("konten:konten-liste"))
        messages.success(request, f"Konto {konto.email} angelegt, Einladung gesendet.")
        return redirect(reverse("konten:konten-liste"))
    return render(request, "konten/konto_anlegen.html", {"form": form})


def konto_aendern(request, pk):
    """Konto ändern (Rolle, aktiv, F-02)."""
    admin = _nur_admin(request)
    if admin is None:
        return _keine_berechtigung(request)
    try:
        konto = Konto.objects.get(pk=pk)
    except Konto.DoesNotExist:
        raise Http404
    form = KontoForm(request.POST or None, instance=konto)
    if request.method == "POST" and form.is_valid():
        konto = form.save()
        if "passwort" in form.cleaned_data and form.cleaned_data["passwort"]:
            konto.set_password(form.cleaned_data["passwort"])
            konto.save(update_fields=["password"])
        messages.success(request, f"Konto {konto.email} geändert.")
        return redirect(reverse("konten:konten-liste"))
    return render(request, "konten/konto_aendern.html", {"form": form, "konto": konto})


# ---------------------------------------------------------------------------
# Übersicht (TESTSCHNITTSTELLE 3: "/" für Admin und Leser)
# ---------------------------------------------------------------------------

def uebersicht(request):
    """Übersicht: die Startseite nach der Anmeldung (TESTSCHNITTSTELLE 3).

    Für Admin und Leser antwortet "/" mit 200 und zeigt die
    Überschrift und die Hauptnavigation.
    Für Mitarbeiter wird auf "/meine-geraete/" weitergeleitet
    (F-110, M5; die Seite mit Kennzahlen kommt mit M7).
    """
    if not request.user.is_authenticated:
        return redirect(reverse("konten:anmelden"))
    if request.user.ist_mitarbeiter:
        return redirect("/meine-geraete/")
    return render(request, "startseite.html")


# ---------------------------------------------------------------------------
# Hilfe
# ---------------------------------------------------------------------------

def _keine_berechtigung(request):
    """F-112: Antwort 403 mit Seite „Keine Berechtigung“."""
    return render(request, "konten/keine_berechtigung.html", status=403)
