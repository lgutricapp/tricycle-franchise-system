from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applicants.models import Applicant
from apps.documents.models import DocumentRequirement, ApplicationDocument
from apps.documents.services import review_document
from apps.documents.validators import validate_document_file
from apps.franchises.models import Franchise
from apps.notifications.services import notify_applicant
from .models import Application, StatusHistory
from .services import transition_application, InvalidTransition, ALLOWED_TRANSITIONS
from .services import get_timeline_progress
from .forms import ApplicantForm, VehicleForm, RenewalLookupForm
from apps.franchises.models import Franchise, FranchiseHolder
from apps.notifications.message_templates import APPROVED_INSTRUCTIONS_TEMPLATE, submission_message
from apps.core.names import normalize_name
from .services import (
    transition_application, InvalidTransition, ALLOWED_TRANSITIONS,
    get_queue_front, is_queue_front, claim_application_for_review, QueueLocked,
    BLOCKING_QUEUE_STATUSES, QUEUE_DISPLAY_STATUSES, get_timeline_progress,
    FranchiseNumberError, validate_franchise_number, register_franchise,
    get_allowed_transitions,
)

def _validate_document_uploads(request, requirements):
    """
    Checks required-document presence AND validates each uploaded file's
    type/size/content. Returns (missing_required_docs, file_errors, valid_files)
    where valid_files maps requirement.id -> UploadedFile for files that passed.
    """
    missing_required_docs = []
    file_errors = []
    valid_files = {}

    for req in requirements:
        uploaded_file = request.FILES.get(f"document_{req.id}")
        if not uploaded_file:
            if req.required:
                missing_required_docs.append(req.name)
            continue
        try:
            validate_document_file(uploaded_file)
            valid_files[req.id] = uploaded_file
        except ValidationError as e:
            file_errors.append(f"{req.name}: {'; '.join(e.messages)}")

    return missing_required_docs, file_errors, valid_files


def new_application(request):
    requirements = DocumentRequirement.objects.filter(
        active=True, application_type__in=[DocumentRequirement.ApplicationType.NEW, DocumentRequirement.ApplicationType.BOTH]
    )

    if request.method == "POST":
        applicant_form = ApplicantForm(request.POST)
        vehicle_form = VehicleForm(request.POST)
        missing_required_docs, file_errors, valid_files = _validate_document_uploads(request, requirements)

        if applicant_form.is_valid() and vehicle_form.is_valid() and not missing_required_docs and not file_errors:
            with transaction.atomic():
                applicant = applicant_form.save()
                vehicle = vehicle_form.save()

                application = Application.objects.create(
                    applicant=applicant,
                    vehicle=vehicle,
                    type=Application.ApplicationType.NEW,
                    status=Application.Status.SUBMITTED,
                    submitted_at=timezone.now(),
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
    else:
        applicant_form = ApplicantForm()
        vehicle_form = VehicleForm()
        missing_required_docs = []
        file_errors = []

    return render(request, "applications/new_application.html", {
        "applicant_form": applicant_form,
        "vehicle_form": vehicle_form,
        "requirements": requirements,
        "missing_required_docs": missing_required_docs,
        "file_errors": file_errors,
    })


def application_submitted(request, reference_code):
    application = get_object_or_404(Application, reference_code=reference_code)
    return render(request, "applications/application_submitted.html", {"application": application})


@ratelimit(key="ip", rate="10/m", block=True)
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
            from apps.core.models import SystemConfiguration
            from apps.violations.models import Violation

            config = SystemConfiguration.get()
            has_unsettled = franchise.violations.filter(status=Violation.Status.UNSETTLED).exists()
            if config.block_renewal_on_unsettled_violations and has_unsettled:
                error = (
                    "This franchise has unsettled violations and cannot be renewed online. "
                    "Please visit the LGU office to settle outstanding violations first."
                )
                return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})
            return redirect("applications:renewal_form", franchise_number=franchise.franchise_number)

        error = "We couldn't find a matching franchise record. Please check the franchise number and last name."

    return render(request, "applications/renewal_lookup.html", {"form": form, "error": error})


def renewal_form(request, franchise_number):
    franchise = get_object_or_404(
        Franchise.objects.select_related("holder", "vehicle"), franchise_number=franchise_number
    )
    requirements = DocumentRequirement.objects.filter(
        active=True,
        application_type__in=[DocumentRequirement.ApplicationType.RENEWAL, DocumentRequirement.ApplicationType.BOTH],
    )

    if request.method == "POST":
        missing_required_docs, file_errors, valid_files = _validate_document_uploads(request, requirements)

        if not missing_required_docs and not file_errors:
            with transaction.atomic():
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
                    submitted_at=timezone.now(),
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

            return redirect("applications:submitted", reference_code=application.reference_code)
    else:
        missing_required_docs = []
        file_errors = []

    return render(request, "applications/renewal_form.html", {
        "franchise": franchise,
        "requirements": requirements,
        "missing_required_docs": missing_required_docs,
        "file_errors": file_errors,
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

    if request.method == "GET" and application.status in (
        Application.Status.SUBMITTED, Application.Status.RESUBMITTED
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

                    if new_status in (Application.Status.APPROVED, Application.Status.REJECTED):
                        revision_flagged_docs = [
                            doc.document_requirement.name for doc in documents
                            if doc.status == ApplicationDocument.Status.REVISION_REQUIRED
                        ]
                        if revision_flagged_docs:
                            messages.error(
                                request,
                                "Cannot approve or reject — the following document(s) are still "
                                "tagged Revision Required and must be resolved first: " + ", ".join(revision_flagged_docs)
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
    revision_required_document_names = [
        doc.document_requirement.name for doc in documents
        if doc.status == ApplicationDocument.Status.REVISION_REQUIRED
    ]

    return render(request, "applications/staff_application_detail.html", {
        "application": application,
        "documents": documents,
        "history": history,
        "allowed_next_statuses": allowed_next_statuses,
        "document_status_choices": ApplicationDocument.Status.choices,
        "pending_document_names": pending_document_names,
        "revision_required_document_names": revision_required_document_names,
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
        status__in=[Application.Status.APPROVED, Application.Status.COMPLETED],
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