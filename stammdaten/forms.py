"""Formulare für Stammdaten (F-60, F-120, F-121, F-61)."""
import re

from django import forms

from .models import Ausstattungsprofil, Kategorie, Ort, Person, Plan, Profilposition, Einstellungen
from .uploads import UploadFehler, datei_pruefen

# F-96: Jede Mailart mit Schalter. Feld, Text, an wen und wann, Markierung.
MAILARTEN = [
    ("mail_leihe_endet_morgen", "Leihe endet morgen", "an Mitarbeiter, einmalig am Vortag", "mail-leihe-endet-morgen"),
    ("mail_leihe_ueberfaellig", "Leihe überfällig", "an Mitarbeiter und IT, täglich bis zur Rückgabe", "mail-leihe-ueberfaellig"),
    ("mail_verleih_anfrage", "Leihanfrage eingegangen", "an IT, sofort", "mail-verleih-anfrage"),
    ("mail_verleih_genehmigung", "Leihanfrage genehmigt", "an Mitarbeiter, sofort", "mail-verleih-genehmigung"),
    ("mail_verleih_ablehnung", "Leihanfrage abgelehnt", "an Mitarbeiter, sofort", "mail-verleih-ablehnung"),
    ("mail_garantie_sammelmail", "Garantie endet bald", "an IT, montags als Sammelmail", "mail-garantie"),
    ("mail_unterzeichen_sammelmail", "Unterschrift offen", "an IT, in der Sammelmail", "mail-unterschrift"),
    ("mail_protokoll_gesendet", "Link zur Gegenzeichnung", "an die Person, sobald der Bearbeiter signiert hat", "mail-protokoll-gesendet"),
    ("mail_gegenzeichnung_erinnerung", "Erinnerung an die Gegenzeichnung", "an die Person, am dritten Tag nach dem Versand", "mail-gegenzeichnung-erinnerung"),
    ("mail_protokoll_unterzeichnet", "Fertiges Protokoll", "an Person und Bearbeiter, nach der Gegenzeichnung", "mail-protokoll-unterzeichnet"),
]


