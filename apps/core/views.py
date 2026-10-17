from datetime import timedelta
from django.shortcuts import render
from django.utils import timezone
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applications.models import Application
from apps.franchises.models import Franchise
from apps.violations.models import Violation
from django.shortcuts import render
from apps.franchises.services import expired_franchises_queryset, refresh_franchise_statuses

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404


def home(request):
    return render(request, "core/home.html")

def ratelimited_view(request, exception=None):
    return render(request, "core/ratelimited.html", status=429)

ACTIVE_QUEUE_STATUSES_EXCLUDED = [
    Application.Status.APPROVED,
    Application.Status.REJECTED,
    Application.Status.CANCELLED,
    Application.Status.COMPLETED,
]


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def dashboard(request):
    refresh_franchise_statuses()
    today = timezone.now().date()
    soon = today + timedelta(days=30)

    stats = {
        "active_franchises": Franchise.objects.filter(status=Franchise.Status.ACTIVE).count(),
        "expired_franchises": expired_franchises_queryset().count(),
        "expiring_soon": Franchise.objects.filter(
            status=Franchise.Status.ACTIVE, expiration_date__range=(today, soon)
        ).count(),
        "new_pending": Application.objects.filter(type=Application.ApplicationType.NEW)
            .exclude(status__in=ACTIVE_QUEUE_STATUSES_EXCLUDED).count(),
        "renewal_pending": Application.objects.filter(type=Application.ApplicationType.RENEWAL)
            .exclude(status__in=ACTIVE_QUEUE_STATUSES_EXCLUDED).count(),
        "revision_required": Application.objects.filter(status=Application.Status.REVISION_REQUIRED).count(),
        "unsettled_violations": Violation.objects.filter(status=Violation.Status.UNSETTLED).count(),
    }

    recent_queue = Application.objects.select_related("applicant").exclude(
        status__in=ACTIVE_QUEUE_STATUSES_EXCLUDED
    ).order_by("-created_at")[:10]

    return render(request, "core/dashboard.html", {"stats": stats, "recent_queue": recent_queue})

@role_required(User.Role.STAFF, User.Role.REVIEWER)
def protected_media(request, path):
    """Serve an uploaded file, but only to signed-in staff."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    full_path = (media_root / path).resolve()
    # Refuse anything that escapes the media folder or isn't a real file
    if media_root not in full_path.parents or not full_path.is_file():
        raise Http404

    content_type, _ = mimetypes.guess_type(str(full_path))
    response = FileResponse(open(full_path, "rb"), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{full_path.name}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response