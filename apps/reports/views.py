from urllib.parse import urlencode
from django.contrib import messages
from django.shortcuts import render
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applications.models import Application
from apps.franchises.models import Franchise

from .services import (
    REPORT_TYPE_NEW_APPLICATIONS,
    REPORT_TYPE_RENEWALS,
    REPORT_TYPE_STATUS_SUMMARY,
    REPORT_TYPE_FRANCHISE_REGISTRY,
    REPORT_TYPE_CHOICES,
    validate_report_filters,
    get_report_data,
    export_report_csv,
    export_report_pdf,
)


@role_required(User.Role.STAFF)
def report_index(request):
    """
    Main report generation view for authorized administrators.
    Allows filtering by report type, date range, and status.
    Supports previewing results and downloading reports as CSV or PDF.
    """
    report_type = request.GET.get("report_type", REPORT_TYPE_NEW_APPLICATIONS).strip()
    start_date_str = request.GET.get("start_date", "").strip()
    end_date_str = request.GET.get("end_date", "").strip()
    status = request.GET.get("status", "").strip()
    export = request.GET.get("export", "").strip().lower()

    # If the user selected an invalid report type, fallback to default
    valid_types = [c[0] for c in REPORT_TYPE_CHOICES]
    if report_type not in valid_types:
        report_type = REPORT_TYPE_NEW_APPLICATIONS

    start_date, end_date, validation_error = validate_report_filters(
        report_type, start_date_str, end_date_str, status
    )

    if validation_error:
        messages.error(request, validation_error)
        # In case of validation error on an export request, return to page with message
        if export in ("csv", "pdf"):
            export = ""

    report_data = None
    if not validation_error:
        report_data = get_report_data(
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )

        # Handle file downloads
        if export == "csv":
            return export_report_csv(report_data)
        elif export == "pdf":
            generated_by = request.user.get_full_name() or request.user.username
            return export_report_pdf(report_data, generated_by=generated_by)

    # Build query string for export links (excluding export param itself)
    query_dict = {}
    if report_type:
        query_dict["report_type"] = report_type
    if start_date_str:
        query_dict["start_date"] = start_date_str
    if end_date_str:
        query_dict["end_date"] = end_date_str
    if status:
        query_dict["status"] = status

    query_string = urlencode(query_dict)

    context = {
        "report_type": report_type,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "status": status,
        "validation_error": validation_error,
        "report_type_choices": REPORT_TYPE_CHOICES,
        "application_status_choices": Application.Status.choices,
        "franchise_status_choices": Franchise.Status.choices,
        "report_data": report_data,
        "query_string": query_string,
    }

    return render(request, "reports/reports.html", context)
