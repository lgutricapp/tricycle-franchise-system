from django.db import models

from apps.core.names import compose_full_name


class FranchiseHolder(models.Model):
    first_name = models.CharField(max_length=100, default="")
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, default="")
    full_name = models.CharField(max_length=255, blank=True, editable=False)
    address = models.TextField()
    contact_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["full_name"]

    def save(self, *args, **kwargs):
        if self.first_name or self.last_name:
            self.full_name = compose_full_name(self.first_name, self.middle_name, self.last_name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


class Vehicle(models.Model):
    plate_number = models.CharField(max_length=20, unique=True)
    engine_number = models.CharField(max_length=50, unique=True)
    chassis_number = models.CharField(max_length=50, unique=True)
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    color = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.plate_number} ({self.make} {self.model})"


class Franchise(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    class Source(models.TextChoices):
        APPLICATION = "APPLICATION", "Online application"
        MANUAL = "MANUAL", "Added manually"

    franchise_number = models.CharField(max_length=30, unique=True)
    holder = models.OneToOneField(FranchiseHolder, on_delete=models.PROTECT, related_name="franchise")
    vehicle = models.OneToOneField(Vehicle, on_delete=models.PROTECT, related_name="franchise")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    date_issued = models.DateField()
    expiration_date = models.DateField(db_index=True)
    source = models.CharField(max_length=15, choices=Source.choices, default=Source.APPLICATION)
    registered_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="franchises_registered",
    )
    registered_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ["-date_issued"]

    def __str__(self):
        return self.franchise_number