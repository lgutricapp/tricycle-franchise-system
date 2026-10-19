from django.db import migrations


REQUIRED_DOCUMENTS = [
    "Photocopy of Official Receipt and Certificate of Registration issued by LTO",
    "Accident insurance issued by competent insurance company",
    "Original Voter's Certificate",
    "Original Police Clearance",
    "Original Health Certificate",
    "Photocopy of CEDULA",
    "Photocopy of Driver's License (Front and Back)",
    "Parked Tricycle Photo — 1. Front",
    "Parked Tricycle Photo — 2. Back",
    "Parked Tricycle Photo — 3. Left Side",
    "Parked Tricycle Photo — 4. Right Side",
]


def seed_submission_requirements(apps, schema_editor):
    DocumentRequirement = apps.get_model("documents", "DocumentRequirement")
    requirements = DocumentRequirement.objects.using(schema_editor.connection.alias)

    requirements.exclude(name__in=REQUIRED_DOCUMENTS).update(active=False)

    for name in REQUIRED_DOCUMENTS:
        existing = requirements.filter(name=name).order_by("-active", "pk")
        requirement = existing.first()
        if requirement is None:
            requirements.create(
                name=name,
                application_type="BOTH",
                required=True,
                active=True,
            )
            continue

        existing.exclude(pk=requirement.pk).update(active=False)
        requirements.filter(pk=requirement.pk).update(
            application_type="BOTH",
            required=True,
            active=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_alter_applicationdocument_uploaded_file_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_submission_requirements,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
