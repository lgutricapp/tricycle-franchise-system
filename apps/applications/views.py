from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_ratelimit.decorators import ratelimit
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applicants.models import Applicant
from apps.documents.models import DocumentRequirement, ApplicationDocument
from apps.documents.services import review_document
from apps.documents.validators import validate_document_file
from apps.franchises.models import Franchise
from apps.notifications.services import notify_applicant
from .models import Application, CURRENT_POLICY_VERSION, StatusHistory
from .services import transition_application, InvalidTransition, ALLOWED_TRANSITIONS
from .services import get_timeline_progress
from .forms import ApplicantForm, VehicleForm, RenewalLookupForm, RenewalOTPForm, PolicyAcceptanceForm
from apps.franchises.models import Franchise, FranchiseHolder
from apps.notifications.message_templates import APPROVED_INSTRUCTIONS_TEMPLATE, submission_message
from apps.core.names import normalize_name
from .services import (
    transition_application, InvalidTransition, ALLOWED_TRANSITIONS,
    get_queue_front, is_queue_front, claim_application_for_review, QueueLocked,
    BLOCKING_QUEUE_STATUSES, QUEUE_DISPLAY_STATUSES, get_timeline_progress,
    FranchiseNumberError, validate_franchise_number, register_franchise,
    get_allowed_transitions, franchise_has_unsettled_violations,
    has_pending_application_for_person,
)

UNSETTLED_VIOLATION_ERROR = (
    "This franchise has unsettled violations and cannot be renewed until they are settled. "
    "Please visit the LGU office to settle outstanding violations first."
)
RENEWAL_OTP_SESSION_KEY = "renewal_otp_challenge"
RENEWAL_VERIFIED_SESSION_KEY = "renewal_verified"
RENEWAL_OTP_TTL_SECONDS = 5 * 60
RENEWAL_VERIFIED_TTL_SECONDS = 15 * 60
RENEWAL_OTP_MAX_ATTEMPTS = 5
RENEWAL_OTP_RESEND_WAIT_SECONDS = 60


def _masked_phone_number(number):
    digits = "".join(character for character in number if character.isdigit())
    return f"{'*' * max(len(digits) - 2, 0)}{digits[-2:]}"


def _has_renewal_verification(request, franchise):
    verification = request.session.get(RENEWAL_VERIFIED_SESSION_KEY, {})
    if (
        verification.get("franchise_id") != franchise.pk
        or verification.get("expires_at", 0) <= timezone.now().timestamp()
    ):
        request.session.pop(RENEWAL_VERIFIED_SESSION_KEY, None)
        return False
    return True

def _validate_document_uploads(request, requirements):
    """
    Checks required-document presence AND validates each uploaded file's
    type/size/content. Returns (missing_required_docs, file_errors, valid_files)
    where valid_files maps requirement.id -> UploadedFile for files that passed.
    """
    missing_required_docs = []
    file_errors = []
    valid_files = {}
    document_errors = {}

    for req in requirements:
        uploaded_file = request.FILES.get(f"document_{req.id}")
        if not uploaded_file:
            if req.required:
                missing_required_docs.append(req.name)
                document_errors[req.id] = "This document is required. Please choose a file."
            continue
        try:
            validate_document_file(uploaded_file)
            valid_files[req.id] = uploaded_file
        except ValidationError as e:
            error = "; ".join(e.messages)
            file_errors.append(f"{req.name}: {error}")
            document_errors[req.id] = error

    return missing_required_docs, file_errors, valid_files, document_errors


