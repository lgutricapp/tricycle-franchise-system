from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.applications.models import Application
from apps.audit.services import log_action
from apps.franchises.models import Franchise
from .forms import AnnouncementForm
from .models import Notification
from .services import (
    send_sms, send_email_notification, notify_applicant, notify_franchise_holder,
)

MAX_MESSAGE_LENGTH = 1000


@role_required(User.Role.STAFF)
def send_bulk_notification(request):
    """Global announcements to every franchise holder, plus the full message history."""
    if request.method == "POST":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            channel = form.cleaned_data["channel"]
            message = form.cleaned_data["message"]
            sent_count = 0

            for franchise in Franchise.objects.select_related("holder"):
                holder = franchise.holder
                if channel in ("SMS", "BOTH") and holder.contact_number:
                    send_sms(holder.contact_number, message, sent_by=request.user, franchise=franchise)
                    sent_count += 1
                if channel in ("EMAIL", "BOTH") and holder.email:
                    send_email_notification(
                        holder.email, "LGU Announcement", message, sent_by=request.user, franchise=franchise,
                    )
                    sent_count += 1

            log_action(request.user, "announcement_sent", None, {"channel": channel, "messages_sent": sent_count})
            messages.success(request, f"Announcement sent: {sent_count} message(s).")
            return redirect("notifications:bulk_send")
    else:
        form = AnnouncementForm()

    history = Notification.objects.select_related("sent_by").order_by("-sent_at")
    page = Paginator(history, 15).get_page(request.GET.get("page"))
    return render(request, "notifications/bulk_send.html", {"form": form, "page": page})


def _read_message(request):
    """Returns (message, error). Exactly one of them is None."""
    message = request.POST.get("message", "").strip()
    if not message:
        return None, "Please enter a message before sending."
    if len(message) > MAX_MESSAGE_LENGTH:
        return None, f"Message is too long (maximum {MAX_MESSAGE_LENGTH} characters)."
    return message, None


def _report_results(request, results, recipient_name):
    if not results:
        messages.error(request, f"{recipient_name} has no contact number or email on file.")
        return False
    if any(r.delivery_status == Notification.DeliveryStatus.FAILED for r in results):
        messages.warning(request, f"The message to {recipient_name} could not be delivered on every channel. See the notification history.")
        return True
    channels = " and ".join("SMS" if r.channel == Notification.Channel.SMS else "email" for r in results)
    messages.success(request, f"Message sent to {recipient_name} by {channels}.")
    return True


@role_required(User.Role.STAFF)
def send_to_applicant(request, reference_code):
    application = get_object_or_404(
        Application.objects.select_related("applicant"),
        reference_code=reference_code,
        status__in=[Application.Status.APPROVED, Application.Status.COMPLETED],
    )

    if request.method == "POST":
        message, error = _read_message(request)
        if error:
            messages.error(request, error)
        else:
            results = notify_applicant(
                application,
                message_sms=message,
                message_email_subject="Update on your franchise application",
                message_email_body=message,
                actor=request.user,
            )
            if _report_results(request, results, application.applicant.full_name):
                log_action(request.user, "message_sent", application, {
                    "recipient": application.applicant.full_name,
                    "channels": [r.channel for r in results],
                })

    if application.type == Application.ApplicationType.RENEWAL:
        return redirect("staff_applications:approved_renewals_list")
    return redirect("staff_applications:approved_list")


@role_required(User.Role.STAFF)
def send_to_holder(request, franchise_number):
    franchise = get_object_or_404(
        Franchise.objects.select_related("holder"), franchise_number=franchise_number
    )

    if request.method == "POST":
        message, error = _read_message(request)
        if error:
            messages.error(request, error)
        else:
            results = notify_franchise_holder(
                franchise, message, email_subject="Message from the LGU", actor=request.user,
            )
            if _report_results(request, results, franchise.holder.full_name):
                log_action(request.user, "message_sent", franchise, {
                    "recipient": franchise.holder.full_name,
                    "channels": [r.channel for r in results],
                })

    return redirect("franchises:detail", franchise_number=franchise.franchise_number)