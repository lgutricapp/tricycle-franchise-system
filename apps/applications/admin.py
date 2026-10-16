from django.contrib import admin
from .models import Application, StatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("status", "changed_by", "changed_at", "remarks")
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("reference_code", "applicant", "vehicle", "type", "status", "submitted_at")
    list_filter = ("type", "status")
    search_fields = ("reference_code", "applicant__full_name")
    readonly_fields = ("reference_code",)
    inlines = [StatusHistoryInline]