def new_application(request):
    requirements = DocumentRequirement.objects.filter(
        active=True, application_type__in=[DocumentRequirement.ApplicationType.NEW, DocumentRequirement.ApplicationType.BOTH]
    )

    if request.method == "POST":
        applicant_form = ApplicantForm(request.POST)
        vehicle_form = VehicleForm(request.POST)
        policy_acceptance_form = PolicyAcceptanceForm(request.POST)
        missing_required_docs, file_errors, valid_files, document_errors = _validate_document_uploads(request, requirements)

        forms_valid = (
            applicant_form.is_valid()
            and vehicle_form.is_valid()
            and policy_acceptance_form.is_valid()
            and not missing_required_docs
            and not file_errors
        )
        if forms_valid and has_pending_application_for_person(
            applicant_form.cleaned_data["first_name"],
            applicant_form.cleaned_data["last_name"],
        ):
            applicant_form.add_error(
                None,
                "You already have an application or renewal in progress. "
                "You may apply again after it is cancelled or rejected.",
            )

        if forms_valid and not applicant_form.errors:
            with transaction.atomic():
                submitted_at = timezone.now()
                applicant = applicant_form.save()
                vehicle = vehicle_form.existing_vehicle or vehicle_form.save()

                application = Application.objects.create(
                    applicant=applicant,
                    vehicle=vehicle,
                    type=Application.ApplicationType.NEW,
                    status=Application.Status.SUBMITTED,
                    submitted_at=submitted_at,
                    policy_accepted_at=submitted_at,
                    policy_version_accepted=CURRENT_POLICY_VERSION,
                )

                StatusHistory.objects.create(
                    application=application,
                    status=Application.Status.SUBMITTED,
                    remarks="Application submitted by applicant.",
                )

                text = submission_message(application)
                transaction.on_commit(lambda: notify_applicant(
                    application,
                    message_sms=text,
                    message_email_subject="Application Received",
                    message_email_body=text,
                ))

                for req in requirements:
                    if req.id in valid_files:
                        ApplicationDocument.objects.create(
                            application=application,
                            document_requirement=req,
                            uploaded_file=valid_files[req.id],
                        )

            return redirect("applications:submitted", reference_code=application.reference_code)
        active_step = (
            0 if applicant_form.errors
            else 1 if vehicle_form.errors
            else 2
        )
    else:
        applicant_form = ApplicantForm()
        vehicle_form = VehicleForm()
        policy_acceptance_form = PolicyAcceptanceForm()
        missing_required_docs = []
        file_errors = []
        document_errors = {}
        active_step = 0

    return render(request, "applications/new_application.html", {
        "applicant_form": applicant_form,
        "vehicle_form": vehicle_form,
        "policy_acceptance_form": policy_acceptance_form,
        "requirements": requirements,
        "missing_required_docs": missing_required_docs,
        "file_errors": file_errors,
        "document_errors": document_errors,
        "active_step": active_step,
        "active_step_label": ("Applicant Information", "Tricycle Information", "Required Documents")[active_step],
        "show_validation_feedback": request.method == "POST",
    })


def application_submitted(request, reference_code):
    application = get_object_or_404(Application, reference_code=reference_code)
    return render(request, "applications/application_submitted.html", {"application": application})


@ratelimit(key="ip", rate="3/10m", method="POST", block=True)
def renewal_lookup(request):
    form = RenewalLookupForm(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        franchise_number = form.cleaned_data["franchise_number"].strip()
        last_name = form.cleaned_data["last_name_confirm"].strip()

        try:
            franchise = Franchise.objects.select_related("holder", "vehicle").get(
                franchise_number__iexact=franchise_number
            )
        except Franchise.DoesNotExist:
            franchise = None

        if franchise and normalize_name(last_name) == normalize_name(franchise.holder.last_name):
            if franchise_has_unsettled_violations(franchise):
                error = UNSETTLED_VIOLATION_ERROR
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})
            if has_pending_application_for_person(
                franchise.holder.first_name,
                franchise.holder.last_name,
            ):
                error = (
                    "You already have an application or renewal in progress. "
                    "You may apply again after it is cancelled or rejected."
                )
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})
            now = timezone.now().timestamp()
            last_sent_at = request.session.get("renewal_otp_last_sent_at", 0)
            if now - last_sent_at < RENEWAL_OTP_RESEND_WAIT_SECONDS:
                error = "Please wait before requesting another verification code."
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})
            if not franchise.holder.contact_number:
                error = "There is no phone number on file for this franchise. Please contact the LGU office."
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})

            from apps.notifications.services import deliver_sms

            code = get_random_string(6, allowed_chars="0123456789")
            delivery = deliver_sms(
                franchise.holder.contact_number,
                f"Your tricycle franchise renewal verification code is {code}. "
                "It expires in 5 minutes. Do not share this code.",
            )
            if not delivery.get("success"):
                error = "We couldn't send a verification code right now. Please try again later."
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})

            request.session[RENEWAL_OTP_SESSION_KEY] = {
                "franchise_id": franchise.pk,
                "code_hash": make_password(code),
                "expires_at": now + RENEWAL_OTP_TTL_SECONDS,
                "attempts": 0,
            }
            request.session["renewal_otp_last_sent_at"] = now
            request.session.pop(RENEWAL_VERIFIED_SESSION_KEY, None)
            return redirect("applications:renewal_verify")

        error = "We couldn't find a matching franchise record. Please check the franchise number and last name."

    return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
