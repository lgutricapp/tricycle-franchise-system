import csv
import io
from datetime import datetime
from xml.sax.saxutils import escape
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone

from apps.applications.models import Application
from apps.franchises.models import Franchise
from apps.franchises.services import (
    current_franchises_queryset,
    refresh_franchise_statuses,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.pdfgen import canvas


REPORT_TYPE_NEW_APPLICATIONS = "new_applications"
REPORT_TYPE_RENEWALS = "renewals"
REPORT_TYPE_STATUS_SUMMARY = "status_summary"
REPORT_TYPE_FRANCHISE_REGISTRY = "franchise_registry"
REPORT_TYPE_TRICYCLE_REGISTRATION = "tricycle_registration"
REPORT_TYPE_DRIVER_INFORMATION = "driver_information"
REPORT_TYPE_PERMIT_APPLICATIONS = "permit_applications"
REPORT_TYPE_PERMIT_EXPIRATION = "permit_expiration"
REPORT_TYPE_ACTIVE_UNITS = "active_units"
REPORT_TYPE_PENDING_APPLICATIONS = "pending_applications"
REPORT_TYPE_EXPIRED_PERMITS = "expired_permits"

REPORT_TYPE_CHOICES = [
    (REPORT_TYPE_NEW_APPLICATIONS, "New Franchise Applications"),
    (REPORT_TYPE_RENEWALS, "Franchise Renewals"),
    (REPORT_TYPE_STATUS_SUMMARY, "Application Status Summary"),
    (REPORT_TYPE_FRANCHISE_REGISTRY, "Franchise Registry / Active Franchises"),
    (REPORT_TYPE_TRICYCLE_REGISTRATION, "Tricycle Registration Report"),
    (REPORT_TYPE_DRIVER_INFORMATION, "Driver Information Report"),
    (REPORT_TYPE_PERMIT_APPLICATIONS, "Permit Application Report"),
    (REPORT_TYPE_PERMIT_EXPIRATION, "Permit Expiration Report"),
    (REPORT_TYPE_ACTIVE_UNITS, "Active Unit Report"),
    (REPORT_TYPE_PENDING_APPLICATIONS, "Pending Application Report"),
    (REPORT_TYPE_EXPIRED_PERMITS, "Expired Permit Report"),
]

REPORT_TITLES = {
    REPORT_TYPE_NEW_APPLICATIONS: "New Franchise Applications Report",
    REPORT_TYPE_RENEWALS: "Franchise Renewals Report",
    REPORT_TYPE_STATUS_SUMMARY: "Application Status Summary Report",
    REPORT_TYPE_FRANCHISE_REGISTRY: "Franchise Registry Report",
    REPORT_TYPE_TRICYCLE_REGISTRATION: "Tricycle Registration Report",
    REPORT_TYPE_DRIVER_INFORMATION: "Driver Information Report",
    REPORT_TYPE_PERMIT_APPLICATIONS: "Permit Application Report",
    REPORT_TYPE_PERMIT_EXPIRATION: "Permit Expiration Report",
    REPORT_TYPE_ACTIVE_UNITS: "Active Unit Report",
    REPORT_TYPE_PENDING_APPLICATIONS: "Pending Application Report",
    REPORT_TYPE_EXPIRED_PERMITS: "Expired Permit Report",
}

FRANCHISE_REPORT_TYPES = {
    REPORT_TYPE_FRANCHISE_REGISTRY,
    REPORT_TYPE_TRICYCLE_REGISTRATION,
    REPORT_TYPE_DRIVER_INFORMATION,
    REPORT_TYPE_PERMIT_EXPIRATION,
    REPORT_TYPE_ACTIVE_UNITS,
    REPORT_TYPE_EXPIRED_PERMITS,
}

PENDING_APPLICATION_STATUSES = [
    Application.Status.SUBMITTED,
    Application.Status.UNDER_REVIEW,
    Application.Status.REVISION_REQUIRED,
    Application.Status.RESUBMITTED,
    Application.Status.FOR_APPROVAL,
]


def parse_date(date_str):
    """Parse date from YYYY-MM-DD string, return date object or None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def validate_report_filters(report_type, start_date_str, end_date_str, status=""):
    """
    Validate filter parameters.
    Prevents end_date from being earlier than start_date.
    Returns: (start_date, end_date, error_message)
    """
    valid_types = [c[0] for c in REPORT_TYPE_CHOICES]
    if report_type not in valid_types:
        return None, None, "Invalid report type selected."

    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    if start_date_str and not start_date:
        return None, None, "Invalid start date format. Please use YYYY-MM-DD."
    if end_date_str and not end_date:
        return None, None, "Invalid end date format. Please use YYYY-MM-DD."

    if start_date and end_date and end_date < start_date:
        return start_date, end_date, "End date cannot be earlier than start date."

    return start_date, end_date, None


def get_report_data(report_type, start_date=None, end_date=None, status=""):
    """
    Fetch and assemble data for the specified report type and date range.
    Uses only existing fields from the database.
    """
    if report_type == REPORT_TYPE_NEW_APPLICATIONS:
        return _get_application_report_data(
            Application.ApplicationType.NEW,
            report_type,
            REPORT_TITLES[REPORT_TYPE_NEW_APPLICATIONS],
            start_date,
            end_date,
            status,
        )

    elif report_type == REPORT_TYPE_RENEWALS:
        return _get_application_report_data(
            Application.ApplicationType.RENEWAL,
            report_type,
            REPORT_TITLES[REPORT_TYPE_RENEWALS],
            start_date,
            end_date,
            status,
        )

    elif report_type == REPORT_TYPE_STATUS_SUMMARY:
        return _get_status_summary_report_data(start_date, end_date)

    elif report_type == REPORT_TYPE_FRANCHISE_REGISTRY:
        return _get_franchise_registry_report_data(start_date, end_date, status)

    elif report_type == REPORT_TYPE_TRICYCLE_REGISTRATION:
        return _get_franchise_detail_report_data(
            report_type, start_date, end_date, status, "registration"
        )

    elif report_type == REPORT_TYPE_DRIVER_INFORMATION:
        return _get_franchise_detail_report_data(
            report_type, start_date, end_date, status, "driver"
        )

    elif report_type == REPORT_TYPE_PERMIT_APPLICATIONS:
        return _get_all_application_report_data(start_date, end_date, status)

    elif report_type == REPORT_TYPE_PERMIT_EXPIRATION:
        return _get_permit_report_data(
            report_type, start_date, end_date, status, "expiration"
        )

    elif report_type == REPORT_TYPE_ACTIVE_UNITS:
        return _get_permit_report_data(
            report_type, start_date, end_date, status, "active"
        )

    elif report_type == REPORT_TYPE_PENDING_APPLICATIONS:
        return _get_all_application_report_data(
            start_date, end_date, status, pending_only=True
        )

    elif report_type == REPORT_TYPE_EXPIRED_PERMITS:
        return _get_permit_report_data(
            report_type, start_date, end_date, status, "expired"
        )

    raise ValueError(f"Unknown report type: {report_type}")


def _report_result(report_type, title, start_date, end_date, status, rows, headers):
    status_choices = Franchise.Status.choices if report_type in FRANCHISE_REPORT_TYPES else Application.Status.choices
    return {
        "report_type": report_type,
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "status_display": dict(status_choices).get(status, "All Statuses") if status else "All Statuses",
        "headers": headers,
        "rows": rows,
        "count": len(rows),
        "is_summary": False,
    }


def _get_all_application_report_data(start_date, end_date, status, pending_only=False):
    qs = (
        Application.objects.select_related("applicant", "franchise", "vehicle")
        .annotate(effective_date=Coalesce("submitted_at", "created_at"))
    )
    if pending_only:
        qs = qs.filter(status__in=PENDING_APPLICATION_STATUSES)
    if start_date:
        qs = qs.filter(effective_date__date__gte=start_date)
    if end_date:
        qs = qs.filter(effective_date__date__lte=end_date)
    if status:
        qs = qs.filter(status=status)

    rows = []
    for application in qs.order_by("-effective_date"):
        rows.append({
            "cells": [
                application.reference_code,
                application.applicant.full_name,
                application.get_type_display(),
                application.submitted_at.strftime("%Y-%m-%d %H:%M")
                if application.submitted_at
                else f"{application.created_at.strftime('%Y-%m-%d')} (Draft)",
                application.get_status_display(),
                application.franchise.franchise_number if application.franchise else "—",
                application.vehicle.plate_number if application.vehicle else "—",
                application.applicant.contact_number or "—",
            ],
        })

    report_type = (
        REPORT_TYPE_PENDING_APPLICATIONS if pending_only else REPORT_TYPE_PERMIT_APPLICATIONS
    )
    return _report_result(
        report_type,
        REPORT_TITLES[report_type],
        start_date,
        end_date,
        status,
        rows,
        [
            "Reference #", "Applicant Name", "Application Type", "Submission Date",
            "Status", "Permit #", "Plate #", "Contact Number",
        ],
    )


def _franchise_queryset(start_date, end_date, status):
    refresh_franchise_statuses()
    qs = Franchise.objects.select_related("holder", "vehicle")
    if start_date:
        qs = qs.filter(date_issued__gte=start_date)
    if end_date:
        qs = qs.filter(date_issued__lte=end_date)
    if status:
        qs = qs.filter(status=status)
    return qs


def _get_franchise_detail_report_data(report_type, start_date, end_date, status, detail):
    qs = _franchise_queryset(start_date, end_date, status).order_by(
        "holder__full_name", "franchise_number"
    )
    if detail == "registration":
        headers = [
            "Permit #", "Registered Driver", "Plate #", "Engine #", "Chassis #",
            "Make / Model", "Color", "Date Issued", "Expiration Date",
        ]
        rows = [{
            "cells": [
                franchise.franchise_number,
                franchise.holder.full_name,
                franchise.vehicle.plate_number,
                franchise.vehicle.engine_number,
                franchise.vehicle.chassis_number,
                f"{franchise.vehicle.make} {franchise.vehicle.model}".strip(),
                franchise.vehicle.color,
                franchise.date_issued.strftime("%Y-%m-%d"),
                franchise.expiration_date.strftime("%Y-%m-%d"),
            ],
        } for franchise in qs]
    else:
        headers = [
            "Driver Name", "Address", "Contact Number", "Email", "Permit #",
            "Plate #", "Permit Expiration", "Status",
        ]
        rows = [{
            "cells": [
                franchise.holder.full_name,
                franchise.holder.address,
                franchise.holder.contact_number,
                franchise.holder.email or "—",
                franchise.franchise_number,
                franchise.vehicle.plate_number,
                franchise.expiration_date.strftime("%Y-%m-%d"),
                franchise.get_status_display(),
            ],
        } for franchise in qs]
    return _report_result(
        report_type, REPORT_TITLES[report_type], start_date, end_date,
        status, rows, headers,
    )


def _get_permit_report_data(report_type, start_date, end_date, status, permit_filter):
    today = timezone.localdate()
    qs = Franchise.objects.select_related("holder", "vehicle")
    if permit_filter == "expiration":
        qs = qs.filter(expiration_date__gte=today).exclude(
            status=Franchise.Status.REVOKED
        )
        if start_date:
            qs = qs.filter(expiration_date__gte=start_date)
        if end_date:
            qs = qs.filter(expiration_date__lte=end_date)
    elif permit_filter == "active":
        refresh_franchise_statuses()
        qs = current_franchises_queryset().select_related("holder", "vehicle")
        if start_date:
            qs = qs.filter(date_issued__gte=start_date)
        if end_date:
            qs = qs.filter(date_issued__lte=end_date)
    else:
        qs = qs.filter(expiration_date__lt=today).exclude(status=Franchise.Status.REVOKED)
        if start_date:
            qs = qs.filter(expiration_date__gte=start_date)
        if end_date:
            qs = qs.filter(expiration_date__lte=end_date)
    if status:
        qs = qs.filter(status=status)

    rows = [{
        "cells": [
            franchise.franchise_number,
            franchise.holder.full_name,
            franchise.vehicle.plate_number,
            f"{franchise.vehicle.make} {franchise.vehicle.model}".strip(),
            franchise.date_issued.strftime("%Y-%m-%d"),
            franchise.expiration_date.strftime("%Y-%m-%d"),
            franchise.get_status_display(),
            franchise.holder.contact_number,
        ],
    } for franchise in qs.order_by("expiration_date", "franchise_number")]
    return _report_result(
        report_type, REPORT_TITLES[report_type], start_date, end_date,
        status, rows,
        [
            "Permit #", "Driver Name", "Plate #", "Make / Model",
            "Date Issued", "Expiration Date", "Status", "Contact Number",
        ],
    )


def _get_application_report_data(app_type, report_type, title, start_date, end_date, status):
    """Fetch applications (new or renewal) within date range and status."""
    qs = (
        Application.objects.filter(type=app_type)
        .select_related("applicant", "franchise", "vehicle")
        .annotate(effective_date=Coalesce("submitted_at", "created_at"))
    )

    if start_date:
        qs = qs.filter(effective_date__date__gte=start_date)
    if end_date:
        qs = qs.filter(effective_date__date__lte=end_date)
    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by("-effective_date")

    headers = [
        "Reference #",
        "Applicant Name",
        "Franchise #",
        "Application Type",
        "Submission Date",
        "Current Status",
        "Plate #",
        "Contact Number",
    ]

    rows = []
    for app in qs:
        sub_date = (
            app.submitted_at.strftime("%Y-%m-%d %H:%M")
            if app.submitted_at
            else f"{app.created_at.strftime('%Y-%m-%d')} (Draft)"
        )
        rows.append({
            "reference_number": app.reference_code,
            "applicant_name": app.applicant.full_name,
            "franchise_number": app.franchise.franchise_number if app.franchise else "—",
            "application_type": app.get_type_display(),
            "submission_date": sub_date,
            "status": app.status,
            "status_display": app.get_status_display(),
            "plate_number": app.vehicle.plate_number if app.vehicle else "—",
            "contact_number": app.applicant.contact_number or "—",
        })

    return {
        "report_type": report_type,
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "status_display": dict(Application.Status.choices).get(status, "All Statuses") if status else "All Statuses",
        "headers": headers,
        "rows": rows,
        "count": len(rows),
        "is_summary": False,
    }


def _get_status_summary_report_data(start_date, end_date):
    """
    Generate status summary counts by aggregating applications under each actual status.
    Uses exact statuses from Application.Status.choices without renaming.
    """
    qs = Application.objects.annotate(effective_date=Coalesce("submitted_at", "created_at"))

    if start_date:
        qs = qs.filter(effective_date__date__gte=start_date)
    if end_date:
        qs = qs.filter(effective_date__date__lte=end_date)

    total_applications = qs.count()

    headers = [
        "Application Status",
        "New Applications",
        "Renewal Applications",
        "Total Applications",
        "Percentage (%)",
    ]

    rows = []
    total_new = 0
    total_renewals = 0

    for status_code, status_name in Application.Status.choices:
        count_new = qs.filter(type=Application.ApplicationType.NEW, status=status_code).count()
        count_renewal = qs.filter(type=Application.ApplicationType.RENEWAL, status=status_code).count()
        count_total = count_new + count_renewal

        total_new += count_new
        total_renewals += count_renewal

        pct = round((count_total / total_applications * 100), 1) if total_applications > 0 else 0.0

        rows.append({
            "status_code": status_code,
            "status_name": status_name,
            "new_count": count_new,
            "renewal_count": count_renewal,
            "total_count": count_total,
            "percentage": pct,
        })

    totals = {
        "status_name": "Total",
        "new_count": total_new,
        "renewal_count": total_renewals,
        "total_count": total_applications,
        "percentage": 100.0 if total_applications > 0 else 0.0,
    }

    return {
        "report_type": REPORT_TYPE_STATUS_SUMMARY,
        "title": REPORT_TITLES[REPORT_TYPE_STATUS_SUMMARY],
        "start_date": start_date,
        "end_date": end_date,
        "status": "",
        "status_display": "All Statuses (Aggregated)",
        "headers": headers,
        "rows": rows,
        "totals": totals,
        "count": total_applications,
        "is_summary": True,
    }


def _get_franchise_registry_report_data(start_date, end_date, status):
    """Fetch franchise registry records within date range and status."""
    refresh_franchise_statuses()
    qs = Franchise.objects.select_related("holder", "vehicle")

    if start_date:
        qs = qs.filter(date_issued__gte=start_date)
    if end_date:
        qs = qs.filter(date_issued__lte=end_date)
    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by("-date_issued", "franchise_number")

    headers = [
        "Franchise #",
        "Franchise Holder",
        "Plate #",
        "Make / Model",
        "Date Issued",
        "Expiration Date",
        "Status",
        "Contact Number",
    ]

    rows = []
    for f in qs:
        make_model = f"{f.vehicle.make} {f.vehicle.model}".strip() if f.vehicle else "—"
        rows.append({
            "franchise_number": f.franchise_number,
            "holder_name": f.holder.full_name if f.holder else "—",
            "plate_number": f.vehicle.plate_number if f.vehicle else "—",
            "make_model": make_model or "—",
            "date_issued": f.date_issued.strftime("%Y-%m-%d") if f.date_issued else "—",
            "expiration_date": f.expiration_date.strftime("%Y-%m-%d") if f.expiration_date else "—",
            "status": f.status,
            "status_display": f.get_status_display(),
            "contact_number": f.holder.contact_number if f.holder else "—",
        })

    return {
        "report_type": REPORT_TYPE_FRANCHISE_REGISTRY,
        "title": REPORT_TITLES[REPORT_TYPE_FRANCHISE_REGISTRY],
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "status_display": dict(Franchise.Status.choices).get(status, "All Statuses") if status else "All Statuses",
        "headers": headers,
        "rows": rows,
        "count": len(rows),
        "is_summary": False,
    }


def export_report_csv(report_data):
    """
    Generate downloadable CSV file from report data.
    Includes UTF-8 BOM for spreadsheet compatibility.
    """
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"{report_data['report_type']}_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Write UTF-8 BOM so Excel automatically recognizes encoding
    response.write("\ufeff")
    writer = csv.writer(response)

    # Write CSV Header
    writer.writerow(report_data["headers"])

    # Write Data Rows
    if report_data.get("is_summary"):
        for row in report_data["rows"]:
            writer.writerow([
                row["status_name"],
                row["new_count"],
                row["renewal_count"],
                row["total_count"],
                f"{row['percentage']}%",
            ])
        if "totals" in report_data:
            t = report_data["totals"]
            writer.writerow([
                t["status_name"],
                t["new_count"],
                t["renewal_count"],
                t["total_count"],
                f"{t['percentage']}%",
            ])
    elif report_data["report_type"] in (REPORT_TYPE_NEW_APPLICATIONS, REPORT_TYPE_RENEWALS):
        for row in report_data["rows"]:
            writer.writerow([
                row["reference_number"],
                row["applicant_name"],
                row["franchise_number"],
                row["application_type"],
                row["submission_date"],
                row["status_display"],
                row["plate_number"],
                row["contact_number"],
            ])
    elif report_data["report_type"] == REPORT_TYPE_FRANCHISE_REGISTRY:
        for row in report_data["rows"]:
            writer.writerow([
                row["franchise_number"],
                row["holder_name"],
                row["plate_number"],
                row["make_model"],
                row["date_issued"],
                row["expiration_date"],
                row["status_display"],
                row["contact_number"],
            ])
    else:
        writer.writerows(row["cells"] for row in report_data["rows"])

    return response


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to compute total page count and add running footers with page numbers.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#5B6B7C"))

        # Thin rule above footer
        self.setStrokeColor(colors.HexColor("#DDE3E9"))
        self.setLineWidth(0.75)
        page_width, _ = self._pagesize
        self.line(36, 36, page_width - 36, 36)

        # Footer labels
        left_text = "Republic of the Philippines • Tricycle Franchise Regulatory Board — Official LGU Record"
        right_text = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 22, left_text)
        self.drawRightString(page_width - 36, 22, right_text)

        self.restoreState()


def export_report_pdf(report_data, generated_by="Administrator"):
    """
    Generate downloadable PDF with official LGU layout, repeated table headers,
    date range, generation timestamp, and running page numbers.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    # Custom styles matching system design tokens
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#1B3A6B"),
    )
    gov_header_style = ParagraphStyle(
        "GovHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#4A6288"),
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#142C52"),
    )
    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1F2937"),
    )
    th_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )
    td_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#1F2937"),
    )
    td_bold_style = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#142C52"),
    )
    empty_style = ParagraphStyle(
        "EmptyNotice",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor("#5B6B7C"),
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("REPUBLIC OF THE PHILIPPINES &bull; LOCAL GOVERNMENT UNIT", gov_header_style))
    story.append(Paragraph("OFFICE OF THE TRICYCLE FRANCHISE REGULATORY BOARD", gov_header_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(report_data["title"].upper(), title_style))
    story.append(Spacer(1, 10))

    # 2. Metadata Information Block
    date_range_display = "All Dates"
    if report_data["start_date"] and report_data["end_date"]:
        date_range_display = f"{report_data['start_date'].strftime('%B %d, %Y')} to {report_data['end_date'].strftime('%B %d, %Y')}"
    elif report_data["start_date"]:
        date_range_display = f"From {report_data['start_date'].strftime('%B %d, %Y')} onward"
    elif report_data["end_date"]:
        date_range_display = f"Up to {report_data['end_date'].strftime('%B %d, %Y')}"

    generation_time = timezone.now().strftime("%B %d, %Y at %I:%M %p")

    meta_table_data = [
        [
            Paragraph("<b>Date Range:</b>", meta_label_style),
            Paragraph(date_range_display, meta_val_style),
            Paragraph("<b>Generated On:</b>", meta_label_style),
            Paragraph(generation_time, meta_val_style),
        ],
        [
            Paragraph("<b>Filter Applied:</b>", meta_label_style),
            Paragraph(report_data.get("status_display", "All"), meta_val_style),
            Paragraph("<b>Generated By:</b>", meta_label_style),
            Paragraph(str(generated_by), meta_val_style),
        ],
        [
            Paragraph("<b>Total Records:</b>", meta_label_style),
            Paragraph(f"{report_data['count']} record(s)", meta_val_style),
            Paragraph("", meta_label_style),
            Paragraph("", meta_val_style),
        ],
    ]

    meta_table = Table(meta_table_data, colWidths=[90, 260, 90, 280])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F8")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#DDE3E9")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EAEFF4")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # 3. Results Table or Clear Empty State Message
    if report_data["count"] == 0 and not report_data.get("is_summary"):
        empty_box = Table(
            [[Paragraph(
                "<b>No matching records found.</b><br/>"
                "There are no records matching the selected date range and filter criteria in the system.",
                empty_style
            )]],
            colWidths=[720],
        )
        empty_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#DDE3E9")),
            ("TOPPADDING", (0, 0), (-1, -1), 24),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 24),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(empty_box)
    else:
        # Build table rows with wrapped Paragraph cells
        table_data = []

        # Headers
        table_data.append([Paragraph(h, th_style) for h in report_data["headers"]])

        if report_data.get("is_summary"):
            col_widths = [200, 130, 130, 130, 130]
            for row in report_data["rows"]:
                table_data.append([
                    Paragraph(row["status_name"], td_bold_style),
                    Paragraph(str(row["new_count"]), td_style),
                    Paragraph(str(row["renewal_count"]), td_style),
                    Paragraph(str(row["total_count"]), td_style),
                    Paragraph(f"{row['percentage']}%", td_style),
                ])
            if "totals" in report_data:
                t = report_data["totals"]
                table_data.append([
                    Paragraph(f"<b>{t['status_name']}</b>", td_bold_style),
                    Paragraph(f"<b>{t['new_count']}</b>", td_bold_style),
                    Paragraph(f"<b>{t['renewal_count']}</b>", td_bold_style),
                    Paragraph(f"<b>{t['total_count']}</b>", td_bold_style),
                    Paragraph(f"<b>{t['percentage']}%</b>", td_bold_style),
                ])
        elif report_data["report_type"] in (REPORT_TYPE_NEW_APPLICATIONS, REPORT_TYPE_RENEWALS):
            col_widths = [75, 145, 75, 75, 95, 85, 75, 95]
            for row in report_data["rows"]:
                table_data.append([
                    Paragraph(row["reference_number"], td_bold_style),
                    Paragraph(row["applicant_name"], td_style),
                    Paragraph(row["franchise_number"], td_style),
                    Paragraph(row["application_type"], td_style),
                    Paragraph(row["submission_date"], td_style),
                    Paragraph(row["status_display"], td_style),
                    Paragraph(row["plate_number"], td_style),
                    Paragraph(row["contact_number"], td_style),
                ])
        elif report_data["report_type"] == REPORT_TYPE_FRANCHISE_REGISTRY:
            col_widths = [95, 155, 75, 105, 80, 80, 65, 65]
            for row in report_data["rows"]:
                table_data.append([
                    Paragraph(row["franchise_number"], td_bold_style),
                    Paragraph(row["holder_name"], td_style),
                    Paragraph(row["plate_number"], td_style),
                    Paragraph(row["make_model"], td_style),
                    Paragraph(row["date_issued"], td_style),
                    Paragraph(row["expiration_date"], td_style),
                    Paragraph(row["status_display"], td_style),
                    Paragraph(row["contact_number"], td_style),
                ])
        else:
            col_widths = [720 / len(report_data["headers"])] * len(report_data["headers"])
            for row in report_data["rows"]:
                table_data.append([
                    Paragraph(escape(str(value)), td_style)
                    for value in row["cells"]
                ])

        results_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table_style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A6B")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE3E9")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]

        # Alternating background colors for rows
        num_rows = len(table_data)
        for r_idx in range(1, num_rows):
            if r_idx % 2 == 0:
                table_style_commands.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))
            else:
                table_style_commands.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.white))

        # Highlight totals row for summary report
        if report_data.get("is_summary") and "totals" in report_data:
            last_idx = num_rows - 1
            table_style_commands.extend([
                ("BACKGROUND", (0, last_idx), (-1, last_idx), colors.HexColor("#E8EEF5")),
                ("LINEABOVE", (0, last_idx), (-1, last_idx), 1.25, colors.HexColor("#1B3A6B")),
            ])

        results_table.setStyle(TableStyle(table_style_commands))
        story.append(results_table)

    doc.build(story, canvasmaker=NumberedCanvas)

    filename = f"{report_data['report_type']}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
