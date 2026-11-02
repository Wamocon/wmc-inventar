"""A-0123 M6 Teil 1: Protokoll mit PDF, Fotos und Papierweg.

- F-130: Wortlaut der Vorlage (Art, Fassung, Formularnummer, Absenderzeile,
  Empfängeranschrift, Bearbeiter)
- F-132: Checkliste Zugänge (sechs Punkte, ja/nein)
- F-133: Prüfpunkte IT-Offboarding (13 Punkte)
- F-134: Fotos als Anlage hinter dem Protokoll
- F-22:  hochgeladener Scan des unterzeichneten Protokolls
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('geraete', '0009_alter_leihe_status'),
        ('konten', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='protokoll',
            name='art',
            field=models.CharField(
                choices=[
                    ('ausgabe', 'Ausgabe (FRM-001)'),
                    ('ruecknahme', 'Rücknahme (FRM-002)'),
                ],
                default='ausgabe',
                max_length=16,
                verbose_name='Art',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='fassung',
            field=models.CharField(default='1.0', max_length=8, verbose_name='Fassung'),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='formularnummer',
            field=models.CharField(
                default='FRM-001', max_length=24,
                verbose_name='Formularnummer (Fußzeile)',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='absenderzeile',
            field=models.CharField(
                default='Wamocon GmbH · IT', max_length=240,
                verbose_name='Absenderzeile',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='empfaenger_anschrift',
            field=models.TextField(
                blank=True, default='',
                verbose_name='Empfängeranschrift (Briefkopf)',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='bearbeiter',
            field=models.CharField(
                blank=True, default='', max_length=120,
                verbose_name='Bearbeiter',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='checkliste',
            field=models.JSONField(
                blank=True, default=dict,
                verbose_name='Checkliste Zugänge',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='offboarding',
            field=models.JSONField(
                blank=True, default=dict,
                verbose_name='Prüfpunkte IT-Offboarding',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='scan_datei',
            field=models.FileField(
                blank=True, default='',
                upload_to='protokolle/scans/',
                verbose_name='Scan des Protokolls',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='scan_am',
            field=models.DateTimeField(
                blank=True, null=True,
                verbose_name='Scan hochgeladen am',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='anhaenge',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Anhänge (Fotos)',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='scan_von',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='scans_hochgeladen',
                to='konten.konto',
                verbose_name='Scan hochgeladen von',
            ),
        ),
        migrations.AddField(
            model_name='protokoll',
            name='rueckgabe_zu_protokoll',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='rueckgaben',
                to='geraete.protokoll',
                verbose_name='Rücknahme zu Protokoll',
            ),
        ),
    ]
