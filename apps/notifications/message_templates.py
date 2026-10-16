from django.conf import settings
from django.urls import reverse


def tracking_url():
    base = getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    return base + reverse("applications:track")


def _greeting(application):
    return f"Good Day Ma'am/Sir {application.applicant.full_name}"


def submission_message(application):
    kind = "renewal" if application.type == "RENEWAL" else "application"
    return (
        f"{_greeting(application)}, your {kind} has been received. "
        f"Your reference code is {application.reference_code}. "
        f"Please keep this code to track your {kind} at {tracking_url()}"
    )


def revision_required_message(application):
    return f"{_greeting(application)}, your application requires revision. Please visit {tracking_url()}"


def approved_message(application):
    return f"{_greeting(application)}, your application has been approved. Please wait for further instructions"


def rejected_message(application):
    return (
        f"{_greeting(application)}, your application has been rejected. "
        f"Please visit {tracking_url()} to check on your application"
    )


# Pre-filled text for the "Send A Message" button on Approved Applications.
# {name} is replaced with the applicant's name.
APPROVED_INSTRUCTIONS_TEMPLATE = (
    "Good Day Ma'am/Sir {name}, your application has been approved. "
    "Follow the step-by-step process below:\n\n"
    "1. Proceed to the Municipal Treasury Office to pay\n"
    "2. Proceed to Mayor's Office for your permit\n"
    "3. Bring your unit for inspection\n"
    "4. Wait for your permit and stickers to be released"
)