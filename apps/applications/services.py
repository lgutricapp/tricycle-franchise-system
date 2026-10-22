from django.db import transaction
from django.utils import timezone
from apps.audit.services import log_action
from apps.notifications.message_templates import (
    approved_message, rejected_message, revision_required_message,
)
from apps.notifications.services import notify_applicant
from .models import Application, StatusHistory


ALLOWED_TRANSITIONS = {
    Application.Status.SUBMITTED: [Application.Status.UNDER_REVIEW, Application.Status.CANCELLED],
    Application.Status.UNDER_REVIEW: [
        Application.Status.REVISION_REQUIRED,
        Application.Status.APPROVED,
        Application.Status.REJECTED,
        Application.Status.CANCELLED,
    ],
    Application.Status.REVISION_REQUIRED: [Application.Status.CANCELLED],
    Application.Status.RESUBMITTED: [Application.Status.UNDER_REVIEW],
    # Legacy only: lets any application still sitting in the old status move forward.
    Application.Status.FOR_APPROVAL: [Application.Status.APPROVED, Application.Status.REJECTED],
    Application.Status.APPROVED: [Application.Status.COMPLETED],
}

# Automatic applicant messages (SMS, plus email when the applicant provided one).
STATUS_MESSAGE_BUILDERS = {
    Application.Status.REVISION_REQUIRED: revision_required_message,
    Application.Status.APPROVED: approved_message,
    Application.Status.REJECTED: rejected_message,
}

# Statuses that occupy a queue position and block the next application.
BLOCKING_QUEUE_STATUSES = [
    Application.Status.SUBMITTED,
    Application.Status.RESUBMITTED,
    Application.Status.UNDER_REVIEW,
    Application.Status.FOR_APPROVAL,
]
# Shown in the queue view for context (paused-for-revision stays visible but doesn't block).
QUEUE_DISPLAY_STATUSES = BLOCKING_QUEUE_STATUSES + [Application.Status.REVISION_REQUIRED]
# "Already claimed and actively being worked" — always wins the front position.
ACTIVE_PROCESSING_STATUSES = [Application.Status.UNDER_REVIEW, Application.Status.FOR_APPROVAL]


class InvalidTransition(Exception):
    pass


class QueueLocked(Exception):
    pass


class FranchiseNumberError(Exception):
    pass


def franchise_has_unsettled_violations(franchise):
    from apps.violations.models import Violation

    return franchise.violations.filter(status=Violation.Status.UNSETTLED).exists()


def _one_year_from(day):
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # Feb 29 -> non-leap year
        return day.replace(year=day.year + 1, day=28)


def get_allowed_transitions(application):
    """
    Next statuses this application may move to. Renewals can only be sent
    for revision or approved: they cannot be rejected or cancelled.
    """
    allowed = list(ALLOWED_TRANSITIONS.get(application.status, []))
    if application.type == Application.ApplicationType.RENEWAL:
        allowed = [
            s for s in allowed
            if s not in (Application.Status.REJECTED, Application.Status.CANCELLED)
        ]
    return allowed


def transition_application(application, new_status, actor, remarks="", notify=True):
    if (
        new_status == Application.Status.APPROVED
        and application.type == Application.ApplicationType.RENEWAL
        and franchise_has_unsettled_violations(application.franchise)
    ):
        raise InvalidTransition("A renewal cannot be approved while the franchise has unsettled violations.")

    allowed = get_allowed_transitions(application)
    if new_status not in allowed:
        raise InvalidTransition(
            f"Cannot move an application from '{application.get_status_display()}' to '{new_status}'."
        )

    if new_status == Application.Status.REJECTED and not (remarks or "").strip():
        raise InvalidTransition("A reason is required when rejecting an application. Please enter remarks.")

    old_status = application.status
    application.status = new_status
    application.save()

    StatusHistory.objects.create(
        application=application, status=new_status, changed_by=actor, remarks=remarks
    )
    log_action(
        actor, "application_status_changed", application,
        {"from": old_status, "to": new_status, "remarks": remarks},
    )

    if new_status == Application.Status.APPROVED:
        _apply_approval(application, actor)

    if notify and new_status in STATUS_MESSAGE_BUILDERS:
        text = STATUS_MESSAGE_BUILDERS[new_status](application)
        notify_applicant(
            application,
            message_sms=text,
            message_email_subject=f"Application {application.reference_code} update",
            message_email_body=text,
            actor=actor,
        )

    return application


