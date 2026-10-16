from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.applicants.models import Applicant
from apps.franchises.models import Vehicle, FranchiseHolder, Franchise
from .models import Application
from .services import transition_application, InvalidTransition
from .forms import VehicleForm
from datetime import date

User = get_user_model()


class ReferenceCodeTests(TestCase):
    def setUp(self):
        self.applicant = Applicant.objects.create(
            full_name="Juan Dela Cruz", address="Baguio City", contact_number="09171234567"
        )

    def test_reference_code_is_generated_automatically(self):
        application = Application.objects.create(applicant=self.applicant, type=Application.ApplicationType.NEW)
        self.assertEqual(len(application.reference_code), 10)
        self.assertNotEqual(application.reference_code, "")

    def test_reference_codes_are_unique(self):
        codes = set()
        for _ in range(20):
            app = Application.objects.create(applicant=self.applicant, type=Application.ApplicationType.NEW)
            codes.add(app.reference_code)
        self.assertEqual(len(codes), 20)  # no collisions across 20 generations

    def test_reference_code_excludes_ambiguous_characters(self):
        application = Application.objects.create(applicant=self.applicant, type=Application.ApplicationType.NEW)
        for char in "0O1I":
            self.assertNotIn(char, application.reference_code)


class ApplicationTransitionTests(TestCase):
    def setUp(self):
        self.applicant = Applicant.objects.create(
            full_name="Maria Santos", address="Baguio City", contact_number="09171234567"
        )
        self.vehicle = Vehicle.objects.create(
            plate_number="ABC-1234", engine_number="ENG001", chassis_number="CHS001",
            make="Honda", model="TMX", color="Red",
        )
        self.staff = User.objects.create_user(username="staffuser", password="testpass123", role=User.Role.STAFF)
        self.application = Application.objects.create(
            applicant=self.applicant, vehicle=self.vehicle,
            type=Application.ApplicationType.NEW, status=Application.Status.SUBMITTED,
        )

    def test_valid_transition_succeeds(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.UNDER_REVIEW)

    def test_valid_transition_writes_status_history(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff, remarks="Looks complete")
        latest = self.application.status_history.first()
        self.assertEqual(latest.status, Application.Status.UNDER_REVIEW)
        self.assertEqual(latest.remarks, "Looks complete")
        self.assertEqual(latest.changed_by, self.staff)

    def test_invalid_transition_is_rejected(self):
        # SUBMITTED -> APPROVED is not an allowed direct jump
        with self.assertRaises(InvalidTransition):
            transition_application(self.application, Application.Status.APPROVED, self.staff)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.SUBMITTED)  # unchanged

    def test_approval_creates_franchise_for_new_application(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(self.application, Application.Status.FOR_APPROVAL, self.staff)
        transition_application(self.application, Application.Status.APPROVED, self.staff)

        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.franchise)
        self.assertEqual(self.application.franchise.vehicle, self.vehicle)
        self.assertEqual(self.application.franchise.status, Franchise.Status.ACTIVE)

    def test_approval_updates_expiration_for_renewal(self):
        holder = FranchiseHolder.objects.create(
            full_name="Maria Santos", address="Baguio City", contact_number="09171234567"
        )
        franchise = Franchise.objects.create(
            franchise_number="TRI-2026-00099", holder=holder, vehicle=self.vehicle,
            date_issued=date(2025, 1, 1), expiration_date=date(2026, 1, 1),
        )
        renewal = Application.objects.create(
            applicant=self.applicant, vehicle=self.vehicle, franchise=franchise,
            type=Application.ApplicationType.RENEWAL, status=Application.Status.SUBMITTED,
        )
        old_expiration = franchise.expiration_date

        transition_application(renewal, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(renewal, Application.Status.FOR_APPROVAL, self.staff)
        transition_application(renewal, Application.Status.APPROVED, self.staff)

        franchise.refresh_from_db()
        self.assertGreater(franchise.expiration_date, old_expiration)

class VehicleFormTests(TestCase):
    def setUp(self):
        Vehicle.objects.create(
            plate_number="DUP-0001", engine_number="ENGDUP", chassis_number="CHSDUP",
            make="Honda", model="TMX", color="Black",
        )

    def test_duplicate_plate_number_is_rejected(self):
        form = VehicleForm(data={
            "plate_number": "DUP-0001", "engine_number": "ENGNEW", "chassis_number": "CHSNEW",
            "make": "Suzuki", "model": "Raider", "color": "Green",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("plate_number", form.errors)

    def test_unique_vehicle_data_is_accepted(self):
        form = VehicleForm(data={
            "plate_number": "NEW-0002", "engine_number": "ENGNEW2", "chassis_number": "CHSNEW2",
            "make": "Suzuki", "model": "Raider", "color": "Green",
        })
        self.assertTrue(form.is_valid())