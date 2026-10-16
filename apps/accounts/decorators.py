from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied


def role_required(*allowed_roles):
    """
    Restrict a view to users whose .role is in allowed_roles.
    Super Administrators always pass, regardless of the roles listed.
    Usage: @role_required(User.Role.STAFF, User.Role.SUPER_ADMIN)
    """
    def check(user):
        if not user.is_authenticated:
            return False
        if user.role == "SUPER_ADMIN" or user.is_superuser:
            return True
        if user.role in [r.value if hasattr(r, "value") else r for r in allowed_roles]:
            return True
        raise PermissionDenied
    return user_passes_test(check, login_url="accounts:login")