from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.applicants.models import Applicant
from apps.franchises.models import Vehicle
from apps.applications.models import Application

User = get_user_model()


class RoleAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(username="staffer", password="testpass123", role=User.Role.STAFF)
        self.reviewer = User.objects.create_user(username="reviewer1", password="testpass123", role=User.Role.REVIEWER)

        applicant = Applicant.objects.create(full_name="Test Applicant", address="Baguio", contact_number="0917")
        vehicle = Vehicle.objects.create(
            plate_number="XYZ-9999", engine_number="ENG999", chassis_number="CHS999",
            make="Yamaha", model="TMX", color="Blue",
        )
        self.application = Application.objects.create(
            applicant=applicant, vehicle=vehicle,
            type=Application.ApplicationType.NEW, status=Application.Status.SUBMITTED,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("staff_applications:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_staff_can_access_application_queue(self):
        self.client.login(username="staffer", password="testpass123")
        response = self.client.get(reverse("staff_applications:list"))
        self.assertEqual(response.status_code, 200)

    def test_reviewer_can_view_but_cannot_change_application_status(self):
        self.client.login(username="reviewer1", password="testpass123")
        url = reverse("staff_applications:detail", kwargs={"reference_code": self.application.reference_code})

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)  # Reviewer CAN view
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.SUBMITTED)

        self.client.post(url, {
            "action": "transition_status", "new_status": "UNDER_REVIEW", "remarks": "trying to sneak this through",
        })
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.SUBMITTED)  # unchanged — blocked


class LoginRedirectTests(TestCase):
    def test_staff_login_redirects_to_dashboard(self):
        User.objects.create_user(
            username="admin_staff",
            password="test-password",
            role=User.Role.STAFF,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_staff", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("core:dashboard"))

    def test_super_admin_login_redirects_to_dashboard(self):
        User.objects.create_user(
            username="super_admin",
            password="test-password",
            role=User.Role.SUPER_ADMIN,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "super_admin", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("core:dashboard"))

    def test_reviewer_keeps_default_login_redirect(self):
        User.objects.create_user(
            username="reviewer",
            password="test-password",
            role=User.Role.REVIEWER,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "reviewer", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("core:home"))