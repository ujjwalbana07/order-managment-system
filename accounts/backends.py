from django.contrib.auth.backends import ModelBackend
from accounts.services import attempt_login


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get('email', username)
        if not isinstance(email, str) or not isinstance(password, str):
            return None
        return attempt_login(email, password)
