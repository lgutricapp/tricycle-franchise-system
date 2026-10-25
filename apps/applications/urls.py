from django.urls import path
from . import views

app_name = "applications"

urlpatterns = [
    path("new/", views.new_application, name="new"),
    path("submitted/<str:reference_code>/", views.application_submitted, name="submitted"),
    path("renew/", views.renewal_lookup, name="renewal_lookup"),
    path("renew/verify/", views.renewal_verify, name="renewal_verify"),
    path("renew/<str:franchise_number>/", views.renewal_form, name="renewal_form"),
    path("track/", views.track_application, name="track"),
    path("status/<str:reference_code>/", views.application_status, name="status"),
]