from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applications.forms import VehicleForm
from apps.audit.services import log_action
from apps.documents.models import DocumentRequirement, FranchiseDocument
from apps.documents.services import validate_document_uploads
from .forms import ManualFranchiseForm, ManualHolderForm
from .models import Franchise
from .services import (
    build_franchise_timeline,
    current_franchises_queryset,
    expired_franchises_queryset,
    get_current_documents,
    refresh_franchise_statuses,
)


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def franchise_list(request):
    refresh_franchise_statuses()
    query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")

    franchises = current_franchises_queryset().select_related("holder", "vehicle").order_by("-date_issued")
    if query:
        franchises = franchises.filter(
            Q(franchise_number__icontains=query)
            | Q(holder__full_name__icontains=query)
            | Q(vehicle__plate_number__icontains=query)
        )
    if status_filter:
        franchises = franchises.filter(status=status_filter)

    return render(request, "franchises/franchise_list.html", {
        "franchises": franchises,
        "status_choices": [c for c in Franchise.Status.choices if c[0] != Franchise.Status.EXPIRED],
        "query": query,
        "status_filter": status_filter,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def franchise_detail(request, franchise_number):
    refresh_franchise_statuses()
    franchise = get_object_or_404(
        Franchise.objects.select_related("holder", "vehicle", "registered_by"),
        franchise_number=franchise_number,
    )
    violations = franchise.violations.all()
    applications = franchise.applications.order_by("-created_at")

    return render(request, "franchises/franchise_detail.html", {
        "franchise": franchise,
        "violations": violations,
        "applications": applications,
        "current_documents": get_current_documents(franchise),
    })


@role_required(User.Role.STAFF)
def add_franchise_manually(request):
    requirements = DocumentRequirement.objects.filter(
        active=True,
        application_type__in=[DocumentRequirement.ApplicationType.NEW, DocumentRequirement.ApplicationType.BOTH],
    )
    missing_required_docs = []
    file_errors = []

    if request.method == "POST":
        holder_form = ManualHolderForm(request.POST)
        vehicle_form = VehicleForm(request.POST)
        franchise_form = ManualFranchiseForm(request.POST)
        missing_required_docs, file_errors, valid_files = validate_document_uploads(request.FILES, requirements)

        if (
            holder_form.is_valid() and vehicle_form.is_valid() and franchise_form.is_valid()
            and not missing_required_docs and not file_errors
        ):
            try:
                with transaction.atomic():
                    holder = holder_form.save()
                    vehicle = vehicle_form.save()
                    franchise = franchise_form.save(commit=False)
                    franchise.holder = holder
                    franchise.vehicle = vehicle
                    franchise.status = (
                        Franchise.Status.EXPIRED
                        if franchise.expiration_date < timezone.localdate()
                        else Franchise.Status.ACTIVE
                    )
                    franchise.source = Franchise.Source.MANUAL
                    franchise.registered_by = request.user
                    franchise.save()

                    for req in requirements:
                        if req.id in valid_files:
                            FranchiseDocument.objects.create(
                                franchise=franchise,
                                document_requirement=req,
                                uploaded_file=valid_files[req.id],
                                uploaded_by=request.user,
                            )

                    log_action(request.user, "franchise_added_manually", franchise, {
                        "franchise_number": franchise.franchise_number,
                        "holder": holder.full_name,
                        "documents_uploaded": len(valid_files),
                    })
            except IntegrityError:
                messages.error(
                    request,
                    "Could not save: that franchise number or tricycle detail is already registered. "
                    "Please review the form and try again.",
                )
            else:
                if franchise.status == Franchise.Status.EXPIRED:
                    messages.success(
                        request,
                        f"Franchise {franchise.franchise_number} added for {holder.full_name}. "
                        "It is already expired, so it is listed under Expired Franchises.",
                    )
                    return redirect("franchises:expired")
                messages.success(
                    request,
                    f"Franchise {franchise.franchise_number} added for {holder.full_name}.",
                )
                return redirect("franchises:detail", franchise_number=franchise.franchise_number)
    else:
        holder_form = ManualHolderForm()
        vehicle_form = VehicleForm()
        franchise_form = ManualFranchiseForm()

    recent_manual = Franchise.objects.filter(
        source=Franchise.Source.MANUAL
    ).select_related("holder", "registered_by").order_by("-registered_at", "-id")[:10]

    return render(request, "franchises/add_manual.html", {
        "holder_form": holder_form,
        "vehicle_form": vehicle_form,
        "franchise_form": franchise_form,
        "requirements": requirements,
        "missing_required_docs": missing_required_docs,
        "file_errors": file_errors,
        "recent_manual": recent_manual,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def expired_franchises(request):
    query = request.GET.get("q", "")

    franchises = expired_franchises_queryset().select_related("holder", "vehicle").order_by("-expiration_date")
    if query:
        franchises = franchises.filter(
            Q(franchise_number__icontains=query)
            | Q(holder__full_name__icontains=query)
            | Q(vehicle__plate_number__icontains=query)
        )

    page = Paginator(franchises, 20).get_page(request.GET.get("page"))
    today = timezone.localdate()
    rows = [
        {"franchise": f, "days_expired": max((today - f.expiration_date).days, 0)}
        for f in page
    ]

    return render(request, "franchises/expired_list.html", {
        "rows": rows, "page": page, "query": query,
    })


@role_required(User.Role.STAFF, User.Role.REVIEWER)
def expired_franchise_summary(request, franchise_number):
    # Only expired franchises are served here; anything else returns 404.
    franchise = get_object_or_404(
        expired_franchises_queryset().select_related("holder", "vehicle", "registered_by"),
        franchise_number=franchise_number,
    )
    return render(request, "franchises/_franchise_summary.html", {
        "franchise": franchise,
        "timeline": build_franchise_timeline(franchise),
    })