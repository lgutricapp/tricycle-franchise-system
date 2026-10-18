from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.applicants.models import Applicant
from apps.franchises.models import Vehicle, FranchiseHolder, Franchise
from .models import Application
from .services import transition_application, register_franchise, InvalidTransition
from .forms import PolicyAcceptanceForm, VehicleForm
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

    def test_approved_new_application_can_be_registered_as_franchise(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(self.application, Application.Status.APPROVED, self.staff)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.APPROVED)
        self.assertIsNone(self.application.franchise)

        franchise = register_franchise(self.application, "TRI-2026-APPROVED-1", self.staff)
        self.application.refresh_from_db()
        self.assertEqual(franchise.vehicle, self.vehicle)
        self.assertEqual(franchise.status, Franchise.Status.ACTIVE)
        self.assertEqual(self.application.status, Application.Status.COMPLETED)

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
        transition_application(renewal, Application.Status.APPROVED, self.staff)

        franchise.refresh_from_db()
        self.assertGreater(franchise.expiration_date, old_expiration)
        renewal.refresh_from_db()
        self.assertEqual(renewal.status, Application.Status.COMPLETED)

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


class PolicyAcceptanceFormTests(TestCase):
    def test_policy_acceptance_is_required(self):
        form = PolicyAcceptanceForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("accepted", form.errors)

    def test_checked_policy_acceptance_is_valid(self):
        form = PolicyAcceptanceForm(data={"accepted": "on"})
        self.assertTrue(form.is_valid())


class ApplicationValidationFeedbackTests(TestCase):
    def test_new_application_error_returns_to_documents_step(self):
        response = self.client.post(reverse("applications:new"), {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
            "plate_number": "FB-1001",
            "engine_number": "FB-ENG-1001",
            "chassis_number": "FB-CHS-1001",
            "make": "Honda",
            "model": "TMX",
            "color": "Red",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-initial-step="2"')
        self.assertContains(response, "You must agree to the Terms &amp; Conditions")
        self.assertContains(response, "Uploaded files are not retained")
        self.assertEqual(Application.objects.count(), 0)

    def test_vehicle_error_returns_to_vehicle_step(self):
        Vehicle.objects.create(
            plate_number="FB-DUP-1",
            engine_number="FB-DUP-ENG",
            chassis_number="FB-DUP-CHS",
            make="Honda",
            model="TMX",
            color="Black",
        )
        response = self.client.post(reverse("applications:new"), {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
            "plate_number": "FB-DUP-1",
            "engine_number": "FB-ENG-1002",
            "chassis_number": "FB-CHS-1002",
            "make": "Honda",
            "model": "TMX",
            "color": "Red",
            "accepted": "on",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-initial-step="1"')
        self.assertContains(response, "A vehicle with this plate number is already registered.")
        self.assertEqual(Application.objects.count(), 0)

    def test_valid_submission_records_policy_acceptance(self):
        response = self.client.post(reverse("applications:new"), {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
            "plate_number": "FB-1003",
            "engine_number": "FB-ENG-1003",
            "chassis_number": "FB-CHS-1003",
            "make": "Honda",
            "model": "TMX",
            "color": "Red",
            "accepted": "on",
        })

        self.assertEqual(response.status_code, 302)
        application = Application.objects.get()
        self.assertIsNotNone(application.policy_accepted_at)
        self.assertEqual(application.policy_version_accepted, "2026-10-18")


class SubmissionConfirmationTests(TestCase):
    def setUp(self):
        self.applicant = Applicant.objects.create(
            first_name="Taylor",
            last_name="Applicant",
            address="Bontoc",
            contact_number="09171234567",
        )

    def test_new_application_has_themed_confirmation(self):
        application = Application.objects.create(
            applicant=self.applicant,
            type=Application.ApplicationType.NEW,
        )

        response = self.client.get(
            reverse("applications:submitted", kwargs={"reference_code": application.reference_code})
        )

        self.assertContains(response, "Application Submitted Successfully")
        self.assertContains(response, "Important reminder")
        self.assertContains(response, "submission-reminder card")
        self.assertContains(response, "Track your submission")

    def test_renewal_has_renewal_confirmation(self):
        application = Application.objects.create(
            applicant=self.applicant,
            type=Application.ApplicationType.RENEWAL,
        )

        response = self.client.get(
            reverse("applications:submitted", kwargs={"reference_code": application.reference_code})
        )

        self.assertContains(response, "Renewal Submitted Successfully")
        self.assertContains(response, "Your renewal reference code is:")