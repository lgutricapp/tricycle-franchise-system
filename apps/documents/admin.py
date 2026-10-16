from django.contrib import admin
from .models import DocumentRequirement, ApplicationDocument


@admin.register(DocumentRequirement)
class DocumentRequirementAdmin(admin.ModelAdmin):
    list_display = ("name", "application_type", "required", "active")
    list_filter = ("application_type", "required", "active")


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ("application", "document_requirement", "status", "uploaded_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("application__reference_code",)