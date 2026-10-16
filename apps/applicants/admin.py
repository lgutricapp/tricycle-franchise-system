from django.contrib import admin
from .models import Applicant


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "contact_number", "email", "created_at")
    search_fields = ("full_name", "contact_number", "email")