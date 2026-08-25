"""The audio CARD is request-specific and never cached; the OBSERVATION is byte-derived and is.

Found by re-firing row 31 against the live service after the transcript was plumbed through to the
composer: the words still did not reach `<d>` in any of 7 runs, and the reason was upstream of every
change. `analyse_all` consults the card cache first, the key is
`sha256 | ANALYZER_VERSION | model | kind`, and every field that distinguishes one request's
audio card from another's comes from the REQUEST:

    role      -> the summary sentence ("a spoken vocal reference supplying voice timbre")
    note      -> `characterisation`, the ONLY channel the encoder has for what the audio sounds like
    transcript-> the words, supplied by the caller's own recogniser
    seconds   -> the duration

None of those is in the key. So the first request that attached a wav saved a card, and every later
request attaching the SAME wav with a different note, a different role, or a transcript got the first
request's card back. The live cache entry for the probe's `aud_voice.wav` held `transcript: ''` and a
note from a different request entirely ("a low, slow, slightly hoarse female voice" against a request
that said "a flat male voice, close mic"), and that is what reached the writer.

The enhanced audio stack (spec: docs/OpenH3-IR_Enhanced_Audio_Context-IR_Development_Spec.md)
splits the two halves apart rather than caching both or neither:

    AudioObservation  -- derived from the bytes alone -> cached, in audio/cache.py
    AssetCard (audio) -- observation x role x note x transcript -> never cached, either direction

The first four tests below hold the card side of that line exactly as before; the last two hold
the new seam: the observation cache filling does NOT resurrect the card bug.
"""
from __future__ import annotations

import pytest

from h3ir.analyse import analyse_all, save_cached
from h3ir.models import AssetCard, AssetKind, AssetRef, Role

WORDS = "We close at six, not half past."


class _Backend:
    class cfg:
        model = "test-model"


def _wav(note: str, role: Role = Role.VOICE_TIMBRE) -> AssetRef:
    return AssetRef(kind=AssetKind.AUDIO, role=role, sha256="a" * 64, seconds=3.0, note=note)


def _poison_the_cache() -> None:
    """A card for the same bytes from an earlier request: no transcript, someone else's note."""
    stale = AssetCard(sha256="a" * 64, kind=AssetKind.AUDIO,
                      summary="a spoken vocal reference supplying voice timbre and delivery, "
                              "described by the caller as: a low, slow, slightly hoarse female "
                              "voice (3.00s).",
                      characterisation="a low, slow, slightly hoarse female voice",
                      transcript="", analyzer_version="4",
                      model_id="none (typed metadata only)")
    save_cached(_wav("a low, slow, slightly hoarse female voice"), stale, "test-model")


def test_the_transcript_survives_a_cache_hit():
    _poison_the_cache()
    cards = analyse_all(_Backend(), [_wav("a flat male voice, close mic")],
                        transcripts={"a" * 64: WORDS})
    assert cards["a" * 64].transcript == WORDS


def test_the_callers_note_survives_a_cache_hit():
    """`characterisation` is the only channel for timbre, and X15 exists to demand it, so serving
    another request's note is worse than serving none: it is an assertion about a sound."""
    _poison_the_cache()
    cards = analyse_all(_Backend(), [_wav("a flat male voice, close mic")], transcripts={})
    card = cards["a" * 64]
    assert card.characterisation == "a flat male voice, close mic"
    assert "flat male voice" in card.summary
    assert "hoarse female" not in card.summary


def test_the_role_survives_a_cache_hit():
    """The summary sentence is chosen from the role, so a card cached as a voice reference described
    a background music track as a voice."""
    _poison_the_cache()
    cards = analyse_all(_Backend(), [_wav("a slow piano loop", role=Role.BGM)], transcripts={})
    assert "background music track" in cards["a" * 64].summary


