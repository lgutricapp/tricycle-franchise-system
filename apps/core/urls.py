from django.urls import path
from . import views


app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/chart-data/", views.monthly_applications_chart_data, name="monthly_applications_data"),
]