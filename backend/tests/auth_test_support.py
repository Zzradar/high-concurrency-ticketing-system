import json
import os
import threading
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
ALLOWED_ORIGIN = os.environ.get("TICKETING_TEST_ORIGIN", "http://localhost:5173")
TEST_PASSWORD = "Ticketing123!"
TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=2,p=1$tUON0+a+tW+XPmzdPL+RoA$"
    "OCRPrfDL//acztJL8FF4AhlFnL7GN03xL4mAsYextRo"
)


def username_for_user(user_id: str) -> str:
    return "it-" + "".join(
        character.lower() if character.isalnum() else "-" for character in user_id
    )


def test_user_values(user_ids) -> str:
    return ", ".join(
        "(" + ", ".join((
            repr(user_id),
            repr(f"Integration user {user_id}"),
            repr(username_for_user(user_id)),
            repr(TEST_PASSWORD_HASH),
            "'ACTIVE'",
        )) + ")"
        for user_id in user_ids
    )


class AuthenticatedClient:
    def __init__(self, username: str = "demo", password: str = TEST_PASSWORD):
        self.username = username
        self.password = password
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self._login_lock = threading.Lock()
        self._logged_in = False

    def _send(self, path, *, method="GET", body=None, raw_body=None, headers=None,
              timeout=30):
        request_headers = dict(headers or {})
        if body is not None or raw_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        data = raw_body
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = Request(
            BASE_URL + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                payload = json.load(response) if response.length != 0 else None
                return response.status, payload, response.headers
        except HTTPError as error:
            try:
                payload = json.load(error)
            except json.JSONDecodeError:
                payload = None
            return error.code, payload, error.headers

    def login(self):
        with self._login_lock:
            if self._logged_in:
                return
            status, payload, _ = self._send(
                "/auth/login",
                method="POST",
                body={"username": self.username, "password": self.password},
                headers={"Origin": ALLOWED_ORIGIN},
            )
            if status != 200:
                raise AssertionError(f"login failed for {self.username}: {status} {payload}")
            self._logged_in = True

    def cookie(self, name: str) -> str | None:
        return next((cookie.value for cookie in self.cookies if cookie.name == name), None)

    def request(self, path, *, method="GET", body=None, raw_body=None, headers=None,
                timeout=30, csrf=True):
        self.login()
        request_headers = dict(headers or {})
        if method.upper() not in ("GET", "HEAD", "OPTIONS"):
            request_headers.setdefault("Origin", ALLOWED_ORIGIN)
            if csrf:
                token = self.cookie("ticketing_csrf")
                if token:
                    request_headers.setdefault("X-CSRF-Token", token)
        return self._send(
            path,
            method=method,
            body=body,
            raw_body=raw_body,
            headers=request_headers,
            timeout=timeout,
        )


_clients = {}
_clients_lock = threading.Lock()


def reset_auth_clients() -> None:
    with _clients_lock:
        _clients.clear()


def client_for(user_id: str = "U-1001") -> AuthenticatedClient:
    username = "demo" if user_id == "U-1001" else username_for_user(user_id)
    with _clients_lock:
        return _clients.setdefault(username, AuthenticatedClient(username))


def anonymous_request(path, *, method="GET", body=None, raw_body=None, headers=None,
                      timeout=30):
    return AuthenticatedClient()._send(
        path,
        method=method,
        body=body,
        raw_body=raw_body,
        headers=headers,
        timeout=timeout,
    )
