from mjtutor.koromo import (
    decode_paipu_account_id,
    encode_paipu_account_id,
    extract_koromo_player_id,
    extract_paipu_uuid,
)


def test_koromo_player_id_round_trip() -> None:
    player_id = 1_355_604
    encoded = encode_paipu_account_id(player_id)

    assert encoded == 93_787_137
    assert decode_paipu_account_id(encoded) == player_id


def test_extracts_player_from_paipu_viewer_suffix() -> None:
    url = (
        "https://game.maj-soul.com/1/"
        "?paipu=260618-f15dd885-5509-44f3-b9ee-2f65e4c40a82_a93787137"
    )

    assert extract_koromo_player_id(url) == 1_355_604
    assert (
        extract_koromo_player_id("https://game.maj-soul.com/1/?paipu=260618-example")
        is None
    )


def test_extracts_uuid_without_viewer_suffix() -> None:
    assert (
        extract_paipu_uuid(
            "https://game.maj-soul.com/1/?paipu=260618-example_a93787137"
        )
        == "260618-example"
    )
    assert extract_paipu_uuid("https://example.com/") is None
