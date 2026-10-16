from django.conf import settings
from django.core.mail import send_mail
from django.utils.module_loading import import_string
from .models import Notification
import logging

logger = logging.getLogger(__name__)

def send_sms(to_number, message, sent_by=None, application=None, franchise=None):
    backend_class = import_string(settings.SMS_BACKEND)
    backend = backend_class()
    result = backend.send(to_number, message)

    return Notification.objects.create(
        channel=Notification.Channel.SMS,
        recipient_contact=to_number,
        message=message,
        sent_by=sent_by,
        application=application,
        franchise=franchise,
        delivery_status=Notification.DeliveryStatus.SENT if result["success"] else Notification.DeliveryStatus.FAILED,
    )


def send_email_notification(to_email, subject, message, sent_by=None, application=None, franchise=None):
    if not to_email:
        return None

    try:
        send_mail(
            subject, message, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=False,
        )
        status = Notification.DeliveryStatus.SENT
    except Exception as e:
        logger.warning("Email to %s failed: %s", to_email, e)
        status = Notification.DeliveryStatus.FAILED

    return Notification.objects.create(
        channel=Notification.Channel.EMAIL,
        recipient_contact=to_email,
        message=f"{subject}\n\n{message}",
        sent_by=sent_by,
        application=application,
        franchise=franchise,
        delivery_status=status,
    )

def notify_applicant(application, message_sms=None, message_email_subject=None, message_email_body=None, actor=None):
    """Convenience wrapper: notify an applicant via whichever channels they provided contact info for."""
    results = []
    if message_sms and application.applicant.contact_number:
        results.append(send_sms(
            application.applicant.contact_number, message_sms, sent_by=actor, application=application,
        ))
    if message_email_subject and application.applicant.email:
        results.append(send_email_notification(
            application.applicant.email, message_email_subject, message_email_body or message_sms,
            sent_by=actor, application=application,
        ))
    return results

def notify_franchise_holder(franchise, message, email_subject, actor=None):
    """SMS the holder, and email them too if an email is on file."""
    results = []
    holder = franchise.holder
    if holder.contact_number:
        results.append(send_sms(holder.contact_number, message, sent_by=actor, franchise=franchise))
    if holder.email:
        results.append(send_email_notification(
            holder.email, email_subject, message, sent_by=actor, franchise=franchise,
        ))
    return [r for r in results if r]