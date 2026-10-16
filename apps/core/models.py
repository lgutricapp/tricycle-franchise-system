from django.db import models


class SystemConfiguration(models.Model):
    block_renewal_on_unsettled_violations = models.BooleanField(default=False)

    class Meta:
        verbose_name = "System Configuration"
        verbose_name_plural = "System Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row (singleton pattern)
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "System Configuration"