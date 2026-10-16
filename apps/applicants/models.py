from django.db import models

from apps.core.names import compose_full_name


class Applicant(models.Model):
    first_name = models.CharField(max_length=100, default="")
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, default="")
    # Built automatically from the three name fields. It stays a stored column so
    # searching, sorting and messages can keep using one display name.
    full_name = models.CharField(max_length=255, blank=True, editable=False)
    address = models.TextField()
    contact_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.first_name or self.last_name:
            self.full_name = compose_full_name(self.first_name, self.middle_name, self.last_name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name