def renewal_verify(request):
    challenge = request.session.get(RENEWAL_OTP_SESSION_KEY)
    now = timezone.now().timestamp()
    if not challenge:
        messages.error(request, "Request a verification code before continuing.")
        return redirect("applications:renewal_lookup")

    if challenge.get("expires_at", 0) <= now or challenge.get("attempts", 0) >= RENEWAL_OTP_MAX_ATTEMPTS:
        request.session.pop(RENEWAL_OTP_SESSION_KEY, None)
        request.session.pop("renewal_otp_last_sent_at", None)
        messages.error(request, "Your verification code has expired or too many attempts were made. Please start again.")
        return redirect("applications:renewal_lookup")

    form = RenewalOTPForm(request.POST or None)
    error = None
    if request.method == "POST":
        if form.is_valid() and check_password(form.cleaned_data["code"], challenge["code_hash"]):
            request.session[RENEWAL_VERIFIED_SESSION_KEY] = {
                "franchise_id": challenge["franchise_id"],
                "expires_at": now + RENEWAL_VERIFIED_TTL_SECONDS,
            }
            request.session.pop(RENEWAL_OTP_SESSION_KEY, None)
            request.session.pop("renewal_otp_last_sent_at", None)
            request.session.cycle_key()
            franchise = get_object_or_404(Franchise, pk=challenge["franchise_id"])
            return redirect("applications:renewal_form", franchise_number=franchise.franchise_number)

        challenge["attempts"] += 1
        request.session[RENEWAL_OTP_SESSION_KEY] = challenge
        error = (
            "Invalid verification code. Your code has been invalidated after five failed attempts."
            if challenge["attempts"] >= RENEWAL_OTP_MAX_ATTEMPTS
            else "Invalid verification code. Please try again."
        )

    franchise = get_object_or_404(Franchise, pk=challenge["franchise_id"])
    return render(request, "applications/renewal_verify.html", {
        "form": form,
        "error": error,
        "masked_phone_number": _masked_phone_number(franchise.holder.contact_number),
    })


