"""Encrypt secrets before they're stored, e.g. Steam match-history auth codes.

The key is HALFTIME_SECRET_KEY in .env (never in the database or the repo). Create one with:
    python -m cs2_insights.secretbox --new-key

Encrypted values start with "enc1:" so they can't be mistaken for plain text.
"""

import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

PREFIX = "enc1:"
KEY_VARIABLE = "HALFTIME_SECRET_KEY"


def _fernet(key: str | None = None) -> Fernet:
    if key is None:
        load_dotenv()
        key = os.getenv(KEY_VARIABLE)
    if not key:
        raise RuntimeError(f"{KEY_VARIABLE} isn't set. Create one with: python -m cs2_insights.secretbox --new-key")
    return Fernet(key.encode())


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(text: str, key: str | None = None) -> str:
    return PREFIX + _fernet(key).encrypt(text.encode()).decode()


def decrypt(value: str, key: str | None = None) -> str:
    if not is_encrypted(value):
        raise ValueError("That value isn't encrypted.")
    try:
        return _fernet(key).decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise ValueError(f"Couldn't decrypt: {KEY_VARIABLE} isn't the key this value was encrypted with.") from None


def main(argv: list[str] | None = None) -> int:
    if (argv if argv is not None else sys.argv[1:]) == ["--new-key"]:
        print(f"{KEY_VARIABLE}={Fernet.generate_key().decode()}")
        print("Add that line to .env. Keep it secret, and back it up: losing it makes stored auth codes unreadable.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