def test_nothing_is_written_to_the_cache_for_audio_either():
    """A write is as wrong as a read: it is what poisons the next request."""
    from h3ir.analyse import _cache_path, _cache_key

    ref = _wav("a flat male voice, close mic")
    p = _cache_path(_cache_key(ref, "test-model"))
    if p.exists():
        p.unlink()
    analyse_all(_Backend(), [ref], transcripts={"a" * 64: WORDS})
    assert not p.exists(), "an audio card was cached; the next request's note would be overwritten"


def test_an_image_card_is_still_cached():
    """The distinction is not "caching is bad": an image card IS derived from the bytes by a model
    call, so content-addressing it is right and the saving is real."""
    from h3ir.analyse import _cache_key, _cache_path, load_cached

    ref = AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="b" * 64, px=(512, 512))
    card = AssetCard(sha256="b" * 64, kind=AssetKind.IMAGE, summary="a black car",
                     analyzer_version="4", model_id="test-model")
    save_cached(ref, card, "test-model")
    assert _cache_path(_cache_key(ref, "test-model")).exists()
    assert load_cached(ref, "test-model") is not None
    cards = analyse_all(_Backend(), [ref])
    assert cards["b" * 64].summary == "a black car", "the image cache hit is still used"


# ------------------------------------------------------------- the new seam

@pytest.fixture
def audio_state(tmp_path):
    from h3ir.config import AudioConfig, Config, Paths, get_config, set_config
    old = get_config()
    set_config(Config(paths=Paths(state_dir=tmp_path),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test")))
    yield tmp_path
    set_config(old)


def test_a_warm_observation_cache_does_not_resurrect_the_card_bug(audio_state):
    """The original failure, re-staged with the audio stack ON: a second request attaches the
    same wav with its own note and its own transcript. The observation may be shared (it is a
    function of the bytes); the card must not be (it is a function of the request)."""
    from fake_audio_worker import FakeWorker

    def heard(note: str) -> AssetRef:
        # The enhanced path needs a readable path; the fake never opens it, but the compiler's
        # rule (no path -> legacy metadata) is itself under test elsewhere.
        return AssetRef(kind=AssetKind.AUDIO, role=Role.VOICE_TIMBRE, sha256="a" * 64,
                        seconds=3.0, note=note, path="clip.wav")

    worker = FakeWorker()
    first = analyse_all(_Backend(), [heard("a low, slow, slightly hoarse female voice")],
                        audio_backend=worker)
    second = analyse_all(_Backend(), [heard("a flat male voice, close mic")],
                         transcripts={"a" * 64: WORDS}, audio_backend=worker)

    assert worker.analyse_calls == 1, "the observation is shared: byte-derived, cached once"
    assert len(list((audio_state / "cache" / "audio").glob("*.json"))) == 1
    card = second["a" * 64]
    assert card.characterisation == "a flat male voice, close mic"
    assert "flat male voice" in card.summary and "hoarse female" not in card.summary
    assert card.transcript == WORDS, "the caller's recogniser still wins over the cache"
    assert first["a" * 64].characterisation == "a low, slow, slightly hoarse female voice"


def test_the_enhanced_path_still_writes_no_card_cache_entry(audio_state):
    """`test_nothing_is_written_to_the_cache_for_audio_either`, enhanced-path edition: the
    observation cache filling must not leak the projection into the card cache."""
    from fake_audio_worker import FakeWorker
    from h3ir.analyse import _cache_key, _cache_path

    ref = AssetRef(kind=AssetKind.AUDIO, role=Role.VOICE_TIMBRE, sha256="a" * 64, seconds=3.0,
                   note="a flat male voice, close mic", path="clip.wav")
    p = _cache_path(_cache_key(ref, "test-model"))
    if p.exists():
        p.unlink()
    analyse_all(_Backend(), [ref], transcripts={"a" * 64: WORDS}, audio_backend=FakeWorker())
    assert not p.exists(), "an audio card was cached; the next request's note would be overwritten"
    assert list((audio_state / "cache" / "audio").glob("*.json")), \
        "and the observation cache is where the byte-derived half went instead"
