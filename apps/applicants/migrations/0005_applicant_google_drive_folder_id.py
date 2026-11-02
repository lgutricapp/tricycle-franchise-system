from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applicants", "0004_split_applicant_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="applicant",
            name="google_drive_folder_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
