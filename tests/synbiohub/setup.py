"""Completes the first-run setup of the throwaway SynBioHub in docker-compose.yml and creates the
test account the integration tests sign in with.

    docker compose -p sbhqa -f tests/synbiohub/docker-compose.yml up -d
    python tests/synbiohub/setup.py
    BOB_TEST_SYNBIOHUB=http://127.0.0.1:7777 pytest tests/test_synbiohub.py
"""

import sys
import time

import requests

URL = "http://127.0.0.1:7777"
EMAIL, PASSWORD = "bobtest@lab.test", "bob-sbh-test-2026"


def main() -> int:
    for _ in range(60):
        try:
            if requests.get(URL + "/", allow_redirects=False, timeout=5).status_code:
                break
        except requests.ConnectionError:
            time.sleep(2)
    form = {
        "instanceName": "BOB test SynBioHub", "color": "#D25627", "frontPageText": "Test instance for BOB", "allowPublicSignup": "on",
        "instanceURL": URL + "/", "uriPrefix": URL + "/", "virtuosoINI": "/etc/virtuoso-opensource-7/virtuoso.ini", "virtuosoDB": "/virtuoso",
        "userName": "bobtest", "userFullName": "BOB Test", "affiliation": "", "userEmail": EMAIL,
        "userPassword": PASSWORD, "userPasswordConfirm": PASSWORD, "authProvider": "",
    }
    r = requests.post(URL + "/setup", files={k: (None, v) for k, v in form.items()}, allow_redirects=False, timeout=60)
    if r.status_code not in (200, 302):
        print("setup failed:", r.status_code, r.text[:300])
        return 1
    token = requests.post(URL + "/login", data={"email": EMAIL, "password": PASSWORD}, headers={"Accept": "text/plain"}, timeout=30)
    print("test account ready" if token.ok else f"sign-in failed: {token.status_code} {token.text[:200]}")
    return 0 if token.ok else 1


if __name__ == "__main__":
    sys.exit(main())
