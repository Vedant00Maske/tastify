import base64
import hashlib
import os
import re
import uuid

import pytest

from app.domains.integrations.providers.base import QuotaExceededError
from app.domains.integrations.providers.listenbrainz import listen_to_item
from app.domains.integrations.providers.musicbrainz import _lucene
from app.domains.integrations.providers.youtube import YouTubeProvider
from app.domains.integrations.service import event_id, export_marker, pkce_pair
from app.domains.integrations.tokens import (
    TokenCipher,
    TokenDecryptionError,
    TokenKeyMissingError,
    _key,
)

USER = uuid.UUID("00000000-0000-4000-8000-000000000001")


def test_tokens_round_trip_and_are_bound_to_their_owner() -> None:
    cipher = TokenCipher(os.urandom(32))
    sealed = cipher.encrypt("secret-access-token", USER, "spotify")
    assert sealed.startswith("v1:")
    assert "secret-access-token" not in sealed
    assert cipher.encrypt("secret-access-token", USER, "spotify") != sealed  # fresh nonce
    assert cipher.decrypt(sealed, USER, "spotify") == "secret-access-token"
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(sealed, uuid.uuid4(), "spotify")  # copied into another user's row
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(sealed, USER, "youtube")
    with pytest.raises(TokenDecryptionError):
        TokenCipher(os.urandom(32)).decrypt(sealed, USER, "spotify")  # another key


@pytest.mark.parametrize("raw", [None, "", "not base64!", base64.b64encode(b"short").decode()])
def test_token_key_must_be_32_bytes_of_base64(raw: str | None) -> None:
    with pytest.raises(TokenKeyMissingError):
        _key(raw)


def test_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()


def test_imported_event_ids_are_stable_and_valid() -> None:
    key = "1700000000:5b1c8b0a-0000-4000-8000-000000000000"
    assert event_id("listenbrainz", key) == event_id("listenbrainz", key)
    assert event_id("listenbrainz", key) != event_id("spotify", key)
    assert len(event_id("spotify", key)) <= 64
    assert re.fullmatch(r"[A-Za-z0-9._:-]+", event_id("youtube", key))
    assert export_marker(USER) == f"[tastify:{USER}]"


def test_listens_prefer_the_mapped_recording() -> None:
    item = listen_to_item(
        {
            "listened_at": 1_700_000_000,
            "recording_msid": "msid-1",
            "track_metadata": {
                "artist_name": "Radiohead",
                "track_name": "Creep",
                "additional_info": {"recording_mbid": "submitted", "isrc": "GBAYE9200070"},
                "mbid_mapping": {"recording_mbid": "mapped"},
            },
        }
    )
    assert item is not None
    assert (item.recording_mbid, item.isrc, item.event_type) == ("mapped", "GBAYE9200070", "play")
    assert item.key == "1700000000:msid-1"
    assert listen_to_item({"listened_at": 1, "track_metadata": {"artist_name": "A"}}) is None


def test_youtube_export_cost_covers_the_worst_case() -> None:
    youtube = YouTubeProvider()
    # 50 new tracks, nothing cached, new playlist: within the default 10,000 units.
    assert youtube.export_cost(50, 50, existing_playlist=False) <= 10_000
    assert youtube.export_cost(2, 0, existing_playlist=True) < youtube.export_cost(2, 2, True)


def test_quota_error_explains_the_shortfall() -> None:
    message = str(QuotaExceededError("YouTube", needed=300, remaining=250))
    assert "300" in message
    assert "250" in message


def test_lucene_syntax_in_queries_is_escaped() -> None:
    assert _lucene('AC/DC "live" (1979)') == 'AC\\/DC \\"live\\" \\(1979\\)'
