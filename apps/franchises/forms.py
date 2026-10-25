from django import forms

from apps.core.validators import CONTACT_NUMBER_VALIDATOR, NAME_VALIDATOR
from .models import Franchise, FranchiseHolder


class ManualHolderForm(forms.ModelForm):
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
        model = FranchiseHolder
        fields = ["first_name", "middle_name", "last_name", "address", "contact_number", "email"]
        labels = {
            "first_name": "First Name",
            "middle_name": "Middle Name",
            "last_name": "Last Name",
            "contact_number": "Contact Number",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        first = cleaned.get("first_name")
        last = cleaned.get("last_name")
        contact = cleaned.get("contact_number")
        if first and last and contact and FranchiseHolder.objects.filter(
            first_name__iexact=first, last_name__iexact=last, contact_number=contact,
        ).exists():
            self.add_error(
                "contact_number",
                "A franchise holder with the same name and contact number is already registered.",
            )
        return cleaned


class ManualFranchiseForm(forms.ModelForm):
    class Meta:
        model = Franchise
        fields = ["franchise_number", "date_issued", "expiration_date"]
        labels = {"date_issued": "Date Issued", "expiration_date": "Expiration Date"}
        widgets = {
            "date_issued": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "expiration_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def clean_franchise_number(self):
        number = (self.cleaned_data.get("franchise_number") or "").strip()
        if "/" in number or "\\" in number:
            raise forms.ValidationError("Franchise number cannot contain slashes. Use a dash instead.")
        if Franchise.objects.filter(franchise_number__iexact=number).exists():
            raise forms.ValidationError(
                "Franchise number already exists. Please enter a different franchise number."
            )
        return number

    def clean(self):
        cleaned = super().clean()
        issued = cleaned.get("date_issued")
        expires = cleaned.get("expiration_date")
        if issued and expires and expires <= issued:
            self.add_error("expiration_date", "Expiration date must be after the date issued.")
        return cleaned