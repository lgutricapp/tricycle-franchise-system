from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("channel", "recipient_contact", "delivery_status", "sent_at", "sent_by")
    list_filter = ("channel", "delivery_status")
    search_fields = ("recipient_contact",)
    readonly_fields = ("sent_at",)