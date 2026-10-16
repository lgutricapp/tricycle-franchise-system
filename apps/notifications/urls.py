from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("send/", views.send_bulk_notification, name="bulk_send"),
    path("applicant/<str:reference_code>/", views.send_to_applicant, name="send_to_applicant"),
    path("holder/<str:franchise_number>/", views.send_to_holder, name="send_to_holder"),
]