def renewal_form(request, franchise_number):
    franchise = get_object_or_404(
        Franchise.objects.select_related("holder", "vehicle"), franchise_number=franchise_number
    )
    if franchise_has_unsettled_violations(franchise):
        return render(request, "applications/renewal_lookup.html", {
            "form": RenewalLookupForm(),
            "error": UNSETTLED_VIOLATION_ERROR,
        })
    if has_pending_application_for_person(
        franchise.holder.first_name,
        franchise.holder.last_name,
    ):
        messages.error(
            request,
            "You already have an application or renewal in progress. "
            "You may apply again after it is cancelled or rejected.",
        )
        return redirect("applications:renewal_lookup")
    if not _has_renewal_verification(request, franchise):
        messages.error(request, "Verify the code sent to the franchise owner's phone before renewing.")
        return redirect("applications:renewal_lookup")

    requirements = DocumentRequirement.objects.filter(
        active=True,
        application_type__in=[DocumentRequirement.ApplicationType.RENEWAL, DocumentRequirement.ApplicationType.BOTH],
    )

    if request.method == "POST":
        policy_acceptance_form = PolicyAcceptanceForm(request.POST)
        missing_required_docs, file_errors, valid_files, document_errors = _validate_document_uploads(request, requirements)

        if policy_acceptance_form.is_valid() and not missing_required_docs and not file_errors:
            with transaction.atomic():
                submitted_at = timezone.now()
                # Snapshot the holder's current info as this renewal's Applicant
                # record. No edits are accepted here — the holder/vehicle registry
                # only changes through the LGU office, not a self-service renewal.
                applicant = Applicant.objects.create(
                    first_name=franchise.holder.first_name,
                    middle_name=franchise.holder.middle_name,
                    last_name=franchise.holder.last_name,
                    address=franchise.holder.address,
                    contact_number=franchise.holder.contact_number,
                    email=franchise.holder.email,
                )

                application = Application.objects.create(
                    applicant=applicant,
                    vehicle=franchise.vehicle,
                    franchise=franchise,
                    type=Application.ApplicationType.RENEWAL,
                    status=Application.Status.SUBMITTED,
                    submitted_at=submitted_at,
                    policy_accepted_at=submitted_at,
                    policy_version_accepted=CURRENT_POLICY_VERSION,
                )

                StatusHistory.objects.create(
                    application=application,
                    status=Application.Status.SUBMITTED,
                    remarks="Renewal submitted by applicant.",
                )

                text = submission_message(application)
                transaction.on_commit(lambda: notify_applicant(
                    application,
                    message_sms=text,
                    message_email_subject="Application Received",
                    message_email_body=text,
                ))

                for req in requirements:
                    if req.id in valid_files:
                        ApplicationDocument.objects.create(
                            application=application,
                            document_requirement=req,
                            uploaded_file=valid_files[req.id],
                        )

            request.session.pop(RENEWAL_VERIFIED_SESSION_KEY, None)
            return redirect("applications:submitted", reference_code=application.reference_code)
    else:
        policy_acceptance_form = PolicyAcceptanceForm()
        missing_required_docs = []
        file_errors = []
        document_errors = {}

    return render(request, "applications/renewal_form.html", {
        "franchise": franchise,
        "policy_acceptance_form": policy_acceptance_form,
        "requirements": requirements,
        "missing_required_docs": missing_required_docs,
        "file_errors": file_errors,
        "document_errors": document_errors,
        "show_validation_feedback": request.method == "POST",
    })


@ratelimit(key="ip", rate="10/m", block=True)
def track_application(request):
    error = None
    if request.method == "POST":
        reference_code = request.POST.get("reference_code", "").strip().upper()
        try:
            application = Application.objects.get(reference_code=reference_code)
            return redirect("applications:status", reference_code=application.reference_code)
        except Application.DoesNotExist:
            error = "No application found with that reference code. Please check and try again."

    return render(request, "applications/track_application.html", {"error": error})


