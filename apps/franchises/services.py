from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone

from apps.applications.models import StatusHistory
from .models import Franchise

from apps.applications.models import Application, StatusHistory
from apps.documents.models import ApplicationDocument


def refresh_franchise_statuses():
    """
    Keep each franchise's stored status in line with its expiration date.
    Revoked franchises are left alone.
    """
    today = timezone.localdate()
    Franchise.objects.filter(
        status=Franchise.Status.ACTIVE, expiration_date__lt=today
    ).update(status=Franchise.Status.EXPIRED)
    Franchise.objects.filter(
        status=Franchise.Status.EXPIRED, expiration_date__gte=today
    ).update(status=Franchise.Status.ACTIVE)


def current_franchises_queryset():
    """Franchises listed under Franchise Holders: not expired (revoked ones stay visible)."""
    today = timezone.localdate()
    return Franchise.objects.filter(
        Q(status=Franchise.Status.REVOKED) | Q(expiration_date__gte=today)
    )


def expired_franchises_queryset():
    """Franchises whose expiration date has passed (revoked ones are excluded)."""
    today = timezone.localdate()
    return Franchise.objects.filter(expiration_date__lt=today).exclude(
        status=Franchise.Status.REVOKED
    )


def _midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def build_franchise_timeline(franchise):
    """Newest-first list of events from a franchise's history."""
    events = []

    history = StatusHistory.objects.filter(
        application__franchise=franchise
    ).select_related("application", "changed_by")
    for entry in history:
        application = entry.application
        events.append({
            "when": entry.changed_at,
            "show_time": True,
            "label": f"{application.get_type_display()} {application.reference_code}: {entry.get_status_display()}",
            "by": entry.changed_by,
            "remarks": entry.remarks,
        })

    if franchise.source == Franchise.Source.MANUAL and franchise.registered_at:
        events.append({
            "when": franchise.registered_at,
            "show_time": True,
            "label": "Added to the system manually",
            "by": franchise.registered_by,
            "remarks": "",
        })

    events.append({
        "when": _midnight(franchise.date_issued),
        "show_time": False,
        "label": "Franchise issued",
        "by": None,
        "remarks": "",
    })
    events.append({
        "when": _midnight(franchise.expiration_date),
        "show_time": False,
        "label": "Franchise expired",
        "by": None,
        "remarks": "",
    })

    events.sort(key=lambda e: e["when"], reverse=True)
    return events

def get_current_documents(franchise):
    """The most recent approved file for each document requirement on a franchise."""
    best = {}

    def consider(requirement, uploaded_at, file_field, source):
        current = best.get(requirement.id)
        if current is None or uploaded_at > current["uploaded_at"]:
            best[requirement.id] = {
                "name": requirement.name,
                "uploaded_at": uploaded_at,
                "url": file_field.url if file_field else "",
                "source": source,
            }

    # Files uploaded directly to the franchise (manually added franchises)
    for doc in franchise.documents.select_related("document_requirement", "uploaded_by"):
        who = ""
        if doc.uploaded_by:
            who = " by " + (doc.uploaded_by.get_full_name() or doc.uploaded_by.username)
        consider(doc.document_requirement, doc.uploaded_at, doc.uploaded_file, "Added manually" + who)

    # Approved files from the franchise's accepted applications and renewals
    application_docs = ApplicationDocument.objects.filter(
        application__franchise=franchise,
        application__status__in=[Application.Status.APPROVED, Application.Status.COMPLETED],
        status=ApplicationDocument.Status.APPROVED,
        superseded_by_set__isnull=True,
    ).select_related("document_requirement", "application")
    for doc in application_docs:
        application = doc.application
        consider(
            doc.document_requirement, doc.uploaded_at, doc.uploaded_file,
            f"{application.get_type_display()} {application.reference_code}",
        )

    return sorted(best.values(), key=lambda d: d["name"])