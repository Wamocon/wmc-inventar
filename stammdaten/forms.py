"""Formulare für Stammdaten (F-60, F-120, F-121, F-61)."""
from django import forms

from .models import Ausstattungsprofil, Kategorie, Ort, Person, Profilposition


class KategorieForm(forms.ModelForm):
    """F-120: Kategorie pflegen (Name, hat Datenträger, Seriennummer Pflicht)."""

    class Meta:
        model = Kategorie
        fields = ["name", "hat_datentraeger", "seriennummer_pflicht"]
        labels = {
            "name": "Name",
            "hat_datentraeger": "hat Datenträger",
            "seriennummer_pflicht": "Seriennummer Pflicht",
        }


class PersonForm(forms.ModelForm):
    """F-121: Person pflegen (Anrede, Vorname, Nachname, E-Mail, Abteilung, Ein-/Austritt)."""

    class Meta:
        model = Person
        fields = [
            "anrede",
            "vorname",
            "nachname",
            "email",
            "abteilung",
            "eintritt",
            "austritt",
            "anschrift",
            "aktiv",
        ]
        labels = {
            "anrede": "Anrede",
            "vorname": "Vorname",
            "nachname": "Nachname",
            "email": "E-Mail",
            "abteilung": "Abteilung",
            "eintritt": "Eintritt",
            "austritt": "Austritt",
            "anschrift": "Anschrift (Briefkopf)",
            "aktiv": "aktiv",
        }
        widgets = {
            "eintritt": forms.DateInput(attrs={"type": "date"}),
            "austritt": forms.DateInput(attrs={"type": "date"}),
        }


class OrtForm(forms.ModelForm):
    """F-60: Ort pflegen (Kennung, Standort, Raum, Notiz).

    A-0127: Raumplan (plan_id), leer erlaubt.
    """

    class Meta:
        model = Ort
        fields = [
            "typ",
            "kennung",
            "name",
            "standort",
            "raum",
            "notiz",
            "feste_person",
            "profil",
            "plan_id",
        ]
        labels = {
            "typ": "Typ",
            "kennung": "Kennung",
            "name": "Name",
            "standort": "Standort",
            "raum": "Raum",
            "notiz": "Notiz",
            "feste_person": "Feste Person",
            "profil": "Ausstattungsprofil",
            "plan_id": "Raumplan",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["feste_person"].required = False
        self.fields["profil"].required = False
        self.fields["plan_id"].required = False


class ProfilForm(forms.ModelForm):
    """F-61: Ausstattungsprofil pflegen."""

    class Meta:
        model = Ausstattungsprofil
        fields = ["name"]
        labels = {"name": "Name"}


class ProfilpositionForm(forms.ModelForm):
    """F-61: Position im Profil (Kategorie und Anzahl)."""

    class Meta:
        model = Profilposition
        fields = ["kategorie", "anzahl"]
        labels = {
            "kategorie": "Kategorie",
            "anzahl": "Anzahl",
        }