def application_status(request, reference_code):
    application = get_object_or_404(
        Application.objects.select_related("applicant", "vehicle", "franchise"),
        reference_code=reference_code,
    )
    documents = application.documents.select_related("document_requirement").order_by(
        "document_requirement__name", "-uploaded_at"
    )
    history = application.status_history.all()
    timeline_steps, timeline_current_index, timeline_is_negative = get_timeline_progress(application)
    resubmit_error = None

    if request.method == "POST":
        doc_id = request.POST.get("resubmit_document_id")
        flagged_doc = get_object_or_404(
            ApplicationDocument, id=doc_id, application=application, status=ApplicationDocument.Status.REVISION_REQUIRED
        )
        new_file = request.FILES.get("replacement_file")
        if new_file:
            try:
                validate_document_file(new_file)
            except ValidationError as e:
                resubmit_error = "; ".join(e.messages)
            else:
                with transaction.atomic():
                    ApplicationDocument.objects.create(
                        application=application,
                        document_requirement=flagged_doc.document_requirement,
                        uploaded_file=new_file,
                        supersedes=flagged_doc,
                    )
                    if application.status == Application.Status.REVISION_REQUIRED:
                        application.status = Application.Status.RESUBMITTED
                        application.save()
                        StatusHistory.objects.create(
                            application=application,
                            status=Application.Status.RESUBMITTED,
                            remarks=f"Applicant re-uploaded: {flagged_doc.document_requirement.name}",
                        )
                return redirect("applications:status", reference_code=application.reference_code)

    return render(request, "applications/application_status.html", {
        "application": application,
        "documents": documents,
        "history": history,
        "resubmit_error": resubmit_error,
        "timeline_steps": timeline_steps,
        "timeline_current_index": timeline_current_index,
        "timeline_is_negative": timeline_is_negative,
    })


# --- Staff / admin views ---

