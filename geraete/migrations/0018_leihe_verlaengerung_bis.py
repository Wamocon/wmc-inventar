from django.db import migrations, models


class Migration(migrations.Migration):
    """F-35: Verlängerung anfragen, das gewünschte Datum steht an der Leihe."""

    dependencies = [
        ("geraete", "0017_vorgang_stand_nachweis_protokoll_geraete"),
    ]

    operations = [
        migrations.AddField(
            model_name="leihe",
            name="verlaengerung_bis",
            field=models.DateField(
                blank=True, null=True, verbose_name="Verlängerung angefragt bis"
            ),
        ),
    ]
