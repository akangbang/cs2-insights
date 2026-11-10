"""Sign in through Steam (OpenID 2.0): the player proves which Steam account is theirs, with no email or password.

The browser goes to Steam with `login_url`, and Steam sends it back to `return_to` with a signed reply in
the query string. `verify` trusts nothing in that reply until Steam itself confirms it, so a forged or
replayed link signs nobody in. All that comes back is the Steam ID.
"""

import re
from urllib.parse import urlencode

import requests

ENDPOINT = "https://steamcommunity.com/openid/login"
NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
CLAIMED_ID = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{17})$")
MUST_BE_SIGNED = {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce"}


def login_url(return_to: str) -> str:
    """Where to send the browser to sign in. `return_to` is this app's public address, e.g. https://example.app/."""
    return ENDPOINT + "?" + urlencode({
        "openid.ns": NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": return_to,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    })


def verify(params: dict, return_to: str, post=requests.post) -> str | None:
    """The Steam ID from Steam's reply if Steam confirms it, else None."""
    if params.get("openid.mode") != "id_res" or params.get("openid.ns") != NS:
        return None
    if params.get("openid.op_endpoint") != ENDPOINT or params.get("openid.return_to") != return_to:
        return None
    claimed = params.get("openid.claimed_id", "")
    found = CLAIMED_ID.match(claimed)
    if not found or params.get("openid.identity") != claimed:
        return None
    if not MUST_BE_SIGNED <= set(params.get("openid.signed", "").split(",")):
        return None
    check = {k: v for k, v in params.items() if k.startswith("openid.")} | {"openid.mode": "check_authentication"}
    try:
        reply = post(ENDPOINT, data=check, timeout=10)
    except requests.RequestException:
        return None
    if getattr(reply, "status_code", 200) != 200 or "is_valid:true" not in reply.text.splitlines():
        return None
    return found.group(1)
