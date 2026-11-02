from django.conf import settings
from django.urls import reverse


def tracking_url():
    base = getattr(settings, "SITE_URL", "https://tricycle-franchise-system.onrender.com").rstrip("/")
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


def review_started_message(application):
    kind = "renewal" if application.type == "RENEWAL" else "application"
    return (
        f"{_greeting(application)}, your {kind} is now under review. "
        "Please proceed to the Municipal Mayor's Office and bring your required documents."
    )


def revision_required_message(application):
    return f"{_greeting(application)}, your application requires revision. Please visit {tracking_url()}"


def approved_message(application):
    if application.type == "RENEWAL":
        return (
            f"{_greeting(application)}, your renewal has been approved and your "
            "franchise record has been updated."
        )
    return APPROVED_INSTRUCTIONS_TEMPLATE.format(name=application.applicant.full_name)


def rejected_message(application):
    return (
        f"{_greeting(application)}, your application has been rejected. "
        f"Please visit {tracking_url()} to check on your application"
    )


# Instructions sent automatically when a new application is approved.
APPROVED_INSTRUCTIONS_TEMPLATE = (
    "Good Day Ma'am/Sir {name}, your application has been approved. "
    "Follow the step-by-step process below:\n\n"
    "1. Proceed to the Municipal Treasury Office to pay\n"
    "2. Proceed to Mayor's Office for your permit\n"
    "3. Bring your unit for inspection\n"
    "4. Wait for your permit and stickers to be released"
)