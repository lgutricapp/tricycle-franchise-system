from django.core.management.base import BaseCommand
from django.db.models import ProtectedError
from apps.documents.models import DocumentRequirement

NEW_REQUIREMENTS = [
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


class Command(BaseCommand):
    help = "Replace all existing document requirements with the current official list (applies to both New and Renewal)."

    def handle(self, *args, **options):
        deleted, deactivated = 0, 0

        for req in DocumentRequirement.objects.all():
            try:
                req.delete()
                deleted += 1
            except ProtectedError:
                req.active = False
                req.save()
                deactivated += 1
                self.stdout.write(self.style.WARNING(
                    f"Could not delete '{req.name}' — it has documents already submitted against it. "
                    f"Deactivated instead (hidden from forms, history preserved)."
                ))

        for name in NEW_REQUIREMENTS:
            DocumentRequirement.objects.create(
                name=name,
                application_type=DocumentRequirement.ApplicationType.BOTH,
                required=True,
                active=True,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. Deleted {deleted} old requirement(s), deactivated {deactivated} (protected by history), "
            f"created {len(NEW_REQUIREMENTS)} new requirement(s)."
        ))