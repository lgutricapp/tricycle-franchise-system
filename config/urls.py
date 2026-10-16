from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("apply/", include("apps.applications.urls")),
    path("staff/applications/", include("apps.applications.staff_urls")),
    path("staff/franchises/", include("apps.franchises.urls")),
    path("staff/violations/", include("apps.violations.urls")),
    path("staff/notifications/", include("apps.notifications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)