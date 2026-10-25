from django.core.validators import RegexValidator


NAME_VALIDATOR = RegexValidator(
    regex=r"^[^\W\d_]+(?: +[^\W\d_]+)*$",
    message="Use letters and spaces only.",
)
CONTACT_NUMBER_VALIDATOR = RegexValidator(
    regex=r"^[0-9]{11}$",
    message="Enter an 11-digit contact number using numbers only.",
)
