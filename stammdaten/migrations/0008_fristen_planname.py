from django.db import migrations, models


class Migration(migrations.Migration):
    """F-122: Erinnerungsfristen, die der Tageslauf liest. Kapitel 3.2: Name des Raumplans."""

    dependencies = [
        ("stammdaten", "0007_person_email_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="name",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="Name"),
        ),
        migrations.RemoveField(
            model_name="einstellungen",
            name="erinnerungsfrist_tage",
        ),
        migrations.AddField(
            model_name="einstellungen",
            name="frist_leihe_tage",
            field=models.PositiveIntegerField(default=1, verbose_name="Leihe endet: Erinnerung (Tage vorher)"),
        ),
        migrations.AddField(
            model_name="einstellungen",
            name="frist_garantie_tage",
            field=models.PositiveIntegerField(default=30, verbose_name="Garantie endet: Sammelmail (Tage vorher)"),
        ),
        migrations.AddField(
            model_name="einstellungen",
            name="frist_unterschrift_tage",
            field=models.PositiveIntegerField(default=3, verbose_name="Unterschrift offen: Sammelmail (mehr als Tage)"),
        ),
        migrations.AddField(
            model_name="einstellungen",
            name="frist_gegenzeichnung_tage",
            field=models.PositiveIntegerField(default=3, verbose_name="Gegenzeichnung: Erinnerung (Tage nach dem Versand)"),
        ),
    ]
