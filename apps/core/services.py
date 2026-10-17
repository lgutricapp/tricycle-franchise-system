import calendar
import datetime
from django.db.models import Count, DateField, Q
from django.db.models.functions import Cast, Coalesce, ExtractMonth, ExtractYear
from django.utils import timezone

from apps.applications.models import Application


def get_available_chart_years():
    """
    Return sorted list of distinct years for which applications exist.
    Always includes the current year so year filtering is always functional.
    """
    today = timezone.localdate() if hasattr(timezone, "localdate") else timezone.now().date()
    qs = (
        Application.objects.annotate(
            ed_date=Cast(Coalesce("submitted_at", "created_at"), output_field=DateField())
        )
        .annotate(yr=ExtractYear("ed_date"))
        .values_list("yr", flat=True)
        .distinct()
    )
    years = {y for y in qs if y is not None}
    years.add(today.year)
    return sorted(years, reverse=True)


def get_monthly_applications_data(filter_type="last_12_months", year=None):
    """
    Calculate monthly counts for new applications and renewals using database-level
    aggregation. Guaranteed to return a continuous sequence of months with 0s for empty periods.

    Returns dict formatted for Chart.js:
    {
        "labels": ["Nov 2025", "Dec 2025", ..., "Oct 2026"],
        "new_applications": [0, ..., 15, 12],
        "renewals": [0, ..., 3, 1],
        "start_label": "Nov 2025",
        "end_label": "Oct 2026",
        "filter_type": "last_12_months",
        "year": None,
        "summary": {
            "total_new": 27,
            "total_renewals": 4,
            "total_overall": 31,
        }
    }
    """
    today = timezone.localdate() if hasattr(timezone, "localdate") else timezone.now().date()
    months = []

    if filter_type == "year" and year:
        try:
            target_year = int(year)
        except (ValueError, TypeError):
            target_year = today.year
        for m in range(1, 13):
            months.append((target_year, m))
        start_date = datetime.date(target_year, 1, 1)
        end_date = datetime.date(target_year, 12, 31)
    else:
        # Default: last 12 continuous months ending at current month
        filter_type = "last_12_months"
        target_year = None
        for i in range(11, -1, -1):
            idx = (today.year * 12 + today.month - 1) - i
            months.append((idx // 12, (idx % 12) + 1))
        start_date = datetime.date(months[0][0], months[0][1], 1)
        last_day = calendar.monthrange(months[-1][0], months[-1][1])[1]
        end_date = datetime.date(months[-1][0], months[-1][1], last_day)

    # Database-level grouping and aggregation in a single query
    qs = (
        Application.objects.annotate(
            ed_date=Cast(Coalesce("submitted_at", "created_at"), output_field=DateField())
        )
        .filter(ed_date__gte=start_date, ed_date__lte=end_date)
        .annotate(yr=ExtractYear("ed_date"), mo=ExtractMonth("ed_date"))
        .values("yr", "mo")
        .annotate(
            new_count=Count("id", filter=Q(type=Application.ApplicationType.NEW)),
            renewal_count=Count("id", filter=Q(type=Application.ApplicationType.RENEWAL)),
        )
        .order_by("yr", "mo")
    )

    data_map = {(row["yr"], row["mo"]): row for row in qs}

    labels = []
    new_counts = []
    renewal_counts = []

    for y, m in months:
        labels.append(datetime.date(y, m, 1).strftime("%b %Y"))
        row = data_map.get((y, m))
        new_counts.append(row["new_count"] if row else 0)
        renewal_counts.append(row["renewal_count"] if row else 0)

    total_new = sum(new_counts)
    total_renewals = sum(renewal_counts)

    return {
        "labels": labels,
        "new_applications": new_counts,
        "renewals": renewal_counts,
        "start_label": labels[0] if labels else "",
        "end_label": labels[-1] if labels else "",
        "filter_type": filter_type,
        "year": target_year,
        "summary": {
            "total_new": total_new,
            "total_renewals": total_renewals,
            "total_overall": total_new + total_renewals,
        },
    }
