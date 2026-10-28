import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from apps.applicants.models import Applicant
from apps.documents.models import ApplicationDocument, DocumentRequirement
from apps.franchises.models import Vehicle, FranchiseHolder, Franchise
from apps.notifications.models import Notification
from apps.violations.models import Violation
from .models import Application
from .services import transition_application, register_franchise, InvalidTransition
from .forms import ApplicantForm, PolicyAcceptanceForm, VehicleForm

User = get_user_model()


class ApplicantFormValidationTests(TestCase):
    def setUp(self):
        self.data = {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
        }

    def test_accepts_letters_and_spaces_in_names(self):
        self.data.update(first_name="De La", middle_name="José", last_name="Cruz")
        self.assertTrue(ApplicantForm(data=self.data).is_valid())

    def test_rejects_numbers_and_symbols_in_names(self):
        for name in ("first_name", "middle_name", "last_name"):
            for invalid_value in ("Alex2", "Alex!"):
                with self.subTest(name=name, value=invalid_value):
                    data = {**self.data, name: invalid_value}
                    self.assertIn(name, ApplicantForm(data=data).errors)

    def test_requires_exactly_eleven_ascii_digits_for_contact_number(self):
        for invalid_number in ("1234567890", "091712345678", "09171ABC567"):
            with self.subTest(number=invalid_number):
                data = {**self.data, "contact_number": invalid_number}
                self.assertIn("contact_number", ApplicantForm(data=data).errors)


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
        cache.clear()
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

    def test_repeating_revision_required_transition_is_idempotent(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(self.application, Application.Status.REVISION_REQUIRED, self.staff)
        history_count = self.application.status_history.count()

        transition_application(self.application, Application.Status.REVISION_REQUIRED, self.staff)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.REVISION_REQUIRED)
        self.assertEqual(self.application.status_history.count(), history_count)

    def test_repeating_approved_transition_is_idempotent(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(self.application, Application.Status.APPROVED, self.staff, notify=False)
        history_count = self.application.status_history.count()

        transition_application(self.application, Application.Status.APPROVED, self.staff, notify=False)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.APPROVED)
        self.assertEqual(self.application.status_history.count(), history_count)

    def test_repeating_rejected_transition_is_idempotent(self):
        transition_application(self.application, Application.Status.UNDER_REVIEW, self.staff)
        transition_application(
            self.application, Application.Status.REJECTED, self.staff, remarks="Incomplete", notify=False
        )
        history_count = self.application.status_history.count()

        transition_application(
            self.application, Application.Status.REJECTED, self.staff, remarks="Incomplete", notify=False
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.REJECTED)
        self.assertEqual(self.application.status_history.count(), history_count)

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

    def test_repeating_renewal_approval_after_completion_is_idempotent(self):
        holder = FranchiseHolder.objects.create(
            full_name="Maria Santos", address="Baguio City", contact_number="09171234567"
        )
        franchise = Franchise.objects.create(
            franchise_number="TRI-2026-00098", holder=holder, vehicle=self.vehicle,
            date_issued=date(2025, 1, 1), expiration_date=date(2026, 1, 1),
        )
        renewal = Application.objects.create(
            applicant=self.applicant, vehicle=self.vehicle, franchise=franchise,
            type=Application.ApplicationType.RENEWAL, status=Application.Status.UNDER_REVIEW,
        )
        transition_application(renewal, Application.Status.APPROVED, self.staff, notify=False)
        franchise.refresh_from_db()
        expiration_after_approval = franchise.expiration_date
        history_count = renewal.status_history.count()

        transition_application(renewal, Application.Status.APPROVED, self.staff, notify=False)

        franchise.refresh_from_db()
        renewal.refresh_from_db()
        self.assertEqual(renewal.status, Application.Status.COMPLETED)
        self.assertEqual(franchise.expiration_date, expiration_after_approval)
        self.assertEqual(renewal.status_history.count(), history_count)

    def test_renewal_cannot_be_approved_with_unsettled_violation(self):
        holder = FranchiseHolder.objects.create(
            full_name="Maria Santos", address="Baguio City", contact_number="09171234567"
        )
        franchise = Franchise.objects.create(
            franchise_number="TRI-2026-00100", holder=holder, vehicle=self.vehicle,
            date_issued=date(2025, 1, 1), expiration_date=date(2026, 1, 1),
        )
        renewal = Application.objects.create(
            applicant=self.applicant, vehicle=self.vehicle, franchise=franchise,
            type=Application.ApplicationType.RENEWAL, status=Application.Status.UNDER_REVIEW,
        )
        Violation.objects.create(
            franchise=franchise, violation_type="Unsettled fine", date=date(2026, 1, 1),
        )

        with self.assertRaises(InvalidTransition):
            transition_application(renewal, Application.Status.APPROVED, self.staff)

        renewal.refresh_from_db()
        self.assertEqual(renewal.status, Application.Status.UNDER_REVIEW)

    def test_lookup_blocks_franchise_with_unsettled_violation(self):
        holder = FranchiseHolder.objects.create(
            first_name="Maria", last_name="Santos", address="Baguio City", contact_number="09171234567"
        )
        franchise = Franchise.objects.create(
            franchise_number="TRI-2026-00101", holder=holder, vehicle=self.vehicle,
            date_issued=date(2025, 1, 1), expiration_date=date(2026, 1, 1),
        )
        Violation.objects.create(
            franchise=franchise, violation_type="Unsettled fine", date=date(2026, 1, 1),
        )

        response = self.client.post(reverse("applications:renewal_lookup"), {
            "franchise_number": franchise.franchise_number,
            "last_name_confirm": "Santos",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be renewed until they are settled")

    def test_direct_renewal_url_blocks_get_and_post_with_unsettled_violation(self):
        holder = FranchiseHolder.objects.create(
            first_name="Maria", last_name="Santos", address="Baguio City", contact_number="09171234567"
        )
        franchise = Franchise.objects.create(
            franchise_number="TRI-2026-00102", holder=holder, vehicle=self.vehicle,
            date_issued=date(2025, 1, 1), expiration_date=date(2026, 1, 1),
        )
        Violation.objects.create(
            franchise=franchise, violation_type="Unsettled fine", date=date(2026, 1, 1),
        )
        renewal_url = reverse("applications:renewal_form", args=[franchise.franchise_number])

        get_response = self.client.get(renewal_url)
        post_response = self.client.post(renewal_url, {"accepted": "on"})

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "cannot be renewed until they are settled")
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "cannot be renewed until they are settled")
        self.assertFalse(Application.objects.filter(franchise=franchise).exists())

