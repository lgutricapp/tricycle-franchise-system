from django.test import TestCase

from .forms import ManualHolderForm


class ManualHolderFormValidationTests(TestCase):
    def setUp(self):
        self.data = {
            "first_name": "Alex",
            "middle_name": "",
            "last_name": "Applicant",
            "address": "Bontoc",
            "contact_number": "09171234567",
            "email": "",
        }

    def test_rejects_numbers_and_symbols_in_names(self):
        for name in ("first_name", "middle_name", "last_name"):
            for invalid_value in ("Alex2", "Alex!"):
                with self.subTest(name=name, value=invalid_value):
                    data = {**self.data, name: invalid_value}
                    self.assertIn(name, ManualHolderForm(data=data).errors)

    def test_requires_exactly_eleven_ascii_digits_for_contact_number(self):
        for invalid_number in ("1234567890", "091712345678", "09171ABC567"):
            with self.subTest(number=invalid_number):
                data = {**self.data, "contact_number": invalid_number}
                self.assertIn("contact_number", ManualHolderForm(data=data).errors)
