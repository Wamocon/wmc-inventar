"""F-72: Der Name des Etikettenformats nennt den tatsächlichen Bogen."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stammdaten", "0008_fristen_planname"),
    ]

    operations = [
        migrations.AlterField(
            model_name="einstellungen",
            name="etikettenformat",
            field=models.CharField(
                choices=[("a4", "A4-Bogen, 24 Etiketten, 70 × 37 mm"), ("a5", "A5-Bogen, 10 Etiketten, 74 × 42 mm")],
                default="a4", max_length=20, verbose_name="Etikettenformat",
            ),
        ),
    ]
