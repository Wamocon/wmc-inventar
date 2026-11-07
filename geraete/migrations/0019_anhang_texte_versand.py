"""Anhänge am Gerät (Kapitel 3.1), Protokolltexte mit Version (F-130), Versand offen (F-139)."""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("geraete", "0018_leihe_verlaengerung_bis"),
    ]

    operations = [
        migrations.CreateModel(
            name="GeratAnhang",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="Name")),
                ("datei", models.FileField(upload_to="anhaenge/", verbose_name="Datei")),
                ("hochgeladen_am", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Hochgeladen am")),
                ("gerat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="anhaenge", to="geraete.gerat")),
                ("hochgeladen_von", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="Hochgeladen von")),
            ],
            options={"verbose_name": "Anhang", "verbose_name_plural": "Anhänge", "ordering": ["-id"]},
        ),
        migrations.AddField(
            model_name="protokoll",
            name="texte",
            field=models.JSONField(blank=True, default=dict, verbose_name="Protokolltexte"),
        ),
        migrations.AddField(
            model_name="protokoll",
            name="pdf_versand_offen",
            field=models.BooleanField(default=False, verbose_name="Versand des PDF offen"),
        ),
    ]
