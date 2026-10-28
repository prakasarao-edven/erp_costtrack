import json
import os
import subprocess

import pytest
import requests


def _base():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
    return url.rstrip("/") + "/api"


BASE = _base()


@pytest.fixture(scope="session")
def tokens():
    out = subprocess.run(["python3", "/app/scripts/test_users.py", "--tokens"], capture_output=True, text=True, timeout=120).stdout
    return json.loads(out)


class Client:
    def __init__(self, token):
        self.h = {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, p, **kw):
        return requests.get(BASE + p, headers=self.h, timeout=30, **kw)

    def post(self, p, json=None):
        return requests.post(BASE + p, headers=self.h, json=json, timeout=30)

    def put(self, p, json=None):
        return requests.put(BASE + p, headers=self.h, json=json, timeout=30)

    def patch(self, p, json=None):
        return requests.patch(BASE + p, headers=self.h, json=json, timeout=30)

    def delete(self, p):
        return requests.delete(BASE + p, headers=self.h, timeout=30)


@pytest.fixture(scope="session")
def c(tokens):
    return {r: Client(v["token"]) for r, v in tokens.items()} | {"anon": Client(None)}


@pytest.fixture(scope="session")
def master(c):
    return c["admin"].get("/master").json()


@pytest.fixture(scope="session")
def crew_a(master):
    return next(x["id"] for x in master["crews"] if x["name"].startswith("Crew-A"))


@pytest.fixture(scope="session")
def crew_b(master):
    return next(x["id"] for x in master["crews"] if x["name"].startswith("Crew-B"))
