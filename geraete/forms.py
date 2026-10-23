"""Formulare für Geräte (M2 Bestand).

F-11, F-13 (Pflichtfelder), F-14 (Seriennummer je Kategorie),
F-15 (Bearbeiten). Validierung über die Service-Schicht (Fehlermeldung
aus services.GeratFehler).
"""
from __future__ import annotations

from django import forms

from stammdaten.models import Kategorie, Person

from . import services
from .models import Gerat

STATUS_WAHL = [
    ("", "Status wählen …"),
    (Gerat.STATUS_AUF_LAGER, "Auf Lager"),
    (Gerat.STATUS_IN_BENUTZUNG, "In Benutzung"),
    (Gerat.STATUS_IN_REPARATUR, "In Reparatur"),
    (Gerat.STATUS_AUSGEMUSTERT, "Ausgemustert"),
]


class GeratForm(forms.ModelForm):
    """Neues Gerät (F-11 bis F-14) oder bestehendes (F-15)."""

    status = forms.CharField(
        required=False,
        widget=forms.Select(choices=STATUS_WAHL),
        label="Status",
    )
    person = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        required=False,
        label="Zuweisende Person",
        widget=forms.Select(attrs={"data-test": "person-wahl"}),
        help_text="Person aus dem Verzeichnis oder später beim Verliehen.",
    )

    class Meta:
        model = Gerat
        fields = [
            "kategorie", "hersteller", "modell", "seriennummer",
            "zustand", "leihpool", "person", "ort", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "notiz",
        ]
        widgets = {
            "kategorie": forms.Select,
            "zustand": forms.Select,
            "standardzuehoer": forms.Textarea(attrs={"rows": 3}),
            "technische_daten": forms.Textarea(attrs={"rows": 4}),
            "notiz": forms.Textarea(attrs={"rows": 3}),
            "kaufpreis_netto": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kategorie"].label = "Kategorie"
        self.fields["zustand"].label = "Zustand"
        self.fields["leihpool"].label = "Leihpool"
        self.fields["person"].label = "Zuweisende Person (optional)"
        self.fields["ort"].label = "Ort (optional)"
        if not kwargs.get("instance", None):
            self.fields["status"].widget.attrs.pop("data-ke-status", None)

    def clean(self) -> dict:
        daten = super().clean()
        kategorie = daten.get("kategorie")
        seriennummer = (daten.get("seriennummer") or "").strip()
        # F-14: Seriennummer nur Pflicht, wenn die Kategorie es verlangt.
        if kategorie is not None and kategorie.seriennummer_pflicht and not seriennummer:
            self.add_error(
                "seriennummer", "Diese Kategorie verlangt eine Seriennummer."
            )
        person = daten.get("person")
        ort = daten.get("ort")
        if person and ort and not (self.instance and self.instance.pk):
            # Neu anlegen: Person UND Ort ist kein gültiger Anfangszustand.
            self.add_error(
                None, "Ein Gerät steht bei einer Person oder an einem Ort, nicht beides."
            )
        return daten


class GeratBearbeitungsForm(GeratForm):
    """Ändern eines vorhandenen Geräts (F-15). Inventarnummer bleibt (F-12)."""

    class Meta(GeratForm.Meta):
        # Status nicht per Formular änderbar: Statuswechsel sind Vorgänge
        # (Kapitel 4), hier nur Stammdaten.
        fields = [
            "kategorie", "hersteller", "modell", "seriennummer",
            "zustand", "leihpool", "person", "ort", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "notiz",
        ]


def kategorie_wahl() -> forms.ChoiceField:
    auswahl = [("", "Kategorie wählen …")]
    for k in sorted(Kategorie.objects.all(), key=lambda k: k.name):
        auswahl.append((str(k.pk), k.name))
    return forms.ChoiceField(choices=auswahl, label="Kategorie")
