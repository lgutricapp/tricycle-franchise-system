from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "target", "timestamp")
    list_filter = ("action",)
    readonly_fields = ("actor", "action", "timestamp", "details", "content_type", "object_id")

    def has_add_permission(self, request):
        return False  # audit logs are written by the system, never created by hand

    def has_change_permission(self, request, obj=None):
        return False  # append-only — no editing history after the fact