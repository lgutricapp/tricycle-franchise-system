from django.urls import path
from django.contrib.auth import views as auth_views
from django_ratelimit.decorators import ratelimit
from .views import AccountLoginView

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        ratelimit(key="ip", rate="5/m", block=True)(
            AccountLoginView.as_view(template_name="accounts/login.html")
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]