from django.contrib import admin
from .models import Violation


@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ("franchise", "violation_type", "date", "status", "penalty_amount")
    list_filter = ("status",)
    search_fields = ("franchise__franchise_number", "violation_type")