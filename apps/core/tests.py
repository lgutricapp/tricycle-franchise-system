import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.applicants.models import Applicant
from apps.applications.models import Application
from apps.core.services import get_monthly_applications_data, get_available_chart_years
from apps.franchises.models import Vehicle


class MonthlyApplicationsDataServiceTests(TestCase):
    def setUp(self):
        self.applicant = Applicant.objects.create(
            first_name="Juan",
            last_name="Dela Cruz",
            address="123 Rizal St",
            contact_number="09171234567",
        )
        self.vehicle = Vehicle.objects.create(
            plate_number="TR-9001",
            engine_number="ENG-9001",
            chassis_number="CHS-9001",
            make="Kawasaki",
            model="Barako 175",
            color="Blue",
        )

    def test_empty_database_returns_continuous_12_months(self):
        data = get_monthly_applications_data("last_12_months")
        self.assertEqual(len(data["labels"]), 12)
        self.assertEqual(len(data["new_applications"]), 12)
        self.assertEqual(len(data["renewals"]), 12)
        self.assertEqual(data["new_applications"], [0] * 12)
        self.assertEqual(data["renewals"], [0] * 12)
        self.assertEqual(data["summary"]["total_new"], 0)
        self.assertEqual(data["summary"]["total_renewals"], 0)
        self.assertEqual(data["summary"]["total_overall"], 0)

    def test_counts_new_and_renewals_separately(self):
        now = timezone.now()
        # Create 2 new applications and 1 renewal in current month
        Application.objects.create(
            applicant=self.applicant,
            vehicle=self.vehicle,
            type=Application.ApplicationType.NEW,
            submitted_at=now,
        )
        Application.objects.create(
            applicant=self.applicant,
            vehicle=self.vehicle,
            type=Application.ApplicationType.NEW,
            submitted_at=now,
        )
        Application.objects.create(
            applicant=self.applicant,
            vehicle=self.vehicle,
            type=Application.ApplicationType.RENEWAL,
            submitted_at=now,
        )

        data = get_monthly_applications_data("last_12_months")
        self.assertEqual(len(data["labels"]), 12)
        # The last element in the 12-month array corresponds to the current month
        self.assertEqual(data["new_applications"][-1], 2)
        self.assertEqual(data["renewals"][-1], 1)
        self.assertEqual(data["summary"]["total_new"], 2)
        self.assertEqual(data["summary"]["total_renewals"], 1)
        self.assertEqual(data["summary"]["total_overall"], 3)

    def test_coalesces_submitted_at_and_created_at(self):
        # Create an application without submitted_at (uses created_at)
        app = Application.objects.create(
            applicant=self.applicant,
            vehicle=self.vehicle,
            type=Application.ApplicationType.NEW,
            submitted_at=None,
        )
        data = get_monthly_applications_data("last_12_months")
        self.assertGreaterEqual(data["new_applications"][-1], 1)

    def test_year_filter_returns_full_calendar_year(self):
        today = timezone.localdate()
        target_year = today.year
        data = get_monthly_applications_data("year", year=target_year)
        self.assertEqual(len(data["labels"]), 12)
        self.assertEqual(data["year"], target_year)
        expected_first = datetime.date(target_year, 1, 1).strftime("%b %Y")
        expected_last = datetime.date(target_year, 12, 1).strftime("%b %Y")
        self.assertEqual(data["labels"][0], expected_first)
        self.assertEqual(data["labels"][-1], expected_last)

    def test_get_available_chart_years(self):
        years = get_available_chart_years()
        today = timezone.localdate()
        self.assertIn(today.year, years)
        self.assertEqual(years, sorted(years, reverse=True))


class DashboardViewAndChartEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff_member", password="password123", role=User.Role.STAFF
        )
        self.reviewer_user = User.objects.create_user(
            username="reviewer_member", password="password123", role=User.Role.REVIEWER
        )
        self.non_staff_user = User.objects.create_user(
            username="regular_user", password="password123", role="PUBLIC_USER"
        )
        self.dashboard_url = reverse("core:dashboard")
        self.chart_data_url = reverse("core:monthly_applications_data")

    def test_anonymous_redirected_to_login(self):
        res_dash = self.client.get(self.dashboard_url)
        self.assertEqual(res_dash.status_code, 302)

        res_api = self.client.get(self.chart_data_url)
        self.assertEqual(res_api.status_code, 302)

    def test_non_staff_user_is_forbidden(self):
        self.client.login(username="regular_user", password="password123")
        res_dash = self.client.get(self.dashboard_url)
        self.assertEqual(res_dash.status_code, 403)

        res_api = self.client.get(self.chart_data_url)
        self.assertEqual(res_api.status_code, 403)

    def test_staff_user_can_access_dashboard_with_chart(self):
        self.client.login(username="staff_member", password="password123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly Applications and Renewals")
        self.assertContains(response, "monthlyApplicationsChart")
        self.assertContains(response, "monthly-chart-initial-data")
        self.assertContains(response, "chartFilterSelect")

    def test_chart_data_endpoint_returns_json(self):
        self.client.login(username="staff_member", password="password123")
        response = self.client.get(self.chart_data_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertIn("labels", data)
        self.assertIn("new_applications", data)
        self.assertIn("renewals", data)
        self.assertIn("summary", data)
        self.assertEqual(len(data["labels"]), 12)

    def test_chart_data_endpoint_with_year_filter(self):
        self.client.login(username="reviewer_member", password="password123")
        today = timezone.localdate()
        response = self.client.get(self.chart_data_url, {"filter_type": f"year_{today.year}"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["filter_type"], "year")
        self.assertEqual(data["year"], today.year)
        self.assertEqual(len(data["labels"]), 12)
