"""The store that keeps bytes a caller sent. No model, no GPU, no HTTP.

This is the half of uploading that decides what lands on somebody's disk, so most of what follows is
about the two things a stranger's bytes must never be able to do: escape the store, and fill the
host. Both are asserted by trying, not by reading the code.

The measurement that shaped every name in here: a service could only ever open attachments from its
own filesystem, so ComfyUI on one machine pointed at a service on another failed every job with
media in it, and `path_candidates`' own docstring said so -- "the one case a box could not fix is a
service on another machine, which cannot open these files under any spelling". Uploads are the way
in for that case, and the store is where they land.

Falsified: every assertion below was watched to fail with the rule it covers removed. The two that
mattered were the ones a careless implementation passes anyway. Naming the stored file after the
digest the CALLER claimed rather than the one this process computed still passes an idempotency test,
a size test and a traversal test, because a well-behaved caller sends a name that matches; it fails
only `test_the_stored_name_is_the_digest_we_computed_not_the_one_we_were_given`. And a grace window
that is not honoured still passes every eviction test that does not have a fresh file in it.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import replace

import pytest

from h3ir import uploads
from h3ir.config import AssetConfig, Config, Paths, get_config, set_config


@pytest.fixture()
def store(tmp_path):
    """A store of its own per test, with caps small enough to reach by hand."""
    before = get_config()
    set_config(replace(before,
                       paths=Paths(state_dir=tmp_path),
                       assets=AssetConfig(upload_max_bytes=1000, upload_store_bytes=2500,
                                          upload_ttl_hours=48, allow_paths=True)))
    yield tmp_path / "uploads"
    set_config(before)


def put(payload: bytes, *, claimed: str | None = None) -> tuple[str, int]:
    """Send bytes the way the endpoint does: one chunk at a time, through the real Receiver."""
    sha = claimed or hashlib.sha256(payload).hexdigest()
    with uploads.receiver(sha, declared=len(payload)) as rx:
        for i in range(0, max(1, len(payload)), 64):
            rx.write(payload[i:i + 64])
        path, size = rx.finish()
    return str(path), size


# --------------------------------------------------------------------------- the name

@pytest.mark.parametrize("name", [
    "../../../../etc/cron.d/pwned",
    "..%2f..%2fetc%2fpasswd",
    "/etc/passwd",
    "ref1.png",
    "$(touch /tmp/pwned)",
    "a" * 63,
    "a" * 65,
    "A" * 64,                      # sha256 is written one way; a second spelling is a second name
    "a" * 63 + "g",
    "a" * 64 + "\x00.png",
    "",
])
def test_a_name_that_is_not_a_digest_never_reaches_the_filesystem(store, name):
    """THE control on where a stored file can land.

    Every one of these is a name a caller can put in the request line, and none of them may become a
    path. Asserted through `path_for`, which is the only place in the package that builds a path into
    the store, so a second builder appearing elsewhere is the thing to watch for rather than this.
    """
    with pytest.raises(uploads.NotADigest):
        uploads.path_for(name)
    with pytest.raises(uploads.NotADigest):
        uploads.receiver(name, declared=4)
    assert not store.exists(), "nothing may be created on the way to refusing a name"


def test_a_stored_path_stays_inside_the_store(store):
    payload = b"pixels"
    path, _ = put(payload)
    assert os.path.realpath(path).startswith(os.path.realpath(str(store)))
    assert os.path.basename(path) == hashlib.sha256(payload).hexdigest()


def test_the_stored_name_is_the_digest_we_computed_not_the_one_we_were_given(store):
    """The rule that makes the path independent of the request, and the one an implementation that
    trusts the caller still passes every other test with.

    The claim is compared and then thrown away: what names the file is what this process hashed. So
    the only way to choose a filename here is to control the bytes, and controlling the bytes gets
    you a filename that is the hash of them.
    """
    payload = b"the bytes decide"
    real = hashlib.sha256(payload).hexdigest()
    with pytest.raises(uploads.DigestMismatch) as e:
        put(payload, claimed="b" * 64)
    assert real in str(e.value), "say what the bytes actually were"
    assert not (store / "bb").exists() and not (store / real[:2]).exists(), \
        "a mismatch stores nothing under either name"


def test_a_mismatch_says_the_two_things_that_cause_it(store):
    with pytest.raises(uploads.DigestMismatch) as e:
        put(b"one thing", claimed="c" * 64)
    msg = str(e.value)
    assert "changed while it was being sent" in msg and "truncated" in msg
    assert "Send it again" in msg, "say the remedy, not just the fact"


def test_nothing_is_left_behind_when_an_upload_dies_mid_body(store):
    """A connection that drops leaves a part-written file, and a store that accumulates those is a
    slow disk leak nobody attributes to uploading."""
    with pytest.raises(RuntimeError):
        with uploads.receiver("d" * 64, declared=100) as rx:
            rx.write(b"half of it")
            raise RuntimeError("the client went away")
    assert list(store.glob("**/*")) == [], f"left behind: {list(store.glob('**/*'))}"


# --------------------------------------------------------------------------- what it costs

def test_a_file_over_the_per_file_cap_is_refused_before_it_is_read(store):
    """Refused on the stated length, so an oversized file is not transferred to be rejected."""
    with pytest.raises(uploads.TooLarge) as e:
        uploads.receiver("e" * 64, declared=1001)
    assert "1000 bytes" in str(e.value) and "H3IR_UPLOAD_MAX_BYTES" in str(e.value), \
        "name the ceiling and the setting that moves it"
    assert list(store.glob("**/*")) == []


def test_the_cap_is_enforced_on_the_bytes_that_arrive_and_not_on_the_header(store):
    """THE control on the size limit. `Content-Length` is absent under chunked encoding and can
    simply be wrong, so a check that reads it and nothing else is a check a caller turns off by
    lying. Here the declaration is honest-looking and the body is not.
    """
    with pytest.raises(uploads.UploadRefused):
        with uploads.receiver("f" * 64, declared=10) as rx:
            rx.write(b"x" * 4000)
    assert list(store.glob("**/*")) == []


def test_an_upload_with_no_stated_length_is_still_capped(store):
    """Chunked encoding states no length at all, which must not read as "no limit"."""
    with pytest.raises(uploads.TooLarge):
        with uploads.receiver("0" * 64, declared=None) as rx:
            rx.write(b"y" * 1001)


def test_uploads_can_be_turned_off_entirely(store):
    """0 is a real setting for a service that should only ever read its own disk, and it has to say
    so rather than failing as a size."""
    set_config(replace(get_config(), assets=AssetConfig(
        upload_max_bytes=0, upload_store_bytes=2500, upload_ttl_hours=48, allow_paths=True)))
    with pytest.raises(uploads.TooLarge) as e:
        uploads.receiver("1" * 64, declared=10)
    assert "does not accept uploads" in str(e.value)
    assert "H3IR_UPLOAD_MAX_BYTES" in str(e.value), "name the setting that turned it off"


def test_the_store_stops_growing_when_it_is_full_of_files_still_in_use(store):
    """A per-file cap alone bounds nothing: it is the total that fills a disk, one legal upload at a
    time. Nothing here is old enough to evict, so the only correct answer is to refuse.
    """
    put(b"a" * 900)
    put(b"b" * 900)
    with pytest.raises(uploads.StoreFull) as e:
        put(b"c" * 900)
    assert "2500 bytes" in str(e.value), "name the ceiling"
    assert "H3IR_UPLOAD_STORE_BYTES" in str(e.value), "and the setting that moves it"
    assert uploads.total_bytes() <= 2500


def test_uploads_in_flight_are_counted_against_the_cap(store):
    """The exhaustion a cap that reads only the disk does not stop: twenty parallel uploads each
    see a store under the ceiling and each write a full file. Reserved on the way in, so the second
    of these cannot be told there is room the first one has already taken.
    """
    first = uploads.receiver("2" * 64, declared=900)
    second = uploads.receiver("3" * 64, declared=900)
    with pytest.raises(uploads.StoreFull):
        uploads.receiver("4" * 64, declared=900)
    first.abort()
    second.abort()
    # And the room comes back, or a dropped connection would shrink the store for good.
    uploads.receiver("5" * 64, declared=900).abort()


def test_a_reservation_survives_nothing_and_is_released_by_finishing_too(store):
    path, _ = put(b"z" * 900)
    assert os.path.isfile(path)
    uploads.receiver("6" * 64, declared=1000).abort()
    uploads.receiver("7" * 64, declared=1000).abort()


# --------------------------------------------------------------------------- making room

def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_the_least_recently_used_asset_goes_first(store):
    """Least recently USED, not oldest: `touch` marks an asset when a brief references it, so the
    file somebody keeps compiling against outlives the one they uploaded and forgot.

    `keep` is the OLDER upload of the two, so the only thing that can save it is having been
    referenced. FALSIFIED THE HARD WAY: a first version of this aged `keep` again after touching it,
    which set the mtime `touch` was supposed to set, and the test passed with `touch` gutted. The
    sweep is given a `now` in the future instead, so both files are outside the grace window and
    their order is decided by nothing but the reference.
    """
    keep, _ = put(b"k" * 900)
    drop, _ = put(b"d" * 900)
    _age(keep, 9000)                         # uploaded long ago
    _age(drop, 4000)                         # uploaded more recently than `keep`
    uploads.touch(keep)                      # ... but a brief referenced `keep` just now
    uploads.sweep(reserve=900, now=time.time() + 2000)
    assert os.path.isfile(keep), "the asset a brief had just referenced was evicted"
    assert not os.path.isfile(drop), "nothing was evicted, so this proves no ordering at all"


def test_an_asset_that_was_just_uploaded_is_never_evicted(store):
    """The race this closes: a brief references an attachment, then spends a minute in the analyser
    and the prose model. Another caller's upload arriving in that minute must not delete it, or the
    compile fails with nothing anybody can reproduce.
    """
    fresh, _ = put(b"f" * 900)
    fresher, _ = put(b"g" * 900)
    with pytest.raises(uploads.StoreFull):
        put(b"h" * 900)
    assert os.path.isfile(fresh) and os.path.isfile(fresher), \
        "a full store refused the new file rather than eating a file in use"


def test_an_expired_asset_is_dropped_even_with_room_to_spare(store):
    """Uploaded bytes are a cache: every one of them can be sent again. Keeping them for ever would
    make a disk fill in proportion to how long the service has been up.
    """
    old, _ = put(b"o" * 100)
    _age(old, 49 * 3600)
    uploads.sweep()
    assert not os.path.isfile(old)


def test_expiry_can_be_turned_off(store):
    set_config(replace(get_config(), assets=AssetConfig(
        upload_max_bytes=1000, upload_store_bytes=2500, upload_ttl_hours=0, allow_paths=True)))
    old, _ = put(b"o" * 100)
    _age(old, 400 * 24 * 3600)
    uploads.sweep()
    assert os.path.isfile(old), "0 hours means keep until the size cap needs the room"


def test_an_abandoned_part_file_is_swept(store):
    """Every dropped connection leaves one. They are invisible to `missing`, so nothing would ever
    ask for them again and nothing would ever remove them.
    """
    rx = uploads.receiver("8" * 64, declared=900)
    rx.write(b"partial")
    partials = list(store.glob("incoming-*.part"))
    assert len(partials) == 1, "the part file is not where the sweep looks for it"
    _age(partials[0], 4000)
    uploads.sweep()
    assert not partials[0].exists()
    rx.abort()


def test_a_part_file_from_an_upload_still_running_is_left_alone(store):
    """The other half of the same rule, and the one that matters: sweeping runs on the request path,
    so it runs while other uploads are in progress."""
    rx = uploads.receiver("9" * 64, declared=900)
    rx.write(b"still going")
    uploads.sweep()
    assert len(list(store.glob("incoming-*.part"))) == 1
    rx.finish  # noqa: B018 - the object is still usable, which is the point
    rx.abort()


# --------------------------------------------------------------------------- being asked about

def test_the_same_bytes_stored_twice_are_one_file(store):
    """What makes a big reference bearable: re-queueing a graph whose clip has not changed sends
    nothing, because the digest is the same and the store already answers to it."""
    a, _ = put(b"one clip")
    b, _ = put(b"one clip")
    assert a == b
    assert len([p for p in store.glob("**/*") if p.is_file()]) == 1


def test_missing_reports_what_is_absent_in_the_order_asked_without_repeats(store):
    have = hashlib.sha256(b"here").hexdigest()
    put(b"here")
    gone_a, gone_b = "a" * 64, "b" * 64
    assert uploads.missing([gone_b, have, gone_a, gone_b]) == [gone_b, gone_a]
    assert uploads.missing([have]) == []


def test_asking_about_a_name_that_is_not_a_digest_is_refused_rather_than_answered_no(store):
    """`missing` is what a caller acts on, so "we do not have it" for a name that could never be
    held would send them off to upload a file under a name that will be refused."""
    with pytest.raises(uploads.NotADigest):
        uploads.missing(["../etc/passwd"])
