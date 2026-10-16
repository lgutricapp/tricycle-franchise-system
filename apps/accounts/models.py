from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Administrator"
        STAFF = "STAFF", "Administrator/Staff"
        REVIEWER = "REVIEWER", "Reviewer"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
    )

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"