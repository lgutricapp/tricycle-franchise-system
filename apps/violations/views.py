from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django import forms
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.audit.services import log_action
from apps.franchises.models import Franchise
from .models import Violation


class ViolationForm(forms.ModelForm):
    class Meta:
        model = Violation
        fields = [
            "violation_type", "date", "location", "details",
            "penalty_amount", "status", "settlement_date", "remarks", "evidence_file",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "settlement_date": forms.DateInput(attrs={"type": "date"}),
            "details": forms.Textarea(attrs={"rows": 2}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }


@role_required(User.Role.STAFF)
def add_violation(request, franchise_number):
    franchise = get_object_or_404(Franchise, franchise_number=franchise_number)

    if request.method == "POST":
        form = ViolationForm(request.POST, request.FILES)
        if form.is_valid():
            violation = form.save(commit=False)
            violation.franchise = franchise
            violation.save()
            log_action(request.user, "violation_recorded", violation, {"franchise": franchise.franchise_number})
            messages.success(request, "Violation recorded.")
            return redirect("franchises:detail", franchise_number=franchise.franchise_number)
    else:
        form = ViolationForm(initial={"status": Violation.Status.UNSETTLED})

    return render(request, "violations/add_violation.html", {"form": form, "franchise": franchise})


@role_required(User.Role.STAFF)
def settle_violation(request, violation_id):
    violation = get_object_or_404(Violation, id=violation_id)
    if request.method == "POST":
        violation.status = Violation.Status.SETTLED
        from django.utils import timezone
        violation.settlement_date = timezone.now().date()
        violation.save()
        log_action(request.user, "violation_settled", violation, {"franchise": violation.franchise.franchise_number})
        messages.success(request, "Violation marked as settled.")
    return redirect("franchises:detail", franchise_number=violation.franchise.franchise_number)