from app.domains.catalogue.resolution import (
    MatchDecision,
    TrackEvidence,
    artist_similarity,
    compare,
    resolve,
)

HALO = TrackEvidence(
    title="Halo",
    artists=("Beyoncé",),
    duration_ms=261_000,
    isrcs=frozenset({"USSM10804556"}),
    album="I Am... Sasha Fierce",
)


def evidence(**overrides: object) -> TrackEvidence:
    fields: dict[str, object] = {
        "title": HALO.title,
        "artists": HALO.artists,
        "duration_ms": HALO.duration_ms,
        "isrcs": frozenset(),
        "album": None,
    }
    fields.update(overrides)
    return TrackEvidence(**fields)  # type: ignore[arg-type]


class TestCompare:
    def test_shared_isrc_with_consistent_duration_links(self) -> None:
        result = compare(evidence(isrcs=frozenset({"USSM10804556"}), duration_ms=262_000), HALO)

        assert result.decision is MatchDecision.LINK
        assert result.method == "isrc"

    def test_shared_isrc_with_very_different_duration_needs_review(self) -> None:
        result = compare(evidence(isrcs=frozenset({"USSM10804556"}), duration_ms=400_000), HALO)

        assert result.decision is MatchDecision.REVIEW

    def test_shared_isrc_with_unrelated_artist_needs_review(self) -> None:
        result = compare(evidence(isrcs=frozenset({"USSM10804556"}), artists=("Metallica",)), HALO)

        assert result.decision is MatchDecision.REVIEW

    def test_exact_title_artist_and_close_duration_link(self) -> None:
        result = compare(evidence(title="HALO", artists=("Beyonce",), duration_ms=262_500), HALO)

        assert result.decision is MatchDecision.LINK
        assert result.method == "metadata"

    def test_album_agreement_raises_confidence(self) -> None:
        without_album = compare(evidence(), HALO)
        with_album = compare(evidence(album="I am... Sasha Fierce"), HALO)

        assert with_album.confidence > without_album.confidence

    def test_featuring_and_remaster_annotations_are_ignored(self) -> None:
        result = compare(evidence(title="Halo (feat. Nobody) - Remastered 2020"), HALO)

        assert result.decision is MatchDecision.LINK

    def test_exact_metadata_without_durations_needs_review(self) -> None:
        result = compare(evidence(duration_ms=None), HALO)

        assert result.decision is MatchDecision.REVIEW

    def test_same_title_and_artist_with_different_duration_is_a_different_recording(self) -> None:
        result = compare(evidence(duration_ms=330_000), HALO)  # e.g. a live or extended version

        assert result.decision is MatchDecision.NO_MATCH

    def test_title_alone_never_matches(self) -> None:
        result = compare(evidence(artists=("Depeche Mode",)), HALO)

        assert result.decision is MatchDecision.NO_MATCH

    def test_near_identical_metadata_needs_review(self) -> None:
        single_ladies = evidence(title="Single Ladies (Put a Ring on It)")
        typo = evidence(title="Single Ladys (Put a Ring on It)")

        assert compare(typo, single_ladies).decision is MatchDecision.REVIEW

    def test_live_version_is_not_linked_to_studio_version(self) -> None:
        result = compare(evidence(title="Halo (Live)"), HALO)

        assert result.decision is not MatchDecision.LINK

    def test_signals_explain_the_decision(self) -> None:
        result = compare(evidence(duration_ms=262_000), HALO)

        assert result.signals["duration_delta_ms"] == 1_000
        assert result.signals["shared_isrc"] is False
        assert result.signals["artist_similarity"] == 1.0


def test_artist_similarity_uses_best_matching_credit() -> None:
    assert artist_similarity(["Jay-Z", "Beyoncé"], ["beyonce"]) == 1.0
    assert artist_similarity(["Metallica"], ["Beyoncé"]) < 0.5
    assert artist_similarity([], ["Beyoncé"]) == 0.0


class TestResolve:
    def test_single_qualifying_candidate_is_linked(self) -> None:
        other = evidence(title="Single Ladies")

        resolution = resolve(evidence(), [("halo", HALO), ("other", other)])

        assert resolution.decision is MatchDecision.LINK
        assert resolution.linked == "halo"

    def test_several_qualifying_candidates_are_ambiguous_and_not_linked(self) -> None:
        duplicate = evidence(duration_ms=260_500)

        resolution = resolve(evidence(), [("a", HALO), ("b", duplicate)])

        assert resolution.decision is MatchDecision.REVIEW
        assert resolution.linked is None
        assert {key for key, _ in resolution.review} == {"a", "b"}
        assert all(result.signals["ambiguous"] for _, result in resolution.review)

    def test_review_candidates_are_reported(self) -> None:
        resolution = resolve(evidence(duration_ms=None), [("halo", HALO)])

        assert resolution.decision is MatchDecision.REVIEW
        assert [key for key, _ in resolution.review] == ["halo"]

    def test_no_candidates_means_no_match(self) -> None:
        assert resolve(evidence(), []).decision is MatchDecision.NO_MATCH