@role_required(User.Role.STAFF, User.Role.REVIEWER)
def staff_application_list(request):
    status_filter = request.GET.get("status", "")
    type_filter = request.GET.get("type", "")
    query = request.GET.get("q", "")

    applications = Application.objects.select_related("applicant", "franchise").order_by("-created_at")
    if status_filter:
        applications = applications.filter(status=status_filter)
    if type_filter:
        applications = applications.filter(type=type_filter)
    if query:
        applications = applications.filter(
            Q(reference_code__icontains=query) | Q(applicant__full_name__icontains=query)
        )

    return render(request, "applications/staff_application_list.html", {
        "applications": applications,
        "status_choices": Application.Status.choices,
        "type_choices": Application.ApplicationType.choices,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "query": query,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def staff_application_detail(request, reference_code):
    application = get_object_or_404(
        Application.objects.select_related("applicant", "vehicle", "franchise"),
        reference_code=reference_code,
    )

    if application.status in BLOCKING_QUEUE_STATUSES and not is_queue_front(application):
        front = get_queue_front(application.type)
        return render(request, "applications/application_locked.html", {
            "application": application, "front": front,
        }, status=403)

    if (
        request.method == "GET"
        and (request.user.role != User.Role.REVIEWER or request.user.is_superuser)
        and application.status in (
        Application.Status.SUBMITTED, Application.Status.RESUBMITTED
        )
    ):
        try:
            claim_application_for_review(application, request.user)
        except QueueLocked:
            front = get_queue_front(application.type)
            return render(request, "applications/application_locked.html", {
                "application": application, "front": front,
            }, status=403)
        application.refresh_from_db()

    documents = application.documents.select_related("document_requirement").filter(
        superseded_by_set__isnull=True
    ).order_by("document_requirement__name")
    history = application.status_history.all()
    allowed_next_statuses = get_allowed_transitions(application)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "review_documents":
            valid_statuses = [value for value, _ in ApplicationDocument.Status.choices]
            updated_names = []
            for doc in documents:
                new_status = request.POST.get(f"doc_status_{doc.id}", doc.status)
                new_remarks = request.POST.get(f"doc_remarks_{doc.id}", doc.admin_remarks)
                if new_status not in valid_statuses:
                    continue
                if new_status != doc.status or new_remarks != doc.admin_remarks:
                    review_document(doc, new_status, request.user, new_remarks)
                    updated_names.append(doc.document_requirement.name)

            if updated_names:
                messages.success(request, f"Updated {len(updated_names)} document(s): " + ", ".join(updated_names))
            else:
                messages.info(request, "No document changes to save.")

        elif action == "transition_status":
            if request.user.role == User.Role.REVIEWER and not request.user.is_superuser:
                messages.error(request, "Reviewers cannot change the overall application status.")
            else:
                new_status = request.POST.get("new_status")
                remarks = request.POST.get("remarks", "")

                if new_status != Application.Status.CANCELLED:
                    pending_docs = [
                        doc.document_requirement.name for doc in documents
                        if doc.status == ApplicationDocument.Status.PENDING
                    ]
                    if pending_docs:
                        messages.error(
                            request,
                            "Cannot update application status — the following document(s) "
                            "still need to be reviewed: " + ", ".join(pending_docs)
                        )
                        return redirect("staff_applications:detail", reference_code=application.reference_code)

                    blocked_documents = [
                        doc.document_requirement.name for doc in documents
                        if doc.status in (
                            ApplicationDocument.Status.REVISION_REQUIRED,
                            ApplicationDocument.Status.REJECTED,
                        )
                    ]
                    if new_status == Application.Status.APPROVED and blocked_documents:
                        messages.error(
                            request,
                            "Cannot approve — resolve the following document(s) marked "
                            "Requires Revision or Rejected first: " + ", ".join(blocked_documents)
                        )
                        return redirect("staff_applications:detail", reference_code=application.reference_code)
                    if (
                        new_status == Application.Status.REJECTED
                        and any(
                            doc.status == ApplicationDocument.Status.REVISION_REQUIRED
                            for doc in documents
                        )
                    ):
                        messages.error(
                            request,
                            "Cannot reject — resolve documents tagged Revision Required first."
                        )
                        return redirect("staff_applications:detail", reference_code=application.reference_code)

                try:
                    transition_application(application, new_status, request.user, remarks)
                except InvalidTransition as e:
                    messages.error(request, str(e))
                else:
                    if new_status == Application.Status.APPROVED:
                        if application.type == Application.ApplicationType.NEW:
                            messages.success(
                                request,
                                "Application approved. Enter its Franchise Number below to complete the registration."
                            )
                            return redirect("staff_applications:approved_list")
                        messages.success(request, "Renewal approved and the franchise record has been updated.")
                        return redirect("staff_applications:approved_renewals_list")
                    messages.success(request, "Application status updated.")

        return redirect("staff_applications:detail", reference_code=application.reference_code)

    pending_document_names = [
        doc.document_requirement.name for doc in documents
        if doc.status == ApplicationDocument.Status.PENDING
    ]
    approval_blocked_document_names = [
        doc.document_requirement.name for doc in documents
        if doc.status in (
            ApplicationDocument.Status.REVISION_REQUIRED,
            ApplicationDocument.Status.REJECTED,
        )
    ]

    return render(request, "applications/staff_application_detail.html", {
        "application": application,
        "documents": documents,
        "history": history,
        "allowed_next_statuses": allowed_next_statuses,
        "document_status_choices": ApplicationDocument.Status.choices,
        "pending_document_names": pending_document_names,
        "approval_blocked_document_names": approval_blocked_document_names,
    })


def _queue_view(request, application_type, page_title):
    queue = Application.objects.select_related("applicant").filter(
        type=application_type, status__in=QUEUE_DISPLAY_STATUSES
    ).order_by("submitted_at", "id")
    front = get_queue_front(application_type)
    return render(request, "applications/application_queue.html", {
        "queue": queue, "front": front, "page_title": page_title,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def new_application_queue(request):
    return _queue_view(request, Application.ApplicationType.NEW, "New Application Queue")


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def renewal_queue(request):
    return _queue_view(request, Application.ApplicationType.RENEWAL, "Renewal Queue")


def _type_filtered_list(request, fixed_type, page_title):
    status_filter = request.GET.get("status", "")
    query = request.GET.get("q", "")

    applications = Application.objects.select_related("applicant", "franchise").filter(
        type=fixed_type
    ).order_by("-created_at")
    if status_filter:
        applications = applications.filter(status=status_filter)
    if query:
        applications = applications.filter(
            Q(reference_code__icontains=query) | Q(applicant__full_name__icontains=query)
        )

    return render(request, "applications/staff_application_list.html", {
        "applications": applications,
        "status_choices": Application.Status.choices,
        "status_filter": status_filter,
        "query": query,
        "page_title": page_title,
        "hide_type_filter": True,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def new_applications_list(request):
    return _type_filtered_list(request, Application.ApplicationType.NEW, "New Applications")


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def renewal_applications_list(request):
    return _type_filtered_list(request, Application.ApplicationType.RENEWAL, "Renewal Applications")


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def approved_applications_list(request):
    applications = Application.objects.select_related("applicant", "franchise").filter(
        type=Application.ApplicationType.NEW,
        status=Application.Status.APPROVED,
    ).order_by("-updated_at")
    franchise_retry = request.session.pop("franchise_retry", None)
    return render(request, "applications/status_filtered_list.html", {
        "applications": applications,
        "page_title": "Approved Applications",
        "franchise_retry": franchise_retry,
        "show_message_button": True,
        "approved_message_template": APPROVED_INSTRUCTIONS_TEMPLATE,
    })

@role_required(User.Role.STAFF, User.Role.REVIEWER)
def approved_renewals_list(request):
    applications = Application.objects.select_related("applicant", "franchise").filter(
        type=Application.ApplicationType.RENEWAL,
        status__in=[Application.Status.APPROVED, Application.Status.COMPLETED],
    ).order_by("-updated_at")
    return render(request, "applications/status_filtered_list.html", {
        "applications": applications,
        "page_title": "Approved Renewals",
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def rejected_applications_list(request):
    applications = Application.objects.select_related("applicant", "franchise").filter(
        status=Application.Status.REJECTED
    ).order_by("-updated_at")
    return render(request, "applications/status_filtered_list.html", {
        "applications": applications, "page_title": "Rejected Applications",
    })


@role_required(User.Role.STAFF)
def confirm_franchise_number(request, reference_code):
    application = get_object_or_404(Application, reference_code=reference_code)

    if request.method != "POST":
        return redirect("staff_applications:approved_list")

    if application.type != Application.ApplicationType.NEW or application.status != Application.Status.APPROVED:
        messages.error(request, "This application is not awaiting a franchise number.")
        return redirect("staff_applications:approved_list")

    if not application.franchise_number_unlocked_at:
        messages.error(request, "Send a message successfully to the applicant before entering a franchise number.")
        return redirect("staff_applications:approved_list")

    raw_number = request.POST.get("franchise_number", "")
    try:
        franchise_number = validate_franchise_number(raw_number)
        with transaction.atomic():
            locked = Application.objects.select_for_update().select_related(
                "applicant", "vehicle"
            ).get(pk=application.pk)
            if locked.status != Application.Status.APPROVED:
                raise InvalidTransition("This application has already been registered.")
            franchise = register_franchise(locked, franchise_number, request.user)
    except (FranchiseNumberError, IntegrityError) as e:
        error = str(e) if isinstance(e, FranchiseNumberError) else (
            "Franchise number already exists. Please enter a different franchise number."
        )
        request.session["franchise_retry"] = {
            "reference_code": application.reference_code,
            "number": raw_number,
            "error": error,
        }
    except InvalidTransition as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Franchise {franchise.franchise_number} registered successfully.")

    return redirect("staff_applications:approved_list")

@role_required(User.Role.STAFF, User.Role.REVIEWER)
def application_summary(request, reference_code):
    # Only finished applications are viewable here. Anything still in the
    # queue must go through the locked review page, so this can't be used
    # to peek at queued applications out of order.
    application = get_object_or_404(
        Application.objects.select_related("applicant", "vehicle"),
        reference_code=reference_code,
        status__in=[
            Application.Status.APPROVED,
            Application.Status.COMPLETED,
            Application.Status.REJECTED,
        ],
    )
    history = application.status_history.select_related("changed_by").all()
    rejection_entry = None
    if application.status == Application.Status.REJECTED:
        rejection_entry = history.filter(status=Application.Status.REJECTED).first()

    return render(request, "applications/_application_summary.html", {
        "application": application, "history": history, "rejection_entry": rejection_entry,
    })