"""Steam helpers: parse pasted profile links and walk a player's match history."""

import re
from collections.abc import Iterator
from typing import Literal, NamedTuple
from urllib.parse import urlparse

import requests

from cs2_insights.sharecode import is_share_code

NEXT_CODE_URL = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1"
# Match history authentication codes look like AAAA-AAAAA-AAAA.
AUTH_CODE_PATTERN = re.compile(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{5}-[A-Za-z0-9]{4}")

# Every Steam64 ID is 17 digits and starts with 7656119.
STEAM64_PATTERN = re.compile(r"7656119\d{10}")
# Custom profile URLs use letters, digits, underscores and hyphens.
VANITY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}")
STEAM_HOSTS = {"steamcommunity.com", "www.steamcommunity.com"}


class SteamProfileRef(NamedTuple):
    """What a pasted link points to.

    kind is "steam64" when the ID is already known, or "vanity" when it is a
    custom URL name that still has to be resolved through the Steam API.
    """

    kind: Literal["steam64", "vanity"]
    value: str


def parse_steam_url(text: str) -> SteamProfileRef:
    """Turn a pasted Steam profile link (or bare Steam64 ID) into a SteamProfileRef.

    Raises ValueError with a message that can be shown to the player.
    """
    text = text.strip()
    if not text:
        raise ValueError("Paste your Steam profile link.")

    if STEAM64_PATTERN.fullmatch(text):
        return SteamProfileRef("steam64", text)

    # urlparse only finds the host when a scheme is present.
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)

    if parsed.scheme not in ("http", "https") or (parsed.hostname or "") not in STEAM_HOSTS:
        raise ValueError("That isn't a steamcommunity.com profile link.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("That link doesn't point to a Steam profile.")
    section, identifier = parts[0].lower(), parts[1]

    if section == "profiles":
        if STEAM64_PATTERN.fullmatch(identifier):
            return SteamProfileRef("steam64", identifier)
        raise ValueError(f"'{identifier}' isn't a valid Steam64 ID.")

    if section == "id":
        if VANITY_PATTERN.fullmatch(identifier):
            return SteamProfileRef("vanity", identifier)
        raise ValueError(f"'{identifier}' isn't a valid Steam custom URL.")

    raise ValueError("That link doesn't point to a Steam profile.")


class SteamAPIError(Exception):
    """The Steam Web API refused a request. The message can be shown to the player."""


def get_next_share_code(
    api_key: str,
    steam64: str,
    auth_code: str,
    known_code: str,
    session: requests.Session | None = None,
) -> str | None:
    """Return the share code of the match played after known_code, or None if there isn't one yet."""
    if not STEAM64_PATTERN.fullmatch(steam64):
        raise ValueError(f"'{steam64}' isn't a valid Steam64 ID.")
    if not AUTH_CODE_PATTERN.fullmatch(auth_code.strip()):
        raise ValueError("That isn't a match history authentication code (AAAA-AAAAA-AAAA).")
    if not is_share_code(known_code):
        raise ValueError("That isn't a CS2 match share code.")

    response = (session or requests).get(
        NEXT_CODE_URL,
        params={
            "key": api_key,
            "steamid": steam64,
            "steamidkey": auth_code.strip(),
            "knowncode": known_code.strip(),
        },
        timeout=10,
    )
    if response.status_code == 403:
        raise SteamAPIError("Steam rejected the authentication code or API key.")
    if response.status_code == 412:
        raise SteamAPIError("That share code doesn't belong to this player's match history.")
    if response.status_code == 429:
        raise SteamAPIError("Steam is rate limiting requests; try again shortly.")
    if response.status_code not in (200, 202):
        raise SteamAPIError(f"Steam returned HTTP {response.status_code}.")

    next_code = response.json().get("result", {}).get("nextcode")
    if not next_code or next_code == "n/a":
        return None
    return next_code


def iter_share_codes(
    api_key: str,
    steam64: str,
    auth_code: str,
    known_code: str,
    limit: int | None = None,
    session: requests.Session | None = None,
) -> Iterator[str]:
    """Yield every share code after known_code, oldest first, until Steam has no newer match."""
    current = known_code
    count = 0
    while limit is None or count < limit:
        next_code = get_next_share_code(api_key, steam64, auth_code, current, session=session)
        if next_code is None:
            return
        yield next_code
        current = next_code
        count += 1
