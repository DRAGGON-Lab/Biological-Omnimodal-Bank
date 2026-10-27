"""A client for the SynBioHub API (https://synbiohub.org), limited to what BOB uses: sign-in,
design search and lookup, reading a design's SBOL, the user's collections, and submitting SBOL."""

import base64

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TIMEOUT_S = 30
DESIGN_TYPES = ("ComponentDefinition", "ModuleDefinition")


class SynBioHubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _cipher(secret_key: str) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"bob synbiohub token").derive(secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret_key: str, token: str) -> str:
    return _cipher(secret_key).encrypt(token.encode("utf-8")).decode("ascii")


def unseal(secret_key: str, sealed: str) -> str | None:
    """None when the token was sealed under another secret key; the user then signs in again."""
    try:
        return _cipher(secret_key).decrypt(sealed.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def _request(method: str, url: str, token: str | None = None, accept: str = "application/json", **kw) -> requests.Response:
    headers = {"Accept": accept}
    if token:
        headers["X-authorization"] = token
    try:
        # Redirects are refused, so a SynBioHub answer cannot send BOB on to another host.
        r = requests.request(method, url, headers=headers, timeout=TIMEOUT_S, allow_redirects=False, **kw)
    except requests.RequestException as exc:
        raise SynBioHubError(f"SynBioHub at {url.split('/', 3)[2]} could not be reached ({type(exc).__name__})") from exc
    if r.status_code == 401:
        raise SynBioHubError("SynBioHub asked for a sign-in: " + (r.text.strip()[:200] or "login required"), 401)
    if r.status_code >= 300:
        raise SynBioHubError(f"SynBioHub answered {r.status_code}: {r.text.strip()[:300]}", r.status_code)
    return r


def login(instance: str, email: str, password: str) -> str:
    try:
        r = _request("POST", f"{instance}/login", accept="text/plain", data={"email": email, "password": password})
    except SynBioHubError as exc:
        if exc.status == 401:
            raise SynBioHubError("SynBioHub did not accept that email or user name and password.", 401) from exc
        raise
    token = r.text.strip()
    if not token or " " in token or len(token) > 200:
        raise SynBioHubError("SynBioHub's sign-in answer was not a token.")
    return token


def _entries(r: requests.Response) -> list[dict]:
    try:
        data = r.json()
    except ValueError as exc:
        raise SynBioHubError("SynBioHub's answer was not JSON.") from exc
    return data if isinstance(data, list) else []


def _design(d: dict) -> dict:
    return {
        "uri": d.get("uri", ""),
        "name": d.get("name") or d.get("displayId") or "",
        "display_id": d.get("displayId", ""),
        "description": d.get("description", ""),
        "version": d.get("version", ""),
        "sbol_class": (d.get("type") or "").rsplit("#", 1)[-1],
    }


def search(instance: str, token: str | None, text: str, limit: int = 20) -> list[dict]:
    words = " ".join(text.split())[:200].replace("/", " ").replace("&", " ")
    found = []
    for kind in DESIGN_TYPES:
        path = requests.utils.quote(f"objectType={kind}&{words}", safe="=&")
        r = _request("GET", f"{instance}/search/{path}/", token, params={"offset": 0, "limit": limit})
        found += [{**_design(d), "sbol_class": d.get("type", "").rsplit("#", 1)[-1] or kind} for d in _entries(r)]
    return found[:limit]


def metadata(iri: str, token: str | None) -> dict | None:
    r = _request("GET", f"{iri.rstrip('/')}/metadata", token)
    entries = _entries(r)
    return _design({**entries[0], "uri": iri}) if entries else None


def request_sbol(url: str, token: str | None) -> requests.Response:
    return _request("GET", url, token, accept="text/plain")


def collections(instance: str, token: str) -> list[dict]:
    r = _request("GET", f"{instance}/manage", token)
    return [_design(d) for d in _entries(r) if (d.get("type") or "").endswith("#Collection")]


def submit(instance: str, token: str, sbol: bytes, filename: str, *, collection_id: str | None = None, version: str = "1",
           name: str = "", description: str = "", root_collection: str | None = None, overwrite: bool = False) -> None:
    """A new collection `collection_id`/`version`, or a merge into the existing `root_collection`."""
    if root_collection:
        data = {"rootCollections": root_collection, "overwrite_merge": "3" if overwrite else "2"}
    else:
        data = {"id": collection_id, "version": version, "name": name, "description": description or name, "citations": "", "overwrite_merge": "1" if overwrite else "0"}
    _request("POST", f"{instance}/submit", token, accept="text/plain", data=data, files={"file": (filename, sbol, "application/rdf+xml")})
