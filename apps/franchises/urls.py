from django.urls import path
from . import views

app_name = "franchises"

urlpatterns = [
    path("", views.franchise_list, name="list"),
    path("add/", views.add_franchise_manually, name="add_manual"),
    path("expired/", views.expired_franchises, name="expired"),
    path("expired/<str:franchise_number>/summary/", views.expired_franchise_summary, name="expired_summary"),
    path("<str:franchise_number>/", views.franchise_detail, name="detail"),
]