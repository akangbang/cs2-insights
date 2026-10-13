import pytest

from cs2_insights.sharecode import ShareCode, decode, encode, is_share_code

# Published example from the csgo-sharecode library.
KNOWN_CODE = "CSGO-GADqf-jjyJ8-cSP2r-smZRo-TO2xK"
KNOWN_VALUES = ShareCode(
    match_id=3230642215713767580,
    outcome_id=3230647599455273103,
    tv_port=55788,
)


def test_decode_known_code():
    assert decode(KNOWN_CODE) == KNOWN_VALUES


def test_encode_known_values():
    assert encode(KNOWN_VALUES) == KNOWN_CODE


def test_round_trip():
    values = ShareCode(match_id=123456789012345678, outcome_id=987654321098765432, tv_port=12345)
    assert decode(encode(values)) == values


def test_surrounding_spaces_ignored():
    assert decode(f"  {KNOWN_CODE}\n") == KNOWN_VALUES


@pytest.mark.parametrize(
    "text",
    [
        "",
        "CSGO-GADqf-jjyJ8-cSP2r-smZRo",  # too short
        "CSGO-GADqf-jjyJ8-cSP2r-smZRo-TO2x0",  # 0 isn't in the alphabet
        "GADqf-jjyJ8-cSP2r-smZRo-TO2xK",  # missing prefix
        "https://steamcommunity.com/id/s1mple",
    ],
)
def test_rejects_invalid(text):
    assert not is_share_code(text)
    with pytest.raises(ValueError):
        decode(text)
