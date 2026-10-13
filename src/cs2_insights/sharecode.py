"""Decode and encode CS2 match share codes (CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx).

A share code packs three numbers the game coordinator needs to find a match's demo:
the match ID, the outcome (reservation) ID and the TV port.
"""

import re
from typing import NamedTuple

DICTIONARY = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"
SHARE_CODE_PATTERN = re.compile(
    rf"CSGO(-[{DICTIONARY}]{{5}}){{5}}"
)


class ShareCode(NamedTuple):
    match_id: int
    outcome_id: int
    tv_port: int


def is_share_code(text: str) -> bool:
    return SHARE_CODE_PATTERN.fullmatch(text.strip()) is not None


def decode(code: str) -> ShareCode:
    """Turn a share code into its match ID, outcome ID and TV port.

    Raises ValueError if the text isn't a valid share code.
    """
    code = code.strip()
    if not is_share_code(code):
        raise ValueError("That isn't a CS2 match share code (CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx).")

    chars = code.removeprefix("CSGO").replace("-", "")
    number = 0
    for char in reversed(chars):
        number = number * len(DICTIONARY) + DICTIONARY.index(char)

    raw = number.to_bytes(18, "big")
    return ShareCode(
        match_id=int.from_bytes(raw[0:8], "little"),
        outcome_id=int.from_bytes(raw[8:16], "little"),
        tv_port=int.from_bytes(raw[16:18], "little"),
    )


def encode(share_code: ShareCode) -> str:
    """Inverse of decode()."""
    raw = (
        share_code.match_id.to_bytes(8, "little")
        + share_code.outcome_id.to_bytes(8, "little")
        + share_code.tv_port.to_bytes(2, "little")
    )
    number = int.from_bytes(raw, "big")

    chars = []
    for _ in range(25):
        number, index = divmod(number, len(DICTIONARY))
        chars.append(DICTIONARY[index])
    body = "".join(chars)
    return "CSGO-" + "-".join(body[i : i + 5] for i in range(0, 25, 5))
