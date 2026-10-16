from django.urls import path
from . import views

app_name = "staff_applications"

urlpatterns = [
    path("", views.staff_application_list, name="list"),
    path("new/", views.new_applications_list, name="new_list"),
    path("renewals/", views.renewal_applications_list, name="renewal_list"),
    path("new/queue/", views.new_application_queue, name="new_queue"),
    path("renewals/queue/", views.renewal_queue, name="renewal_queue"),
    path("approved/", views.approved_applications_list, name="approved_list"),
    path("approved-renewals/", views.approved_renewals_list, name="approved_renewals_list"),
    path("rejected/", views.rejected_applications_list, name="rejected_list"),
    path("summary/<str:reference_code>/", views.application_summary, name="summary"),
    path("<str:reference_code>/", views.staff_application_detail, name="detail"),
    path("<str:reference_code>/confirm-franchise-number/", views.confirm_franchise_number, name="confirm_franchise_number"),
]