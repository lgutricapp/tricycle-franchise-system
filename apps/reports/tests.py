import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.applicants.models import Applicant
from apps.applications.models import Application
from apps.franchises.models import Franchise, FranchiseHolder, Vehicle
from apps.reports.services import (
    REPORT_TYPE_NEW_APPLICATIONS,
    REPORT_TYPE_RENEWALS,
    REPORT_TYPE_STATUS_SUMMARY,
    REPORT_TYPE_FRANCHISE_REGISTRY,
    get_report_data,
    validate_report_filters,
    export_report_csv,
    export_report_pdf,
)


class ReportAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff_admin", password="password123", role=User.Role.STAFF
        )
        self.super_admin = User.objects.create_superuser(
            username="super_admin", password="password123", role=User.Role.SUPER_ADMIN, email="admin@example.com"
        )
        self.reviewer_user = User.objects.create_user(
            username="reviewer_user", password="password123", role=User.Role.REVIEWER
        )
        self.url = reverse("reports:index")

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_reviewer_is_forbidden(self):
        self.client.login(username="reviewer_user", password="password123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_admin_can_access(self):
        self.client.login(username="staff_admin", password="password123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report Generation")
        self.assertContains(response, "Report Filters")
        self.assertNotContains(response, 'value="DRAFT"')

    def test_super_admin_can_access(self):
        self.client.login(username="super_admin", password="password123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class ReportFilterValidationTests(TestCase):
    def test_valid_filters(self):
        start, end, err = validate_report_filters(
            REPORT_TYPE_NEW_APPLICATIONS, "2026-01-01", "2026-01-31"
        )
        self.assertIsNone(err)
        self.assertEqual(start, datetime.date(2026, 1, 1))
        self.assertEqual(end, datetime.date(2026, 1, 31))

    def test_end_date_earlier_than_start_date(self):
        start, end, err = validate_report_filters(
            REPORT_TYPE_NEW_APPLICATIONS, "2026-02-01", "2026-01-01"
        )
        self.assertEqual(err, "End date cannot be earlier than start date.")

    def test_invalid_date_format(self):
        start, end, err = validate_report_filters(
            REPORT_TYPE_NEW_APPLICATIONS, "not-a-date", "2026-01-01"
        )
        self.assertEqual(err, "Invalid start date format. Please use YYYY-MM-DD.")


class ReportGenerationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff_admin2", password="password123", role=User.Role.STAFF
        )
        self.client.login(username="staff_admin2", password="password123")

        # Create applicants
        self.applicant1 = Applicant.objects.create(
            first_name="Juan",
            last_name="Dela Cruz",
            address="123 Rizal St",
            contact_number="09171234567",
        )
        self.applicant2 = Applicant.objects.create(
            first_name="Maria",
            last_name="Santos",
            address="456 Bonifacio St",
            contact_number="09187654321",
        )

        # Create vehicles
        self.vehicle1 = Vehicle.objects.create(
            plate_number="TR-1001",
            engine_number="ENG-1001",
            chassis_number="CHS-1001",
            make="Kawasaki",
            model="Barako 175",
            color="Blue",
        )
        self.vehicle2 = Vehicle.objects.create(
            plate_number="TR-1002",
            engine_number="ENG-1002",
            chassis_number="CHS-1002",
            make="Bajaj",
            model="CT100",
            color="Red",
        )

        # Create franchise & holder
        self.holder = FranchiseHolder.objects.create(
            first_name="Pedro",
            last_name="Penduko",
            address="789 Mabini St",
            contact_number="09191112222",
        )
        self.franchise = Franchise.objects.create(
            franchise_number="TF-2026-001",
            holder=self.holder,
            vehicle=self.vehicle1,
            status=Franchise.Status.ACTIVE,
            date_issued=datetime.date(2026, 5, 1),
            expiration_date=datetime.date(2027, 5, 1),
        )

        now = timezone.now()
        # Create applications
        self.app_new = Application.objects.create(
            applicant=self.applicant1,
            vehicle=self.vehicle2,
            type=Application.ApplicationType.NEW,
            status=Application.Status.UNDER_REVIEW,
            submitted_at=now,
        )
        self.app_renewal = Application.objects.create(
            applicant=self.applicant2,
            franchise=self.franchise,
            type=Application.ApplicationType.RENEWAL,
            status=Application.Status.APPROVED,
            submitted_at=now,
        )

    def test_new_applications_report_data(self):
        data = get_report_data(REPORT_TYPE_NEW_APPLICATIONS)
        self.assertEqual(data["report_type"], REPORT_TYPE_NEW_APPLICATIONS)
        self.assertGreaterEqual(data["count"], 1)
        ref_codes = [r["reference_number"] for r in data["rows"]]
        self.assertIn(self.app_new.reference_code, ref_codes)
        self.assertNotIn(self.app_renewal.reference_code, ref_codes)

    def test_renewals_report_data(self):
        data = get_report_data(REPORT_TYPE_RENEWALS)
        self.assertEqual(data["report_type"], REPORT_TYPE_RENEWALS)
        self.assertGreaterEqual(data["count"], 1)
        ref_codes = [r["reference_number"] for r in data["rows"]]
        self.assertIn(self.app_renewal.reference_code, ref_codes)
        self.assertNotIn(self.app_new.reference_code, ref_codes)

    def test_status_summary_report_data(self):
        data = get_report_data(REPORT_TYPE_STATUS_SUMMARY)
        self.assertEqual(data["report_type"], REPORT_TYPE_STATUS_SUMMARY)
        self.assertTrue(data["is_summary"])
        # Check that actual statuses exist
        status_names = [r["status_name"] for r in data["rows"]]
        self.assertIn("Under Review", status_names)
        self.assertIn("Approved", status_names)
        self.assertIn("Revision Required", status_names)
        self.assertIn("Rejected", status_names)

        # Totals verify
        self.assertGreaterEqual(data["totals"]["total_count"], 2)

    def test_franchise_registry_report_data(self):
        data = get_report_data(REPORT_TYPE_FRANCHISE_REGISTRY)
        self.assertEqual(data["report_type"], REPORT_TYPE_FRANCHISE_REGISTRY)
        franchise_nums = [r["franchise_number"] for r in data["rows"]]
        self.assertIn("TF-2026-001", franchise_nums)

    def test_csv_export(self):
        url = reverse("reports:index")
        response = self.client.get(url, {"report_type": REPORT_TYPE_NEW_APPLICATIONS, "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        content = response.content.decode("utf-8")
        self.assertIn("Reference #", content)
        self.assertIn(self.app_new.reference_code, content)

    def test_pdf_export(self):
        url = reverse("reports:index")
        response = self.client.get(url, {"report_type": REPORT_TYPE_STATUS_SUMMARY, "export": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_empty_results_pdf(self):
        # Query a future date range with no records
        url = reverse("reports:index")
        response = self.client.get(url, {
            "report_type": REPORT_TYPE_NEW_APPLICATIONS,
            "start_date": "2099-01-01",
            "end_date": "2099-01-31",
            "export": "pdf",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_invalid_date_range_view(self):
        url = reverse("reports:index")
        response = self.client.get(url, {
            "report_type": REPORT_TYPE_NEW_APPLICATIONS,
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End date cannot be earlier than start date.")
