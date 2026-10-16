from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.franchises.models import Franchise
from apps.notifications.services import send_sms, send_email_notification

REMINDER_THRESHOLDS_DAYS = [90, 60, 30]


class Command(BaseCommand):
    help = "Send reminder notifications to franchise holders whose franchise is approaching expiration."

    def handle(self, *args, **options):
        today = timezone.now().date()
        sent_count = 0

        for days_out in REMINDER_THRESHOLDS_DAYS:
            target_date = today + timedelta(days=days_out)
            franchises = Franchise.objects.select_related("holder").filter(
                status=Franchise.Status.ACTIVE, expiration_date=target_date
            )

            for franchise in franchises:
                message = (
                    f"Reminder: Your tricycle franchise {franchise.franchise_number} "
                    f"expires on {franchise.expiration_date:%B %d, %Y} ({days_out} days from now). "
                    f"Please renew online or visit the LGU office."
                )
                if franchise.holder.contact_number:
                    send_sms(franchise.holder.contact_number, message, franchise=franchise)
                    sent_count += 1
                if franchise.holder.email:
                    send_email_notification(
                        franchise.holder.email, "Franchise Expiration Reminder", message, franchise=franchise,
                    )
                    sent_count += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent_count} expiration reminder notifications."))