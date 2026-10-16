from django import forms
from apps.applicants.models import Applicant
from apps.franchises.models import Vehicle


class ApplicantForm(forms.ModelForm):
    class Meta:
        model = Applicant
        fields = ["first_name", "middle_name", "last_name", "address", "contact_number", "email"]
        labels = {
            "first_name": "First Name",
            "middle_name": "Middle Name",
            "last_name": "Last Name",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["plate_number", "engine_number", "chassis_number", "make", "model", "color"]

    def clean(self):
        cleaned_data = super().clean()
        plate = cleaned_data.get("plate_number")
        engine = cleaned_data.get("engine_number")
        chassis = cleaned_data.get("chassis_number")

        qs = Vehicle.objects.all()
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if plate and qs.filter(plate_number=plate).exists():
            self.add_error("plate_number", "A vehicle with this plate number is already registered.")
        if engine and qs.filter(engine_number=engine).exists():
            self.add_error("engine_number", "A vehicle with this engine number is already registered.")
        if chassis and qs.filter(chassis_number=chassis).exists():
            self.add_error("chassis_number", "A vehicle with this chassis number is already registered.")
        return cleaned_data


class RenewalLookupForm(forms.Form):
    franchise_number = forms.CharField(label="Franchise Number", max_length=30)
    last_name_confirm = forms.CharField(
        label="Last Name of the Franchise Holder",
        max_length=100,
        help_text="Enter your last name exactly as registered, e.g. Dela Cruz.",
    )