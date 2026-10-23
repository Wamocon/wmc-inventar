"""Formulare für Geräte (M2 Bestand).

F-11, F-13 (Pflichtfelder), F-14 (Seriennummer je Kategorie),
F-15 (Bearbeiten), F-20 bis F-23 (Ausgabe), F-41 (Umzug), F-42 (Reparatur),
F-50 bis F-53 (Rückgabe, Austritt), F-55 bis F-58 (Ausmusterung, Archiv).
Validierung über die Service-Schicht (Fehlermeldung aus services.GeratFehler).
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


# --- M3 Lebenszyklus ---------------------------------------------------------

class GeratAusgabeForm(forms.Form):
    """Gerät ausgeben (F-20 bis F-23, M3)."""

    ziel_person = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        required=False,
        label="An Person",
        widget=forms.Select(attrs={"data-test": "ausgabe-person"}),
    )
    ziel_ort = forms.ModelChoiceField(
        queryset=None,  # Wird in __init__ gesetzt
        required=False,
        label="An Ort",
        widget=forms.Select(attrs={"data-test": "ausgabe-ort"}),
    )
    zurueck_am = forms.DateField(
        required=False,
        label="Zurück am",
        widget=forms.DateInput(attrs={"type": "date", "data-test": "zurueck-am"}),
    )
    anmerkung = forms.CharField(
        required=False,
        label="Anmerkung",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "anmerkung"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        self.fields["ziel_ort"].queryset = Ort.objects.all().order_by("kennung")

    def clean(self) -> dict:
        daten = super().clean()
        person = daten.get("ziel_person")
        ort = daten.get("ziel_ort")
        if not person and not ort:
            self.add_error(None, "Ziel muss eine Person oder ein Ort sein.")
        return daten


class GeratRueckgabeForm(forms.Form):
    """Gerät zurückgeben (F-50, M3)."""

    zustand_rueckgabe = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=True,
        label="Zustand bei Rückgabe",
        widget=forms.Select(attrs={"data-test": "zustand-rueckgabe"}),
    )
    zubehoer_komplett = forms.BooleanField(
        required=True,
        label="Zubehör komplett",
        widget=forms.CheckboxInput(attrs={"data-test": "zubehoer-komplett"}),
    )
    maengel = forms.CharField(
        required=False,
        label="Mängel",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "maengel"}),
    )
    ziel = forms.ChoiceField(
        choices=[("lager", "Lager"), ("reparatur", "Reparatur")],
        required=True,
        label="Ziel",
        widget=forms.Select(attrs={"data-test": "ziel"}),
    )
    fehlend = forms.BooleanField(
        required=False,
        label="Fehlt (startet Ausmusterung)",
        widget=forms.CheckboxInput(attrs={"data-test": "fehlend"}),
    )


class GeratUmzugForm(forms.Form):
    """Gerät umziehen (F-41, M3)."""

    ziel_ort = forms.ModelChoiceField(
        queryset=None,  # Wird in __init__ gesetzt
        required=True,
        label="Zielort",
        widget=forms.Select(attrs={"data-test": "umzug-ort"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        self.fields["ziel_ort"].queryset = Ort.objects.all().order_by("kennung")


class GeratReparaturStartForm(forms.Form):
    """Reparatur starten (F-42, M3)."""

    dienstleister = forms.CharField(
        required=True,
        label="Dienstleister",
        widget=forms.TextInput(attrs={"data-test": "dienstleister"}),
    )
    vorgangsnummer = forms.CharField(
        required=True,
        label="Vorgangsnummer",
        widget=forms.TextInput(attrs={"data-test": "vorgangsnummer"}),
    )
    notiz = forms.CharField(
        required=False,
        label="Notiz",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "reparatur-notiz"}),
    )


class GeratReparaturFertigForm(forms.Form):
    """Reparatur abschließen (F-42, M3)."""

    zustand = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=True,
        label="Zustand nach Reparatur",
        widget=forms.Select(attrs={"data-test": "reparatur-zustand"}),
    )
    ziel = forms.ChoiceField(
        choices=[("lager", "Lager"), ("zuordnung", "Bisherige Zuordnung")],
        required=True,
        label="Ziel",
        widget=forms.Select(attrs={"data-test": "reparatur-ziel"}),
    )
    kosten = forms.DecimalField(
        required=False,
        label="Kosten (EUR)",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "data-test": "kosten"}),
    )
    beleg = forms.CharField(
        required=False,
        label="Beleg",
        widget=forms.TextInput(attrs={"data-test": "beleg"}),
    )


class GeratAusmusterungForm(forms.Form):
    """Gerät ausmustern (F-55 bis F-58, M3)."""

    GRUENDE = [
        ("defekt", "Defekt"),
        ("veraltet", "Veraltet"),
        ("verkauft", "Verkauft"),
        ("verloren", "Verloren"),
        ("gestohlen", "Gestohlen"),
    ]

    grund = forms.ChoiceField(
        choices=GRUENDE,
        required=True,
        label="Grund",
        widget=forms.Select(attrs={"data-test": "ausmusterung-grund"}),
    )
    datum = forms.DateField(
        required=True,
        label="Datum",
        widget=forms.DateInput(attrs={"type": "date", "data-test": "ausmusterung-datum"}),
    )
    disposition = forms.CharField(
        required=True,
        label="Verbleib",
        widget=forms.TextInput(attrs={"data-test": "ausmusterung-disposition"}),
    )
    loeschung_art = forms.CharField(
        required=False,
        label="Art der Löschung (bei Datenträgern)",
        widget=forms.TextInput(attrs={"data-test": "loeschung-art"}),
    )
    loeschung_nachweis = forms.CharField(
        required=False,
        label="Nachweis der Löschung",
        widget=forms.TextInput(attrs={"data-test": "loeschung-nachweis"}),
    )
    bestaetigt_gemeldt = forms.BooleanField(
        required=False,
        label="Vorfall gemeldet (Pflicht bei Verlust/Diebstahl)",
        widget=forms.CheckboxInput(attrs={"data-test": "bestaetigt-gemeldet"}),
    )


def kategorie_wahl() -> forms.ChoiceField:
    auswahl = [("", "Kategorie wählen …")]
    for k in sorted(Kategorie.objects.all(), key=lambda k: k.name):
        auswahl.append((str(k.pk), k.name))
    return forms.ChoiceField(choices=auswahl, label="Kategorie")
