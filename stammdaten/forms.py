"""Formulare für Stammdaten (F-60, F-120, F-121, F-61)."""
from django import forms

from .models import Ausstattungsprofil, Kategorie, Ort, Person, Profilposition, Einstellungen


class EinstellungenForm(forms.ModelForm):
    """M7 Teil 1 (A-0905): Einstellungen pflegen (F-122, F-90, F-96, F-130, N-02).

    Das Passwort wird beim Speichern leer übergeben, wenn das Feld
    leer bleibt (nicht überschreiben). Beim Anzeigen wird das
    Passwort nie zurückgegeben.
    """

    class Meta:
        model = Einstellungen
        fields = [
            # Firma / Absender (F-122)
            "firmenname",
            "absenderzeile",
            "telefon",
            "email_it",
            # Logo (N-02)
            "logo",
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
            "erinnerungsfrist_tage",
            # SMTP (F-90)
            "smtp_server",
            "smtp_port",
            "smtp_tls",
            "smtp_absender",
            "smtp_benutzer",
            "smtp_passwort",
            # Mailtypen (F-96)
            "mail_verleih_anfrage",
            "mail_verleih_ablehnung",
            "mail_verleih_genehmigung",
            "mail_verleih_zuruecknahme",
            "mail_protokoll_gesendet",
            "mail_protokoll_unterzeichnet",
        ]
        widgets = {
            "nutzungsbedingungen_ausgabe": forms.Textarea(attrs={"rows": 4}),
            "erklaerungen_ausgabe": forms.Textarea(attrs={"rows": 3}),
            "unterzeichnung_ausgabe": forms.Textarea(attrs={"rows": 4}),
            "erklaerungen_ruecknahme": forms.Textarea(attrs={"rows": 3}),
            "unterzeichnung_ruecknahme": forms.Textarea(attrs={"rows": 4}),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/svg+xml"}),
        }
        labels = {
            "firmenname": "Firmenname",
            "absenderzeile": "Absenderzeile",
            "telefon": "Telefon der IT",
            "email_it": "E-Mail der IT",
            "logo": "Logo (PNG oder SVG)",
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
            "erinnerungsfrist_tage": "Erinnerungsfrist (Tage)",
            "smtp_server": "SMTP-Server",
            "smtp_port": "Port",
            "smtp_tls": "TLS",
            "smtp_absender": "Absender",
            "smtp_benutzer": "Benutzer",
            "smtp_passwort": "Passwort (leer = unverändert)",
            "mail_verleih_anfrage": "Verleihanfrage",
            "mail_verleih_ablehnung": "Verleih-Ablehnung",
            "mail_verleih_genehmigung": "Verleih-Genehmigung",
            "mail_verleih_zuruecknahme": "Verleih-Zurücknahme",
            "mail_protokoll_gesendet": "Protokoll gesendet",
            "mail_protokoll_unterzeichnet": "Protokoll unterzeichnet",
        }
        help_texts = {
            "smtp_passwort": "Leer lassen, wenn sich nichts geändert hat.",
            "logo": "PNG oder SVG. SVG wird nur als Bild eingebunden (N-02).",
            "nutzungsbedingungen_version": "Neue Version gilt nur für neue Protokolle (F-130).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Passwort-Widget: Platzhalter, kein Wert
        self.fields["smtp_passwort"].widget = forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "leer = unverändert"}
        )
        self.fields["smtp_passwort"].required = False
        self.fields["smtp_passwort"].initial = ""


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
