import pytest
from cryptography.fernet import Fernet

from cs2_insights import secretbox

KEY = Fernet.generate_key().decode()


def test_round_trip_and_marker():
    stored = secretbox.encrypt("AAAA-AAAAA-AAAA", KEY)
    assert stored.startswith("enc1:") and "AAAA-AAAAA-AAAA" not in stored
    assert secretbox.is_encrypted(stored) and not secretbox.is_encrypted("AAAA-AAAAA-AAAA")
    assert secretbox.decrypt(stored, KEY) == "AAAA-AAAAA-AAAA"


def test_wrong_key_and_plain_text_fail_clearly():
    stored = secretbox.encrypt("secret", KEY)
    with pytest.raises(ValueError, match="isn't the key"):
        secretbox.decrypt(stored, Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="isn't encrypted"):
        secretbox.decrypt("secret", KEY)


def test_missing_key_explains_how_to_make_one(monkeypatch):
    monkeypatch.setattr(secretbox, "load_dotenv", lambda: None)
    monkeypatch.delenv(secretbox.KEY_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match="--new-key"):
        secretbox.encrypt("secret")


def test_new_key_command_prints_a_usable_key(capsys):
    assert secretbox.main(["--new-key"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    key = line.split("=", 1)[1]
    assert secretbox.decrypt(secretbox.encrypt("x", key), key) == "x"
