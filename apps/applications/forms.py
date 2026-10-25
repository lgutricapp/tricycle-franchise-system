from django import forms
from apps.applicants.models import Applicant
from apps.core.validators import CONTACT_NUMBER_VALIDATOR, NAME_VALIDATOR
from apps.franchises.models import Vehicle


class ApplicantForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=100,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={"data-name-input": "true", "title": "Use letters and spaces only."}),
    )
    middle_name = forms.CharField(
        max_length=100,
        required=False,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={"data-name-input": "true", "title": "Use letters and spaces only."}),
    )
    last_name = forms.CharField(
        max_length=100,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={"data-name-input": "true", "title": "Use letters and spaces only."}),
    )
    contact_number = forms.CharField(
        max_length=11,
        validators=[CONTACT_NUMBER_VALIDATOR],
        widget=forms.TextInput(attrs={
            "inputmode": "numeric",
            "maxlength": "11",
            "pattern": "[0-9]{11}",
            "data-contact-number": "true",
            "title": "Enter an 11-digit contact number using numbers only.",
        }),
    )

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


class RenewalOTPForm(forms.Form):
    code = forms.CharField(
        label="One-time password",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric",
            "autocomplete": "one-time-code",
            "pattern": "[0-9]{6}",
            "maxlength": "6",
        }),
        error_messages={"min_length": "Enter the 6-digit code sent to the franchise owner's phone."},
    )

    def clean_code(self):
        code = self.cleaned_data["code"]
        if not code.isascii() or not code.isdigit():
            raise forms.ValidationError("Enter the 6-digit code sent to the franchise owner's phone.")
        return code


class PolicyAcceptanceForm(forms.Form):
    accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        error_messages={"required": "You must agree to the Terms & Conditions and acknowledge the Privacy Policy."},
    )