class RenewalOTPTests(TestCase):
    def setUp(self):
        cache.clear()
        self.holder = FranchiseHolder.objects.create(
            first_name="Maria",
            last_name="Santos",
            address="Baguio City",
            contact_number="09171234567",
        )
        self.vehicle = Vehicle.objects.create(
            plate_number="OTP-1234",
            engine_number="OTP-ENG",
            chassis_number="OTP-CHS",
            make="Honda",
            model="TMX",
            color="Red",
        )
        self.franchise = Franchise.objects.create(
            franchise_number="TRI-OTP-001",
            holder=self.holder,
            vehicle=self.vehicle,
            date_issued=date(2025, 1, 1),
            expiration_date=date(2027, 1, 1),
        )
        self.lookup_url = reverse("applications:renewal_lookup")
        self.verify_url = reverse("applications:renewal_verify")
        self.renewal_url = reverse(
            "applications:renewal_form", args=[self.franchise.franchise_number]
        )

    def test_correct_lookup_sends_otp_and_verification_grants_renewal_access(self):
        with patch("apps.notifications.services.deliver_sms", return_value={"success": True}) as send_sms:
            lookup_response = self.client.post(self.lookup_url, {
                "franchise_number": self.franchise.franchise_number,
                "last_name_confirm": "Santos",
            })

        self.assertRedirects(lookup_response, self.verify_url)
        self.assertEqual(send_sms.call_args.args[0], self.holder.contact_number)
        code = send_sms.call_args.args[1].split("code is ", 1)[1].split(".", 1)[0]
        self.assertEqual(len(code), 6)
        self.assertFalse(Notification.objects.filter(message__contains=code).exists())

        verify_response = self.client.post(self.verify_url, {"code": code})
        self.assertRedirects(verify_response, self.renewal_url)

        renewal_response = self.client.get(self.renewal_url)
        self.assertEqual(renewal_response.status_code, 200)
        self.assertContains(renewal_response, "Submit Renewal")

    def test_direct_renewal_access_requires_otp(self):
        response = self.client.get(self.renewal_url)
        self.assertRedirects(response, self.lookup_url)

    def test_pending_application_blocks_renewal_until_rejected(self):
        applicant = Applicant.objects.create(
            first_name=self.holder.first_name,
            middle_name=self.holder.middle_name,
            last_name=self.holder.last_name,
            address=self.holder.address,
            contact_number=self.holder.contact_number,
        )
        application = Application.objects.create(
            applicant=applicant,
            type=Application.ApplicationType.NEW,
            status=Application.Status.SUBMITTED,
        )
        session = self.client.session
        session["renewal_verified"] = {
            "franchise_id": self.franchise.pk,
            "expires_at": timezone.now().timestamp() + 900,
        }
        session.save()

        blocked_response = self.client.get(self.renewal_url)
        self.assertRedirects(blocked_response, self.lookup_url)
        self.assertEqual(Application.objects.count(), 1)

        application.status = Application.Status.REJECTED
        application.save()

        allowed_response = self.client.get(self.renewal_url)
        self.assertEqual(allowed_response.status_code, 200)
        self.assertContains(allowed_response, "Submit Renewal")

    def test_otp_verification_is_bound_to_its_franchise(self):
        with patch("apps.notifications.services.deliver_sms", return_value={"success": True}):
            self.client.post(self.lookup_url, {
                "franchise_number": self.franchise.franchise_number,
                "last_name_confirm": "Santos",
            })

        session = self.client.session
        challenge = session["renewal_otp_challenge"]
        session["renewal_otp_challenge"] = {
            **challenge,
            "code_hash": make_password("123456"),
        }
        session.save()
        self.client.post(self.verify_url, {"code": "123456"})

        other_holder = FranchiseHolder.objects.create(
            first_name="Ana",
            last_name="Reyes",
            address="Baguio City",
            contact_number="09179999999",
        )
        other_vehicle = Vehicle.objects.create(
            plate_number="OTP-5678",
            engine_number="OTP-ENG-2",
            chassis_number="OTP-CHS-2",
            make="Honda",
            model="TMX",
            color="Blue",
        )
        other_franchise = Franchise.objects.create(
            franchise_number="TRI-OTP-002",
            holder=other_holder,
            vehicle=other_vehicle,
            date_issued=date(2025, 1, 1),
            expiration_date=date(2027, 1, 1),
        )
        other_renewal_url = reverse(
            "applications:renewal_form", args=[other_franchise.franchise_number]
        )

        self.assertRedirects(self.client.get(other_renewal_url), self.lookup_url)

    def test_invalid_otp_does_not_grant_access(self):
        with (
            patch("apps.notifications.services.deliver_sms", return_value={"success": True}),
            patch("django.utils.crypto.get_random_string", return_value="123456"),
        ):
            self.client.post(self.lookup_url, {
                "franchise_number": self.franchise.franchise_number,
                "last_name_confirm": "Santos",
            })

        response = self.client.post(self.verify_url, {"code": "000000"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid verification code")
        self.assertRedirects(self.client.get(self.renewal_url), self.lookup_url)

    def test_failed_sms_delivery_does_not_grant_renewal_access(self):
        with patch("apps.notifications.services.deliver_sms", return_value={"success": False}):
            response = self.client.post(self.lookup_url, {
                "franchise_number": self.franchise.franchise_number,
                "last_name_confirm": "Santos",
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "verification code right now")
        self.assertRedirects(self.client.get(self.renewal_url), self.lookup_url)


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

    def test_exact_vehicle_can_be_reused_after_all_previous_applications_are_terminal(self):
        vehicle = Vehicle.objects.get(plate_number="DUP-0001")
        applicant = Applicant.objects.create(
            first_name="Alex", last_name="Applicant", address="Bontoc",
            contact_number="09171234567",
        )
        Application.objects.create(
            applicant=applicant,
            vehicle=vehicle,
            type=Application.ApplicationType.NEW,
            status=Application.Status.CANCELLED,
        )

        form = VehicleForm(data={
            "plate_number": "DUP-0001", "engine_number": "ENGDUP", "chassis_number": "CHSDUP",
            "make": "Honda", "model": "TMX", "color": "Black",
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(form.existing_vehicle, vehicle)

    def test_exact_vehicle_cannot_be_reused_while_application_is_pending(self):
        vehicle = Vehicle.objects.get(plate_number="DUP-0001")
        applicant = Applicant.objects.create(
            first_name="Alex", last_name="Applicant", address="Bontoc",
            contact_number="09171234567",
        )
        Application.objects.create(
            applicant=applicant,
            vehicle=vehicle,
            type=Application.ApplicationType.NEW,
            status=Application.Status.SUBMITTED,
        )

        form = VehicleForm(data={
            "plate_number": "DUP-0001", "engine_number": "ENGDUP", "chassis_number": "CHSDUP",
            "make": "Honda", "model": "TMX", "color": "Black",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("plate_number", form.errors)


class PolicyAcceptanceFormTests(TestCase):
    def test_policy_acceptance_is_required(self):
        form = PolicyAcceptanceForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("accepted", form.errors)

    def test_checked_policy_acceptance_is_valid(self):
        form = PolicyAcceptanceForm(data={"accepted": "on"})
        self.assertTrue(form.is_valid())


class ApplicationValidationFeedbackTests(TestCase):
    def test_new_application_is_blocked_for_person_with_pending_application(self):
        applicant = Applicant.objects.create(
            first_name="Alex",
            last_name="Applicant",
            address="Bontoc",
            contact_number="09171234567",
        )
        Application.objects.create(
            applicant=applicant,
            type=Application.ApplicationType.NEW,
            status=Application.Status.UNDER_REVIEW,
        )
        data = {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09178889999",
            "email": "",
            "plate_number": "PEND-1001",
            "engine_number": "PEND-ENG-1001",
            "chassis_number": "PEND-CHS-1001",
            "make": "Honda",
            "model": "TMX",
            "color": "Red",
            "accepted": "on",
        }
        requirements = DocumentRequirement.objects.filter(
            active=True,
            required=True,
            application_type__in=[
                DocumentRequirement.ApplicationType.NEW,
                DocumentRequirement.ApplicationType.BOTH,
            ],
        )
        for requirement in requirements:
            data[f"document_{requirement.id}"] = SimpleUploadedFile(
                f"document-{requirement.id}.pdf",
                b"%PDF-1.4 test document",
                content_type="application/pdf",
            )

        response = self.client.post(reverse("applications:new"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You already have an application or renewal in progress.")
        self.assertEqual(Application.objects.count(), 1)

    def test_rejected_application_allows_new_application_with_same_vehicle(self):
        vehicle = Vehicle.objects.create(
            plate_number="REJ-1001",
            engine_number="REJ-ENG-1001",
            chassis_number="REJ-CHS-1001",
            make="Honda",
            model="TMX",
            color="Red",
        )
        applicant = Applicant.objects.create(
            first_name="Alex",
            last_name="Applicant",
            address="Bontoc",
            contact_number="09171234567",
        )
        Application.objects.create(
            applicant=applicant,
            vehicle=vehicle,
            type=Application.ApplicationType.NEW,
            status=Application.Status.REJECTED,
        )
        data = {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
            "plate_number": "REJ-1001",
            "engine_number": "REJ-ENG-1001",
            "chassis_number": "REJ-CHS-1001",
            "make": "Honda",
            "model": "TMX",
            "color": "Red",
            "accepted": "on",
        }
        requirements = DocumentRequirement.objects.filter(
            active=True,
            required=True,
            application_type__in=[
                DocumentRequirement.ApplicationType.NEW,
                DocumentRequirement.ApplicationType.BOTH,
            ],
        )
        for requirement in requirements:
            data[f"document_{requirement.id}"] = SimpleUploadedFile(
                f"document-{requirement.id}.pdf",
                b"%PDF-1.4 test document",
                content_type="application/pdf",
            )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse("applications:new"), data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Application.objects.count(), 2)
        self.assertEqual(
            Application.objects.exclude(applicant=applicant).get().vehicle,
            vehicle,
        )

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
        data = {
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
        }
        requirements = DocumentRequirement.objects.filter(
            active=True,
            required=True,
            application_type__in=[
                DocumentRequirement.ApplicationType.NEW,
                DocumentRequirement.ApplicationType.BOTH,
            ],
        )
        for requirement in requirements:
            data[f"document_{requirement.id}"] = SimpleUploadedFile(
                f"document-{requirement.id}.pdf",
                b"%PDF-1.4 test document",
                content_type="application/pdf",
            )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse("applications:new"), data)

        self.assertEqual(response.status_code, 302)
        application = Application.objects.get()
        self.assertIsNotNone(application.policy_accepted_at)
        self.assertEqual(application.policy_version_accepted, "2026-10-18")
        self.assertEqual(application.documents.count(), requirements.count())


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


class StaffApplicationDocumentLinkTests(TestCase):
    def test_document_link_uses_root_relative_media_url(self):
        applicant = Applicant.objects.create(
            first_name="Taylor",
            last_name="Applicant",
            address="Bontoc",
            contact_number="09171234567",
        )
        application = Application.objects.create(
            applicant=applicant,
            type=Application.ApplicationType.NEW,
        )
        requirement = DocumentRequirement.objects.create(name="Valid ID")
        staff_user = User.objects.create_user(
            username="document_reviewer",
            password="test-password",
            role=User.Role.STAFF,
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            file_name = f"applications/{application.id}/req_{requirement.id}/id.pdf"
            document = ApplicationDocument.objects.create(
                application=application,
                document_requirement=requirement,
                uploaded_file=file_name,
            )
            file_path = Path(media_root) / document.uploaded_file.name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"%PDF-1.4 test document")
            self.client.force_login(staff_user)
            response = self.client.get(
                reverse("staff_applications:detail", kwargs={"reference_code": application.reference_code})
            )
            file_response = self.client.get(document.uploaded_file.url)
            file_content = b"".join(file_response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="/media/{document.uploaded_file.name}"')
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(file_content, b"%PDF-1.4 test document")


class ApprovedApplicationFranchiseNumberGateTests(TestCase):
    def setUp(self):
        self.applicant = Applicant.objects.create(
            first_name="Jordan",
            last_name="Applicant",
            address="Bontoc",
            contact_number="09171234567",
        )
        self.vehicle = Vehicle.objects.create(
            plate_number="GATE-1001",
            engine_number="GATE-ENG-1001",
            chassis_number="GATE-CHS-1001",
            make="Honda",
            model="TMX",
            color="Red",
        )
        self.application = Application.objects.create(
            applicant=self.applicant,
            vehicle=self.vehicle,
            type=Application.ApplicationType.NEW,
            status=Application.Status.APPROVED,
        )
        self.staff = User.objects.create_user(
            username="franchise_gate_staff",
            password="test-password",
            role=User.Role.STAFF,
        )
        self.client.force_login(self.staff)
        self.approved_list_url = reverse("staff_applications:approved_list")
        self.send_message_url = reverse(
            "notifications:send_to_applicant",
            kwargs={"reference_code": self.application.reference_code},
        )
        self.confirm_number_url = reverse(
            "staff_applications:confirm_franchise_number",
            kwargs={"reference_code": self.application.reference_code},
        )

    def test_franchise_number_is_shown_only_after_successful_message_delivery(self):
        response = self.client.get(self.approved_list_url)
        self.assertContains(response, 'class="btn btn-sm btn-outline-secondary js-send-message"')
        self.assertNotContains(response, 'class="btn btn-sm btn-accent js-enter-franchise"')

        with patch(
            "apps.notifications.views.notify_applicant",
            return_value=[Notification(
                channel=Notification.Channel.SMS,
                delivery_status=Notification.DeliveryStatus.SENT,
            )],
        ):
            response = self.client.post(self.send_message_url, {"message": "Your application is approved."})

        self.assertRedirects(response, self.approved_list_url)
        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.franchise_number_unlocked_at)

        response = self.client.get(self.approved_list_url)
        self.assertNotContains(response, 'class="btn btn-sm btn-outline-secondary js-send-message"')
        self.assertContains(response, 'class="btn btn-sm btn-accent js-enter-franchise"')

        response = self.client.post(self.confirm_number_url, {"franchise_number": "TRI-GATE-1001"})
        self.assertRedirects(response, self.approved_list_url)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.COMPLETED)
        self.assertEqual(self.application.franchise.franchise_number, "TRI-GATE-1001")

    def test_failed_message_delivery_does_not_unlock_franchise_number(self):
        with patch(
            "apps.notifications.views.notify_applicant",
            return_value=[Notification(
                channel=Notification.Channel.SMS,
                delivery_status=Notification.DeliveryStatus.FAILED,
            )],
        ):
            self.client.post(self.send_message_url, {"message": "Your application is approved."})

        self.application.refresh_from_db()
        self.assertIsNone(self.application.franchise_number_unlocked_at)

        response = self.client.get(self.approved_list_url)
        self.assertContains(response, 'class="btn btn-sm btn-outline-secondary js-send-message"')
        self.assertNotContains(response, 'class="btn btn-sm btn-accent js-enter-franchise"')

        response = self.client.post(self.confirm_number_url, {"franchise_number": "TRI-GATE-1001"})
        self.assertRedirects(response, self.approved_list_url)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.APPROVED)
        self.assertFalse(Franchise.objects.filter(franchise_number="TRI-GATE-1001").exists())