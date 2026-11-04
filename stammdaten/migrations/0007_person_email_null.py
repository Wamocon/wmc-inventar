from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stammdaten", "0006_m7_t2_mailversand_zaehlerstand"),
    ]

    operations = [
        migrations.AlterField(
            model_name="person",
            name="email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                null=True,
                unique=True,
                verbose_name="E-Mail",
            ),
        ),
    ]