def _apply_approval(application, actor):
    from apps.franchises.models import Franchise

    if application.type == Application.ApplicationType.RENEWAL:
        # Renewals reuse the existing franchise number, so the workflow
        # completes automatically right after approval.
        franchise = application.franchise
        franchise.expiration_date = _one_year_from(timezone.now().date())
        franchise.status = Franchise.Status.ACTIVE
        franchise.save()
        log_action(actor, "franchise_renewed", franchise, {"application": application.reference_code})
        transition_application(
            application, Application.Status.COMPLETED, actor,
            remarks="Renewal completed; franchise record updated.",
        )
    # NEW applications stop at APPROVED. Staff enter the franchise number later
    # from the Approved Applications page (see register_franchise below).


def validate_franchise_number(raw_number):
    from apps.franchises.models import Franchise

    franchise_number = (raw_number or "").strip()
    if not franchise_number:
        raise FranchiseNumberError("Franchise number is required.")
    if "/" in franchise_number or "\\" in franchise_number:
        raise FranchiseNumberError("Franchise number cannot contain slashes. Use a dash instead.")
    if Franchise.objects.filter(franchise_number__iexact=franchise_number).exists():
        raise FranchiseNumberError("Franchise number already exists. Please enter a different franchise number.")
    return franchise_number


def register_franchise(application, franchise_number, actor):
    """
    Creates the holder + official franchise record from an approved NEW
    application and marks the application Completed. Call inside a transaction.
    """
    from apps.franchises.models import Franchise, FranchiseHolder

    today = timezone.now().date()
    holder = FranchiseHolder.objects.create(
        first_name=application.applicant.first_name,
        middle_name=application.applicant.middle_name,
        last_name=application.applicant.last_name,
        address=application.applicant.address,
        contact_number=application.applicant.contact_number,
        email=application.applicant.email,
    )
    franchise = Franchise.objects.create(
        franchise_number=franchise_number,
        holder=holder,
        vehicle=application.vehicle,
        date_issued=today,
        expiration_date=_one_year_from(today),
        registered_by=actor,
    )
    application.franchise = franchise
    application.save()
    transition_application(
        application, Application.Status.COMPLETED, actor,
        remarks=f"Franchise number {franchise_number} confirmed.",
    )
    log_action(actor, "franchise_number_confirmed", franchise, {
        "application": application.reference_code, "franchise_number": franchise_number,
    })
    return franchise


def get_queue_front(application_type):
    active = Application.objects.filter(
        type=application_type, status__in=ACTIVE_PROCESSING_STATUSES
    ).order_by("submitted_at", "id").first()
    if active:
        return active

    return Application.objects.filter(
        type=application_type,
        status__in=[Application.Status.SUBMITTED, Application.Status.RESUBMITTED],
    ).order_by("submitted_at", "id").first()


def is_queue_front(application):
    front = get_queue_front(application.type)
    return front is not None and front.pk == application.pk


def claim_application_for_review(application, actor):
    with transaction.atomic():
        list(Application.objects.select_for_update().filter(
            type=application.type, status__in=BLOCKING_QUEUE_STATUSES
        ))

        front = get_queue_front(application.type)
        if front is None or front.pk != application.pk:
            raise QueueLocked(
                "This application is currently locked. The previous application in the "
                "queue must be processed first."
            )

        if application.status in (Application.Status.SUBMITTED, Application.Status.RESUBMITTED):
            transition_application(
                application, Application.Status.UNDER_REVIEW, actor, remarks="Opened for review."
            )
            log_action(actor, "application_review_started", application,
                       {"reference_code": application.reference_code})
    return application


TIMELINE_STEPS = [
    (Application.Status.SUBMITTED, "Submitted"),
    (Application.Status.UNDER_REVIEW, "Under Review"),
    (Application.Status.FOR_APPROVAL, "For Approval"),
    (Application.Status.APPROVED, "Approved"),
]

TIMELINE_STATUS_ALIASES = {
    Application.Status.RESUBMITTED: Application.Status.UNDER_REVIEW,
    Application.Status.REVISION_REQUIRED: Application.Status.UNDER_REVIEW,
    Application.Status.COMPLETED: Application.Status.APPROVED,
}


def get_timeline_progress(application):
    if application.status in (Application.Status.REJECTED, Application.Status.CANCELLED):
        return TIMELINE_STEPS, None, True

    effective_status = TIMELINE_STATUS_ALIASES.get(application.status, application.status)
    current_index = next(
        (i for i, (status, _) in enumerate(TIMELINE_STEPS) if status == effective_status), 0
    )
    return TIMELINE_STEPS, current_index, False