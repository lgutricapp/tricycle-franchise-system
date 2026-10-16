from django import template

register = template.Library()

STATUS_TONE_MAP = {
    # Application statuses
    "DRAFT": "neutral", "SUBMITTED": "pending", "UNDER_REVIEW": "pending",
    "RESUBMITTED": "pending", "FOR_APPROVAL": "pending",
    "REVISION_REQUIRED": "warning",
    "APPROVED": "success", "COMPLETED": "success",
    "REJECTED": "danger", "CANCELLED": "danger",
    # Document statuses
    "PENDING": "pending", "REVISION_REQUIRED": "warning",
    # Franchise statuses
    "ACTIVE": "success", "EXPIRED": "danger", "REVOKED": "danger",
    # Violation statuses
    "UNSETTLED": "danger", "SETTLED": "success",
    # Notification delivery statuses
    "SENT": "success", "DELIVERED": "success", "FAILED": "danger",
}


@register.filter
def status_tone(status_value):
    return STATUS_TONE_MAP.get(status_value, "neutral")

STATUS_ICON_MAP = {
    "success": "bi-check-circle-fill",
    "pending": "bi-hourglass-split",
    "warning": "bi-exclamation-triangle-fill",
    "danger": "bi-x-circle-fill",
    "neutral": "bi-dash-circle",
}


@register.filter
def status_icon(status_value):
    tone = STATUS_TONE_MAP.get(status_value, "neutral")
    return STATUS_ICON_MAP.get(tone, "bi-dash-circle")