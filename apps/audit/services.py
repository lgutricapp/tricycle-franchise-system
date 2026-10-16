from django.contrib.contenttypes.models import ContentType
from .models import AuditLog


def log_action(actor, action, target=None, details=None):
    kwargs = {"actor": actor, "action": action, "details": details or {}}
    if target is not None:
        kwargs["content_type"] = ContentType.objects.get_for_model(target)
        kwargs["object_id"] = target.pk
    return AuditLog.objects.create(**kwargs)