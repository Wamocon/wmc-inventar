# A-0905 M7 Teil 1: Einstellungen (F-122, F-90, F-96, F-130, N-02)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stammdaten', '0004_grundriss_datei'),
    ]

    operations = [
        migrations.CreateModel(
            name='Einstellungen',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('firmenname', models.CharField(blank=False, default='', max_length=200, verbose_name='Firmenname')),
                ('absenderzeile', models.CharField(default='', max_length=255, verbose_name='Absenderzeile')),
                ('telefon', models.CharField(default='', max_length=50, verbose_name='Telefon der IT')),
                ('email_it', models.EmailField(blank=True, default='', max_length=254, verbose_name='E-Mail der IT')),
                ('logo', models.FileField(blank=True, default='', upload_to='logo/', verbose_name='Logo (PNG oder SVG)')),
                ('nutzungsbedingungen_ausgabe', models.TextField(blank=True, default='', verbose_name='Nutzungsbedingungen (Ausgabeprotokoll)')),
                ('nutzungsbedingungen_version', models.CharField(default='1', max_length=20, verbose_name='Version Nutzungsbedingungen')),
                ('erklaerungen_ausgabe', models.TextField(blank=True, default='', verbose_name='Erklärungen (Ausgabeprotokoll)')),
                ('erklaerungen_version', models.CharField(default='1', max_length=20, verbose_name='Version Erklärungen')),
                ('unterzeichnung_ausgabe', models.TextField(blank=True, default='', verbose_name='Elektronische Unterzeichnung (Ausgabeprotokoll)')),
                ('unterzeichnung_version', models.CharField(default='1', max_length=20, verbose_name='Version Elektronische Unterzeichnung')),
                ('erklaerungen_ruecknahme', models.TextField(blank=True, default='', verbose_name='Erklärungen (Rücknahmeprotokoll)')),
                ('erklaerungen_ruecknahme_version', models.CharField(default='1', max_length=20, verbose_name='Version Erklärungen (Rücknahme)')),
                ('unterzeichnung_ruecknahme', models.TextField(blank=True, default='', verbose_name='Elektronische Unterzeichnung (Rücknahmeprotokoll)')),
                ('unterzeichnung_ruecknahme_version', models.CharField(default='1', max_length=20, verbose_name='Version Elektronische Unterzeichnung (Rücknahme)')),
                ('etikettenformat', models.CharField(choices=[('a4', 'A4, 10 Etiketten je Seite'), ('a5', 'A5, 10 Etiketten je Seite')], default='a4', max_length=20, verbose_name='Etikettenformat')),
                ('erinnerungsfrist_tage', models.PositiveIntegerField(default=7, verbose_name='Erinnerungsfrist (Tage vor Fälligkeit)')),
                ('smtp_server', models.CharField(default='', max_length=255, verbose_name='SMTP-Server')),
                ('smtp_port', models.PositiveIntegerField(default=587, verbose_name='SMTP-Port')),
                ('smtp_tls', models.BooleanField(default=True, verbose_name='TLS')),
                ('smtp_absender', models.EmailField(blank=True, default='', max_length=254, verbose_name='SMTP-Absender')),
                ('smtp_benutzer', models.CharField(default='', max_length=255, verbose_name='SMTP-Benutzer')),
                ('smtp_passwort', models.CharField(default='', max_length=255, verbose_name='SMTP-Passwort')),
                ('mail_verleih_anfrage', models.BooleanField(default=True, verbose_name='E-Mail: Verleihanfrage')),
                ('mail_verleih_ablehnung', models.BooleanField(default=True, verbose_name='E-Mail: Verleih-Ablehnung')),
                ('mail_verleih_genehmigung', models.BooleanField(default=True, verbose_name='E-Mail: Verleih-Genehmigung')),
                ('mail_verleih_zuruecknahme', models.BooleanField(default=True, verbose_name='E-Mail: Verleih-Zurücknahme')),
                ('mail_protokoll_gesendet', models.BooleanField(default=True, verbose_name='E-Mail: Protokoll gesendet')),
                ('mail_protokoll_unterzeichnet', models.BooleanField(default=True, verbose_name='E-Mail: Protokoll unterzeichnet')),
                ('aktualisiert_am', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Einstellungen',
                'verbose_name_plural': 'Einstellungen',
            },
        ),
    ]
