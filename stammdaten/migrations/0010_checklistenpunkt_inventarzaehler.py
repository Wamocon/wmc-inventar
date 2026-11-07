"""Checklisten als Daten (Kapitel 3.2), Inventarnummern werden nie zweimal vergeben (F-14)."""
from django.db import migrations, models

from stammdaten.checklisten import vorbelegen


def belegen(apps, schema_editor):
    vorbelegen(apps.get_model("stammdaten", "Checklistenpunkt"))


class Migration(migrations.Migration):

    dependencies = [
        ("stammdaten", "0009_etikettenformat_text"),
    ]

    operations = [
        migrations.CreateModel(
            name="Checklistenpunkt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("liste", models.CharField(choices=[("zugaenge", "Zugänge"), ("offboarding", "IT-Offboarding")], max_length=20, verbose_name="Liste")),
                ("schluessel", models.CharField(max_length=40, verbose_name="Schlüssel")),
                ("text", models.CharField(max_length=200, verbose_name="Text")),
                ("reihenfolge", models.PositiveIntegerField(default=0, verbose_name="Reihenfolge")),
                ("aktiv", models.BooleanField(default=True, verbose_name="aktiv")),
            ],
            options={
                "verbose_name": "Checklistenpunkt",
                "verbose_name_plural": "Checklistenpunkte",
                "ordering": ["liste", "reihenfolge", "id"],
                "constraints": [models.UniqueConstraint(fields=("liste", "schluessel"), name="checklistenpunkt_eindeutig")],
            },
        ),
        migrations.RunPython(belegen, migrations.RunPython.noop),
        migrations.AddField(
            model_name="einstellungen",
            name="inventar_zaehler",
            field=models.PositiveIntegerField(default=0, verbose_name="Höchste vergebene Inventarnummer"),
        ),
    ]