class EinstellungenForm(forms.ModelForm):
    """M7 Teil 1 (A-0905): Einstellungen pflegen (F-122, F-90, F-96, F-130, N-02).

    Bleibt das Passwort leer, gilt das gespeicherte weiter. Beim Anzeigen
    wird es nie zurückgegeben. Das Logo ist kein Modellfeld des Formulars:
    Es wird am Inhalt geprüft und erst nach dem Speichern abgelegt (N-02).
    """

    logo = forms.FileField(label="Logo (PNG oder SVG)", required=False)

    class Meta:
        model = Einstellungen
        fields = [
            # Firma / Absender (F-122)
            "firmenname",
            "absenderzeile",
            "telefon",
            "email_it",
            # Protokolltexte (F-130)
            "nutzungsbedingungen_ausgabe",
            "nutzungsbedingungen_version",
            "erklaerungen_ausgabe",
            "erklaerungen_version",
            "unterzeichnung_ausgabe",
            "unterzeichnung_version",
            "erklaerungen_ruecknahme",
            "erklaerungen_ruecknahme_version",
            "unterzeichnung_ruecknahme",
            "unterzeichnung_ruecknahme_version",
            # Etiketten / Fristen
            "etikettenformat",
            "frist_leihe_tage",
            "frist_garantie_tage",
            "frist_unterschrift_tage",
            "frist_gegenzeichnung_tage",
            # SMTP (F-90)
            "smtp_server",
            "smtp_port",
            "smtp_tls",
            "smtp_absender",
            "smtp_benutzer",
            "smtp_passwort",
            # Mailarten (F-96)
            *[art[0] for art in MAILARTEN],
        ]
        widgets = {
            "nutzungsbedingungen_ausgabe": forms.Textarea(attrs={"rows": 4}),
            "erklaerungen_ausgabe": forms.Textarea(attrs={"rows": 3}),
            "unterzeichnung_ausgabe": forms.Textarea(attrs={"rows": 4}),
            "erklaerungen_ruecknahme": forms.Textarea(attrs={"rows": 3}),
            "unterzeichnung_ruecknahme": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {
            "firmenname": "Firmenname",
            "absenderzeile": "Absenderzeile",
            "telefon": "Telefon der IT",
            "email_it": "E-Mail der IT",
            "nutzungsbedingungen_ausgabe": "Nutzungsbedingungen (Ausgabeprotokoll)",
            "nutzungsbedingungen_version": "Version",
            "erklaerungen_ausgabe": "Erklärungen (Ausgabeprotokoll)",
            "erklaerungen_version": "Version",
            "unterzeichnung_ausgabe": "Elektronische Unterzeichnung (Ausgabeprotokoll)",
            "unterzeichnung_version": "Version",
            "erklaerungen_ruecknahme": "Erklärungen (Rücknahmeprotokoll)",
            "erklaerungen_ruecknahme_version": "Version",
            "unterzeichnung_ruecknahme": "Elektronische Unterzeichnung (Rücknahmeprotokoll)",
            "unterzeichnung_ruecknahme_version": "Version",
            "etikettenformat": "Etikettenformat",
            "smtp_server": "SMTP-Server",
            "smtp_port": "Port",
            "smtp_tls": "TLS",
            "smtp_absender": "Absender",
            "smtp_benutzer": "Benutzer",
            "smtp_passwort": "Passwort (leer = unverändert)",
        }
        help_texts = {
            "smtp_passwort": "Leer lassen, wenn sich nichts geändert hat.",
            "nutzungsbedingungen_version": "Neue Version gilt nur für neue Protokolle.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Passwort-Widget: Platzhalter, kein Wert
        self.fields["smtp_passwort"].widget = forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "leer = unverändert"}
        )
        self.fields["smtp_passwort"].initial = ""
        # Pflicht ist nur der Firmenname; SMTP kann noch offen sein (O-05).
        for name in ("absenderzeile", "telefon", "smtp_server", "smtp_benutzer", "smtp_passwort"):
            self.fields[name].required = False

    def clean_smtp_passwort(self):
        """Leer heißt unverändert, auch wenn schon eines gespeichert ist."""
        return self.cleaned_data.get("smtp_passwort") or self.instance.smtp_passwort

    def clean_logo(self):
        """N-02: Logo nur PNG oder SVG bis 10 MB, geprüft am Inhalt."""
        datei = self.cleaned_data.get("logo")
        if not datei:
            return None
        try:
            art, daten = datei_pruefen(datei, ("png", "svg"), "Das Logo muss eine PNG- oder SVG-Datei sein.")
        except UploadFehler as fehler:
            raise forms.ValidationError(str(fehler))
        return art, daten

    @property
    def mailarten(self):
        """F-96: Schalter je Mailart für die Vorlage."""
        return [
            {"feld": self[name], "name": name, "text": text, "hilfe": hilfe, "marke": marke}
            for name, text, hilfe, marke in MAILARTEN
        ]


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

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        andere = Kategorie.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if andere.exists():
            raise forms.ValidationError("Diese Kategorie gibt es schon.")
        return name


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
        # Ein Datumsfeld im Browser braucht JJJJ-MM-TT als Wert; im deutschen
        # Format bliebe es leer, und Speichern würde das Datum löschen.
        widgets = {
            "eintritt": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "austritt": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
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
        # A-0127, F-60: Auswahl der vorhandenen Pläne statt einer freien Zahl.
        self.fields["plan_id"] = forms.TypedChoiceField(
            label="Raumplan",
            required=False,
            coerce=int,
            empty_value=None,
            choices=[("", "—")] + [(p.pk, str(p)) for p in Plan.objects.all()],
        )

    def clean_kennung(self):
        """F-60: Kennung eindeutig, auch ohne Groß- und Kleinschreibung.

        Sie steht in Adressen (/arbeitsplaetze/<Kennung>/), daher keine Leerzeichen.
        """
        kennung = self.cleaned_data["kennung"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", kennung):
            raise forms.ValidationError(
                "Die Kennung darf nur Buchstaben, Ziffern, Bindestrich und Unterstrich enthalten."
            )
        andere = Ort.objects.filter(kennung__iexact=kennung).exclude(pk=self.instance.pk)
        if andere.exists():
            raise forms.ValidationError("Diese Kennung gibt es schon.")
        return kennung

    def clean(self):
        daten = super().clean()
        # Kapitel 3.2: Nur Arbeitsplätze haben Profil und feste Person.
        if daten.get("typ") != Ort.TYP_ARBEITSPLATZ:
            daten["feste_person"] = None
            daten["profil"] = None
        return daten


class PlanForm(forms.ModelForm):
    """Kapitel 3.2, F-65: ein Plan je Standort und Etage."""

    class Meta:
        model = Plan
        fields = ["standort", "etage", "name"]
        labels = {"standort": "Standort", "etage": "Etage", "name": "Name"}

    def clean(self):
        daten = super().clean()
        doppelt = Plan.objects.filter(
            standort=daten.get("standort"), etage=daten.get("etage")
        ).exclude(pk=self.instance.pk)
        if doppelt.exists():
            raise forms.ValidationError("Für diesen Standort und diese Etage gibt es schon einen Plan.")
        return daten


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
        widgets = {"anzahl": forms.NumberInput(attrs={"min": 1})}

    def clean_anzahl(self):
        anzahl = self.cleaned_data["anzahl"]
        if anzahl < 1:
            raise forms.ValidationError("Die Anzahl muss mindestens 1 sein.")
        return anzahl


ProfilPositionenFormSet = forms.inlineformset_factory(
    Ausstattungsprofil,
    Profilposition,
    form=ProfilpositionForm,
    extra=3,
    can_delete=True,
)
