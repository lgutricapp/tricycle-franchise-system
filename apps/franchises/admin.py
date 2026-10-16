from django.contrib import admin
from .models import FranchiseHolder, Vehicle, Franchise


@admin.register(FranchiseHolder)
class FranchiseHolderAdmin(admin.ModelAdmin):
    list_display = ("full_name", "contact_number", "email")
    search_fields = ("full_name", "contact_number")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "make", "model", "color")
    search_fields = ("plate_number", "engine_number", "chassis_number")


@admin.register(Franchise)
class FranchiseAdmin(admin.ModelAdmin):
    list_display = ("franchise_number", "holder", "vehicle", "status", "expiration_date")
    list_filter = ("status",)
    search_fields = ("franchise_number", "holder__full_name", "vehicle__plate_number")