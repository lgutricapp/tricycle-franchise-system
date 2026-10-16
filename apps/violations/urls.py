from django.urls import path
from . import views

app_name = "violations"

urlpatterns = [
    path("<str:franchise_number>/add/", views.add_violation, name="add"),
    path("<int:violation_id>/settle/", views.settle_violation, name="settle"),
]