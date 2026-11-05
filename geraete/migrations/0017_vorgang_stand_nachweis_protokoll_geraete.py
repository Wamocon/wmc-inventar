"""Vorgang nach Kapitel 3.2 (F-43), Löschnachweis (F-56, F-57), Protokoll mit mehreren Geräten (F-20, F-52)."""
import django.db.models.deletion
from django.db import migrations, models


def _text(name, verbose, laenge):
    return migrations.AddField(
        model_name="vorgang",
        name=name,
        field=models.CharField(blank=True, default="", max_length=laenge, verbose_name=verbose),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("geraete", "0016_protokoll_positionen_eingefroren"),
    ]

    operations = [
        _text("status_vorher", "Status vorher", 24),
        _text("status_nachher", "Status nachher", 24),
        _text("person_vorher", "Person vorher", 200),
        _text("person_nachher", "Person nachher", 200),
        _text("ort_vorher", "Ort vorher", 160),
        _text("ort_nachher", "Ort nachher", 160),
        migrations.AddField(
            model_name="vorgang",
            name="protokoll",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="vorgaenge_des_protokolls", to="geraete.protokoll", verbose_name="Protokoll",
            ),
        ),
        _text("loeschung_art", "Art der Löschung", 32),
        _text("loeschung_nachweis", "Nachweisnummer", 240),
        migrations.AddField(
            model_name="vorgang",
            name="nachweis_datei",
            field=models.FileField(blank=True, upload_to="nachweise/", verbose_name="Nachweis (Datei)"),
        ),
        migrations.AddField(
            model_name="vorgang",
            name="vorfall_gemeldet",
            field=models.BooleanField(default=False, verbose_name="Vorfall gemeldet"),
        ),
        migrations.AddField(
            model_name="protokoll",
            name="weitere_geraete",
            field=models.ManyToManyField(
                blank=True, related_name="weitere_protokolle", to="geraete.gerat", verbose_name="Weitere Geräte",
            ),
        ),
    ]
