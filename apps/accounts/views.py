from django.contrib.auth.views import LoginView
from django.shortcuts import render
from django.urls import reverse


class AccountLoginView(LoginView):
    def get_default_redirect_url(self):
        user = self.request.user
        if user.is_superuser or user.role in {
            user.Role.STAFF,
            user.Role.SUPER_ADMIN,
        }:
            return reverse("core:dashboard")
        return super().get_default_redirect_url()
