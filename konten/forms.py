"""Formulare für Anmeldung, Konten, Passwort (F-01 bis F-05)."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Konto

# F-04: mindestens 12 Zeichen
MIN_PASSWORT_LAENGE = 12


def _passwort_mind_12(wert):
    if len(wert) < MIN_PASSWORT_LAENGE:
        raise ValidationError(
            f"Das Passwort muss mindestens {MIN_PASSWORT_LAENGE} Zeichen lang sein."
        )
    validate_password(wert)


class AnmeldeForm(forms.Form):
    """F-01: Anmeldung mit E-Mail und Passwort."""

    email = forms.EmailField(label="E-Mail")
    passwort = forms.CharField(label="Passwort", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update({
            "autocomplete": "username",
            "data-test": "anmelde-email",
        })
        self.fields["passwort"].widget.attrs.update({
            "autocomplete": "current-password",
            "data-test": "anmelde-passwort",
        })


class PasswortVergessenForm(forms.Form):
    """F-03: Passwort vergessen – E-Mail."""

    email = forms.EmailField(label="E-Mail")


class PasswortSetForm(forms.Form):
    """F-02 / F-03: Neues Passwort setzen (mindestens 12 Zeichen)."""

    passwort = forms.CharField(
        label="Neues Passwort",
        widget=forms.PasswordInput,
        min_length=MIN_PASSWORT_LAENGE,
        validators=[_passwort_mind_12],
    )
    passwort_wiederholung = forms.CharField(
        label="Passwort wiederholen",
        widget=forms.PasswordInput,
        min_length=MIN_PASSWORT_LAENGE,
    )

    def clean(self):
        daten = super().clean()
        if daten.get("passwort") != daten.get("passwort_wiederholung"):
            raise forms.ValidationError("Die Passwörter stimmen nicht überein.")
        return daten


class PasswortAenderForm(forms.Form):
    """F-04: Passwort ändern – altes und neues Passwort."""

    altes_passwort = forms.CharField(
        label="Aktuelles Passwort",
        widget=forms.PasswordInput,
    )
    neues_passwort = forms.CharField(
        label="Neues Passwort",
        widget=forms.PasswordInput,
        min_length=MIN_PASSWORT_LAENGE,
        validators=[_passwort_mind_12],
    )
    neues_passwort_wiederholung = forms.CharField(
        label="Neues Passwort wiederholen",
        widget=forms.PasswordInput,
        min_length=MIN_PASSWORT_LAENGE,
    )

    def clean(self):
        daten = super().clean()
        if daten.get("neues_passwort") != daten.get("neues_passwort_wiederholung"):
            raise forms.ValidationError("Die neuen Passwörter stimmen nicht überein.")
        return daten


class KontoForm(forms.ModelForm):
    """F-02: Konten anlegen und ändern (Admin)."""

    class Meta:
        model = Konto
        fields = ["email", "rolle", "person", "aktiv"]
        labels = {
            "email": "E-Mail",
            "rolle": "Rolle",
            "person": "Person",
            "aktiv": "aktiv",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].required = False
        # Optional; wenn gesetzt, gilt dieselbe Regel wie überall (F-04).
        self.fields["passwort"] = forms.CharField(
            label="Passwort",
            widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
            required=False,
            min_length=MIN_PASSWORT_LAENGE,
            validators=[_passwort_mind_12],
            help_text=(
                "Leer lassen ändert nichts. Mindestens 12 Zeichen."
                if self.instance.pk
                else "Optional, mindestens 12 Zeichen. Die Einladungsmail geht in jedem Fall raus."
            ),
        )

    def clean_email(self):
        """Die Anmeldung sucht ohne Groß- und Kleinschreibung (F-01), also auch hier."""
        email = self.cleaned_data["email"]
        andere = Konto.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if andere.exists():
            raise ValidationError("Für diese E-Mail gibt es schon ein Konto.")
        return email

    def clean(self):
        daten = super().clean()
        rolle = daten.get("rolle")
        person = daten.get("person")
        if rolle == Konto.ROLLE_MITARBEITER and not person:
            self.add_error(
                "person",
                "Die Rolle Mitarbeiter braucht eine Person.",
            )
        return daten
