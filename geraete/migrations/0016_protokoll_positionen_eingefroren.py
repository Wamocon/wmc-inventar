"""Protokoll nach FRM-001 und FRM-002 (F-130 bis F-139).

Der Passwortanfang aus ``bearbeiter_signatur`` verschwindet mit dem Feld (N-05).
Protokolle von vor dieser Migration zeigen ihr eines Gerät, ohne Positionen.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geraete", "0015_protokoll_gegenzeichnung_erinnerung_gesendet"),
    ]

    operations = [
        migrations.RemoveField(model_name="protokoll", name="bearbeiter_signatur"),
        migrations.AddField(
            model_name="protokoll",
            name="checkliste_bemerkung",
            field=models.JSONField(blank=True, default=dict, verbose_name="Bemerkungen zur Checkliste"),
        ),
        migrations.AddField(
            model_name="protokoll",
            name="positionen",
            field=models.JSONField(blank=True, default=list, verbose_name="Geräte des Protokolls"),
        ),
        migrations.AddField(
            model_name="protokoll",
            name="html_eingefroren",
            field=models.TextField(blank=True, default="", verbose_name="Inhalt, eingefroren mit der Signatur"),
        ),
        migrations.AlterField(
            model_name="protokoll",
            name="fassung",
            field=models.CharField(default="1.1", max_length=8, verbose_name="Fassung"),
        ),
        migrations.AlterField(
            model_name="protokoll",
            name="stand",
            field=models.CharField(
                choices=[
                    ("scan-offen", "Scan offen"),
                    ("bearbeiter-offen", "Bearbeiter offen"),
                    ("gegenzeichnung-offen", "Gegenzeichnung offen"),
                    ("abgeschlossen", "Abgeschlossen"),
                    ("ersetzt", "Ersetzt durch eine neue Fassung"),
                ],
                default="scan-offen", max_length=24, verbose_name="Stand",
            ),
        ),
        migrations.AlterField(
            model_name="signaturcode",
            name="code",
            field=models.CharField(max_length=6, verbose_name="Code"),
        ),
    ]
