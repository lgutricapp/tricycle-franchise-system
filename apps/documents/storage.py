import json
import mimetypes
import re
import time

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone


class GoogleDriveStorage(Storage):
    token_url = "https://oauth2.googleapis.com/token"
    api_url = "https://www.googleapis.com/drive/v3/files"
    upload_url = "https://www.googleapis.com/upload/drive/v3/files"
    timeout = 30

    def __init__(self):
        self.local_storage = FileSystemStorage()
        self._access_token = None
        self._token_expires_at = 0

    def _save(self, name, content):
        folder_id = self._folder_id_for_name(name)
        if not folder_id:
            raise OSError("Google Drive folder ID is not configured.")

        filename = name.rsplit("/", 1)[-1]
        metadata = {"name": filename, "parents": [folder_id]}
        mime_type = getattr(content, "content_type", None) or mimetypes.guess_type(filename)[0]
        files = {
            "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (filename, content, mime_type or "application/octet-stream"),
        }
        response = self._request(
            "post",
            self.upload_url,
            params={"uploadType": "multipart", "fields": "id"},
            files=files,
        )
        try:
            file_id = response.json()["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("Google Drive returned an invalid upload response.") from error
        return f"drive/{file_id}"

    def _folder_id_for_name(self, name):
        parts = name.split("/", 2)
        if len(parts) != 3 or parts[0] != "applications" or not parts[1].isdigit():
            return settings.GOOGLE_DRIVE_FOLDER_ID

        from apps.applications.models import Application
        from apps.applicants.models import Applicant

        application = Application.objects.only("applicant_id").get(pk=parts[1])
        with transaction.atomic():
            applicant = Applicant.objects.select_for_update().get(pk=application.applicant_id)
            if applicant.google_drive_folder_id:
                return applicant.google_drive_folder_id

            folder_name = (
                f"{applicant.first_name} {applicant.last_name} "
                f"{timezone.localdate().isoformat()}"
            ).strip()
            if not folder_name:
                raise OSError("Cannot create a Google Drive folder without an applicant name.")
            parent_id = settings.GOOGLE_DRIVE_FOLDER_ID
            if not parent_id:
                raise OSError("Google Drive parent folder ID is not configured.")

            response = self._request(
                "post",
                self.api_url,
                params={"fields": "id"},
                json={
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
            )
            try:
                applicant.google_drive_folder_id = response.json()["id"]
            except (KeyError, TypeError, ValueError) as error:
                raise OSError("Google Drive returned an invalid folder response.") from error
            applicant.save(update_fields=["google_drive_folder_id"])
            return applicant.google_drive_folder_id

    def _open(self, name, mode="rb"):
        if not self._is_drive_name(name):
            return self.local_storage.open(name, mode)
        if mode not in ("r", "rb"):
            raise ValueError("Google Drive documents can only be opened for reading.")

        file_id = self._drive_id(name)
        metadata = self._request(
            "get",
            f"{self.api_url}/{file_id}",
            params={"fields": "name"},
        )
        try:
            filename = metadata.json()["name"]
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("Google Drive returned invalid document metadata.") from error
        response = self._request(
            "get",
            f"{self.api_url}/{file_id}",
            params={"alt": "media"},
        )
        file_content = ContentFile(response.content, name=filename)
        return file_content

    def _delete(self, name):
        if not self._is_drive_name(name):
            self.local_storage.delete(name)
            return
        file_id = self._drive_id(name)
        self._request("delete", f"{self.api_url}/{file_id}", allow_not_found=True)

    def exists(self, name):
        if not self._is_drive_name(name):
            return self.local_storage.exists(name)
        file_id = self._drive_id(name)
        response = self._request(
            "get",
            f"{self.api_url}/{file_id}",
            params={"fields": "id"},
            allow_not_found=True,
        )
        return response is not None

    def size(self, name):
        if not self._is_drive_name(name):
            return self.local_storage.size(name)
        file_id = self._drive_id(name)
        response = self._request(
            "get",
            f"{self.api_url}/{file_id}",
            params={"fields": "size"},
        )
        try:
            return int(response.json()["size"])
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("Google Drive returned an invalid file size.") from error

    def url(self, name):
        return reverse("protected_media", kwargs={"path": name})

    @staticmethod
    def _is_drive_name(name):
        return name.startswith("drive/")

    @staticmethod
    def _drive_id(name):
        parts = name.split("/", 2)
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[1]):
            raise FileNotFoundError("Invalid Google Drive document reference.")
        return parts[1]

    def _request(self, method, url, allow_not_found=False, **kwargs):
        headers = {"Authorization": f"Bearer {self._get_access_token()}"}
        try:
            response = requests.request(
                method, url, headers=headers, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as error:
            raise OSError("Google Drive request failed.") from error

        if response.status_code == 404 and allow_not_found:
            return None
        if not response.ok:
            if response.status_code == 404:
                raise FileNotFoundError("Google Drive document was not found.")
            details = self._google_error_details(response)
            suffix = f" ({details})" if details else ""
            raise OSError(
                f"Google Drive request failed with HTTP {response.status_code}{suffix}."
            )
        return response

    @staticmethod
    def _google_error_details(response):
        try:
            error = response.json().get("error", {})
        except (AttributeError, TypeError, ValueError):
            return ""

        details = []
        status = error.get("status")
        if isinstance(status, str) and re.fullmatch(r"[A-Z_]+", status):
            details.append(status)

        errors = error.get("errors", [])
        if isinstance(errors, list):
            for item in errors:
                reason = item.get("reason") if isinstance(item, dict) else None
                if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", reason):
                    if reason not in details:
                        details.append(reason)
                if len(details) >= 3:
                    break
        return ", ".join(details)

    def _get_access_token(self):
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        credentials = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": settings.GOOGLE_DRIVE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }
        if not all(credentials[key] for key in ("client_id", "client_secret", "refresh_token")):
            raise OSError(
                "Google Drive credentials are missing. Configure the Google OAuth "
                "client and Drive refresh token."
            )

        try:
            response = requests.post(self.token_url, data=credentials, timeout=self.timeout)
        except requests.RequestException as error:
            raise OSError("Google OAuth token request failed.") from error
        if not response.ok:
            raise OSError(f"Google OAuth token request failed with HTTP {response.status_code}.")

        try:
            token_data = response.json()
            self._access_token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("Google OAuth returned an invalid access token response.") from error

        self._token_expires_at = time.monotonic() + max(expires_in - 60, 0)
        return self._access_token
