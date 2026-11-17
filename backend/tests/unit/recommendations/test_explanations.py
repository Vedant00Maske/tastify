from app.domains.recommendations import explanations

OPEN, CLOSE = chr(0x201C), chr(0x201D)


def test_shared_genres_orders_by_common_strength_then_name() -> None:
    seed = {"rock": 0.9, "grunge": 0.5, "pop": 0.4, "indie": 0.5}
    other = {"rock": 0.3, "grunge": 0.6, "indie": 0.5, "jazz": 1.0}
    assert explanations.shared_genres(seed, other, limit=3) == ["grunge", "indie", "rock"]
    assert explanations.shared_genres(seed, {"jazz": 1.0}) == []


def test_similar_track_reason_states_the_evidence() -> None:
    reason = explanations.similar_track_reason("Creep", 0.912, ["alternative rock", "britpop"])
    assert reason == (
        f"Shares alternative rock and britpop with {OPEN}Creep{CLOSE} (similarity 0.91)"
    )


def test_similar_track_reason_mentions_same_artist_and_falls_back_to_decade() -> None:
    reason = explanations.similar_track_reason(
        "Creep", 0.8, [], same_artist_name="Radiohead", same_decade=1990
    )
    assert reason == (
        f"Also by Radiohead; from the same decade (1990s) as {OPEN}Creep{CLOSE} (similarity 0.80)"
    )
    assert explanations.similar_track_reason("Creep", 0.5, []).startswith("Similar overall")


def test_other_reasons() -> None:
    assert explanations.similar_artist_reason("Radiohead", 0.9, ["art rock"]) == (
        "By an artist similar to Radiohead (similarity 0.90); shares art rock"
    )
    assert explanations.genre_reason("jazz", 0.75, 1234) == (
        "Popular jazz track (1,234 listeners; genre match 0.75)"
    )
    assert explanations.popular_reason(10, 14) == "Played by 10 listeners in the last 14 days"
    assert explanations.trending_reason(25, 3.0, 3) == (
        f"Listeners up 3.0{chr(0x00D7)} in the last 3 days (25 recent listeners)"
    )
