from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0002_application_vehicle"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="policy_accepted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="policy_version_accepted",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
