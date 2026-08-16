"""`PUT /v1/assets/{sha256}` and the briefs that name an upload. No model, no GPU.

The measured problem: the ComfyUI nodes hand the service file PATHS and the service opens the user's
pictures, clips and sounds off its own disk. That works on one machine and on a second view of one
disk, and it cannot be made to work otherwise -- so every job with media in it failed against a
service on another machine, whatever the path said. These are the endpoint that fixes it and the
refusals that keep it from becoming a way to write anywhere on the host.

What is deliberately NOT here: reading an upload back out. There is no GET, and the 405s below are
asserted on purpose. A content-addressed store that serves its contents is an anonymous drop box that
hands the drop back to anyone who can name it, which is not a thing to leave running on a network.

`compile_brief` is stubbed in the brief tests, because what is under test is which bytes the compiler
is pointed at, not what it writes. The end-to-end run against a live model is not something CI can do.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from h3ir import service, uploads
from h3ir.config import AssetConfig, Paths, get_config, set_config

PAYLOAD = b"\x89PNG\r\n\x1a\n" + b"pretend pixels" * 40
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture()
def client(tmp_path):
    """A service with its own store, and caps small enough to reach in a test."""
    before = get_config()
    set_config(replace(before, paths=Paths(state_dir=tmp_path),
                       assets=AssetConfig(upload_max_bytes=5000, upload_store_bytes=12000,
                                          upload_ttl_hours=48, allow_paths=True)))
    with TestClient(service.app, raise_server_exceptions=False) as c:
        c.store = tmp_path / "uploads"          # type: ignore[attr-defined]
        yield c
    set_config(before)


def _sent(monkeypatch):
    """Capture the Brief the compiler is handed, which is the thing these tests are about."""
    seen = {}

    def fake_compile(brief, **kw):
        seen["brief"] = brief
        raise service.BackendUnavailable("no model in a test")

    monkeypatch.setattr(service, "compile_brief", fake_compile)
    return seen


# --------------------------------------------------------------------------- taking the bytes

def test_bytes_arrive_and_are_filed_under_their_own_hash(client):
    r = client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    assert r.status_code == 201, r.text
    assert r.json() == {"sha256": SHA, "stored": True, "bytes": len(PAYLOAD)}
    assert (client.store / SHA[:2] / SHA).read_bytes() == PAYLOAD


def test_sending_the_same_file_again_costs_nothing_and_keeps_the_verified_bytes(client):
    """The property that makes a big reference bearable, and a safety one at the same time: what is
    stored provably hashes to its name, so a second request under that name cannot replace it with
    something else."""
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.put(f"/v1/assets/{SHA}", content=b"different bytes entirely")
    assert r.status_code == 200, r.text
    assert "already held" in r.json()["note"]
    assert (client.store / SHA[:2] / SHA).read_bytes() == PAYLOAD, "the store took the wrong bytes"


@pytest.mark.parametrize("name", ["ref1.png", "a" * 63, "a" * 65, "A" * 64, "not-a-hash",
                                 "a" * 64 + ".png"])
def test_a_name_that_is_not_a_digest_is_a_422_that_says_what_a_name_is(client, name):
    """MEASURED: this was an empty HTTP 500. `uploads.stored()` was called above the try block, so
    every malformed name raised out of the handler with no body at all -- the one shape of failure a
    caller can do nothing whatsoever with.
    """
    r = client.put(f"/v1/assets/{name}", content=b"x")
    assert r.status_code == 422, f"{name!r} -> {r.status_code}: {r.text[:200]}"
    assert r.json()["detail"]["code"] == "asset-name-not-a-digest"
    assert "64 lowercase hexadecimal" in r.json()["detail"]["message"], "say what a name is"


@pytest.mark.parametrize("name", ["../../../../etc/cron.d/pwned", "%2e%2e%2f%2e%2e%2ftmp%2fpwned",
                                 "aa/../../../etc/passwd", "/etc/passwd", "$(touch /tmp/pwned)"])
def test_a_name_shaped_like_a_path_is_refused_and_writes_nothing(client, name):
    """Refused by the router rather than by the handler, because none of these is one path segment
    once the server has decoded it, so `{sha256}` never matches. Asserted anyway, and asserted on the
    filesystem rather than on the status code: what matters is that nothing appeared, and which layer
    said no is not something to depend on.

    Verified against a real uvicorn over a raw socket as well, since a test client that normalises a
    path would be testing the client. Same outcome: refused, nothing written.
    """
    r = client.put(f"/v1/assets/{name}", content=b"x")
    assert r.status_code in (404, 422), f"{name!r} -> {r.status_code}"
    assert [p for p in client.store.glob("**/*") if p.is_file()] == [] if client.store.exists() \
        else True


def test_bytes_that_are_not_what_they_claim_are_refused_and_stored_nowhere(client):
    r = client.put(f"/v1/assets/{'0' * 64}", content=PAYLOAD)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-digest-mismatch"
    assert SHA in r.json()["detail"]["message"], "say what the bytes actually hash to"
    assert [p for p in client.store.glob("**/*") if p.is_file()] == []


def test_a_file_over_the_cap_is_a_413_naming_the_setting(client):
    r = client.put(f"/v1/assets/{'1' * 64}", content=b"z" * 6000)
    assert r.status_code == 413, r.text
    assert r.json()["detail"]["code"] == "asset-too-large"
    assert "H3IR_UPLOAD_MAX_BYTES" in r.json()["detail"]["message"]


def test_a_full_store_is_a_507_and_not_a_bad_request(client):
    """A distinct status because it is a distinct fix, and it is nobody's request that is wrong. It
    shares nothing with the 503 an absent language model uses, which is the confusion this project
    has already paid for once.
    """
    for i in range(3):
        body = bytes([i]) * 4500
        client.put(f"/v1/assets/{hashlib.sha256(body).hexdigest()}", content=body)
    body = b"\xff" * 4500
    r = client.put(f"/v1/assets/{hashlib.sha256(body).hexdigest()}", content=body)
    assert r.status_code == 507, r.text
    assert r.json()["detail"]["code"] == "upload-store-full"
    assert "H3IR_UPLOAD_STORE_BYTES" in r.json()["detail"]["message"]


@pytest.mark.parametrize("method", ["get", "head", "delete", "post", "patch"])
def test_there_is_no_way_to_read_an_upload_back_out(client, method):
    """Deliberate. Anything that hands the bytes back turns a service reachable by anyone into a
    place to stash a file and collect it, and the store holds other people's media."""
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = getattr(client, method)(f"/v1/assets/{SHA}")
    assert r.status_code == 405, f"{method.upper()} answered {r.status_code}"


def test_the_service_publishes_what_it_will_accept(client):
    """The node reads this to refuse an oversized file locally, in one sentence, instead of spending
    the transfer to be told. An older service has no `assets` block at all, which is how the node
    knows to say "update it" rather than to keep trying."""
    a = client.get("/v1/capabilities").json()["assets"]
    assert a["uploads"] is True and a["paths"] is True
    assert a["upload_max_bytes"] == 5000 and a["upload_store_bytes"] == 12000
    assert a["upload_endpoint"] == "PUT /v1/assets/{sha256}"


# --------------------------------------------------------------------------- a brief that names one

def test_a_brief_can_point_at_an_upload_instead_of_a_path(client, monkeypatch):
    seen = _sent(monkeypatch)
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.post("/v1/briefs", json={"intent": "a car pulls away",
                                        "assets": [{"sha256": SHA, "kind": "image",
                                                    "role": "subject", "note": "the car"}]})
    assert r.status_code == 503, r.text            # the stub's "no model", i.e. it got that far
    asset = seen["brief"].assets[0]
    assert asset.sha256 == SHA, "the compiler was pointed at a different file"
    assert asset.path == str(client.store / SHA[:2] / SHA)
    assert asset.note == "the car" and asset.role.value == "subject", \
        "everything else about the attachment has to survive the other way in"


def test_a_brief_naming_an_upload_the_service_does_not_hold_says_which_ones(client, monkeypatch):
    """One answer listing every missing file, not one round trip per file. A caller with nine
    references needs to know which nine to send; `missing` is what it acts on.
    """
    _sent(monkeypatch)
    gone_a, gone_b = "a" * 64, "b" * 64
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.post("/v1/briefs", json={
        "intent": "x", "assets": [{"sha256": gone_a, "kind": "image"},
                                  {"sha256": SHA, "kind": "image"},
                                  {"sha256": gone_b, "kind": "video"}]})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "asset-not-uploaded"
    assert detail["missing"] == [gone_a, gone_b], "in request order, and only the absent ones"
    assert "PUT /v1/assets" in detail["message"], "say where to send them"
    assert "kept for a while and then dropped" in detail["message"], \
        "say why one that worked an hour ago may need sending again"


def test_referencing_an_upload_marks_it_as_used(client, monkeypatch):
    """What keeps the file somebody is working with out of the eviction queue. Without it, eviction
    is oldest-first and a reference in daily use is exactly the oldest thing in the store."""
    _sent(monkeypatch)
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    stored = client.store / SHA[:2] / SHA
    import os
    os.utime(stored, (1, 1))
    client.post("/v1/briefs", json={"intent": "x", "assets": [{"sha256": SHA, "kind": "image"}]})
    assert stored.stat().st_mtime > 1, "the reference did not mark the asset"


def test_a_path_and_an_upload_for_one_file_is_refused_rather_than_one_winning(client, monkeypatch):
    """They can name different files. Picking one silently would compile a brief about whichever the
    implementation happened to prefer, and nothing in the output would say which."""
    _sent(monkeypatch)
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.post("/v1/briefs", json={
        "intent": "x", "assets": [{"sha256": SHA, "path": "/tmp/something-else.png",
                                   "kind": "image"}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-two-sources"
    assert "pick one" in r.json()["detail"]["message"]


def test_an_asset_with_neither_says_both_ways_in(client, monkeypatch):
    _sent(monkeypatch)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [{"kind": "image"}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-no-path"
    msg = r.json()["detail"]["message"]
    assert "path" in msg and "sha256" in msg, "a caller cannot pick a way in it is not told about"


def test_a_soundtrack_pairs_with_an_uploaded_clip_by_hash(client, monkeypatch):
    """The pairing has to survive the trip too. A pointer sent as a path names nothing on the other
    machine, the pair quietly stops being a pair, and the soundtrack is numbered as a standalone
    <Audio j> while the runtime receives it as that clip's own track: two labels for one file, and
    only the report would ever have said so.
    """
    seen = _sent(monkeypatch)
    clip = b"\x00\x00\x00\x18ftypmp42" + b"clip" * 50
    clip_sha = hashlib.sha256(clip).hexdigest()
    sound = b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"sound" * 40
    sound_sha = hashlib.sha256(sound).hexdigest()
    client.put(f"/v1/assets/{clip_sha}", content=clip)
    client.put(f"/v1/assets/{sound_sha}", content=sound)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [
        {"sha256": clip_sha, "kind": "video", "role": "subject"},
        {"sha256": sound_sha, "kind": "audio", "role": "bgm",
         "paired_video_sha256": clip_sha}]})
    assert r.status_code == 503, r.text
    assert seen["brief"].assets[1].paired_video_sha256 == clip_sha


def test_a_pairing_pointing_at_nothing_is_refused_like_any_other_missing_upload(client, monkeypatch):
    _sent(monkeypatch)
    client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [
        {"sha256": SHA, "kind": "audio", "role": "bgm", "paired_video_sha256": "c" * 64}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["missing"] == ["c" * 64]


@pytest.mark.parametrize("field", ["sha256", "paired_video_sha256"])
def test_a_reference_that_is_not_a_digest_is_refused_before_the_store_is_searched(client, monkeypatch,
                                                                                 field):
    _sent(monkeypatch)
    asset = {"kind": "audio", "role": "bgm", field: "../../etc/passwd"}
    if field != "sha256":
        asset["sha256"] = SHA
        client.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [asset]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-name-not-a-digest"


# --------------------------------------------------------------------------- the path half, intact

def test_a_path_still_works_and_stores_nothing(client, monkeypatch, tmp_path):
    """THE control on the change as a whole. The path handoff is the fast path and the one every
    existing caller is on: it copies nothing, and the bytes H3 is conditioned on are the bytes the
    caller already had. Uploading is the fallback, so a request that states a path must still be
    served from that path and must not put a single byte in the store.
    """
    seen = _sent(monkeypatch)
    f = tmp_path / "plate.png"
    f.write_bytes(PAYLOAD)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [{"path": str(f),
                                                                   "kind": "image"}]})
    assert r.status_code == 503, r.text
    assert seen["brief"].assets[0].path == str(f)
    assert seen["brief"].assets[0].sha256 == SHA, "the service hashes the bytes it was pointed at"
    assert not client.store.exists(), "a path request created an upload store"


def test_a_missing_path_still_carries_the_code_the_node_retries_a_translation_on(client, monkeypatch):
    """The node tries several spellings of ComfyUI's folder and this code is what tells it to. Losing
    it would turn every Windows-ComfyUI-plus-WSL-service install into an upload."""
    _sent(monkeypatch)
    r = client.post("/v1/briefs", json={"intent": "x", "assets": [{"path": "/nowhere/at/all.png",
                                                                   "kind": "image"}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-missing"


# --------------------------------------------------------------------------- reads turned off

@pytest.fixture()
def no_paths(client):
    set_config(replace(get_config(), assets=AssetConfig(
        upload_max_bytes=5000, upload_store_bytes=12000, upload_ttl_hours=48, allow_paths=False)))
    return client


def test_a_service_can_refuse_to_open_its_own_filesystem(no_paths, monkeypatch):
    """For the deployment reachable by more people than you would hand a shell to. A `path` is read
    with the service's own permissions and its contents come back described in the brief, so on an
    open network that is a way to read files. Off by choice, on by default, because on is what every
    existing caller has and the fast path on one machine.
    """
    _sent(monkeypatch)
    r = no_paths.post("/v1/briefs", json={"intent": "x", "assets": [{"path": "/etc/hostname",
                                                                     "kind": "image"}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-paths-disabled"
    assert "PUT /v1/assets" in r.json()["detail"]["message"], "say what to do instead"
    assert no_paths.get("/v1/capabilities").json()["assets"]["paths"] is False, \
        "a caller has to be able to find this out without failing first"


def test_the_pairing_pointer_is_a_path_too(no_paths, monkeypatch):
    """FOUND BY MEASURING THE LIVE SERVICE: it was not gated. With filesystem reads turned off, a
    `paired_video_path` still reached `Path.exists()` and `sha256_file()`, so any file on the host
    was still opened and hashed -- a read the deployment had said it would not do, and an oracle for
    contents somebody can guess.
    """
    _sent(monkeypatch)
    no_paths.put(f"/v1/assets/{SHA}", content=PAYLOAD)
    r = no_paths.post("/v1/briefs", json={"intent": "x", "assets": [
        {"sha256": SHA, "kind": "audio", "role": "bgm", "paired_video_path": "/etc/hostname"}]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "asset-paths-disabled"
    assert "paired_video_sha256" in r.json()["detail"]["message"], "name the field that works"


def test_uploads_still_work_with_filesystem_reads_off(no_paths, monkeypatch):
    """The two settings are independent: refusing paths must not refuse the only remaining way in."""
    seen = _sent(monkeypatch)
    assert no_paths.put(f"/v1/assets/{SHA}", content=PAYLOAD).status_code == 201
    r = no_paths.post("/v1/briefs", json={"intent": "x", "assets": [{"sha256": SHA,
                                                                     "kind": "image"}]})
    assert r.status_code == 503, r.text
    assert seen["brief"].assets[0].sha256 == SHA


# --------------------------------------------------------------------------- refusing readably

def test_a_refused_body_is_read_off_before_the_refusal_is_sent(client):
    """MEASURED, and nondeterministic before the fix: answering while the client is still sending
    closes the connection under its own write, and the sentence naming the real problem is replaced
    at the far end by a broken pipe. Two uploads of identical size in one live run got different
    treatment -- one the message it deserved, one a socket error -- because it depends on what fits
    in a buffer.

    Driven directly rather than over HTTP, because an in-process test client has no socket to break:
    what is asserted is that the body IS consumed, and that consuming it is bounded, since reading an
    unbounded body is the exhaustion the caps exist to prevent.
    """
    import asyncio

    class Body:
        def __init__(self, chunks):
            self.chunks, self.read = chunks, 0

        def stream(self):
            async def gen():
                for c in self.chunks:
                    self.read += len(c)
                    yield c
            return gen()

    small = Body([b"x" * 100] * 3)
    asyncio.run(service._drain(small))
    assert small.read == 300, "the body was not read off, so the refusal cannot be delivered"

    huge = Body([b"y" * 1000] * 10_000)
    asyncio.run(service._drain(huge, budget=4000))
    assert huge.read <= 5000, f"read {huge.read} bytes of a body it had already refused"


def test_a_client_that_hangs_up_mid_refusal_is_not_an_error(client):
    """It is the normal end of a refused upload: the far side stops writing and goes away."""
    import asyncio

    from starlette.requests import ClientDisconnect

    class Gone:
        def stream(self):
            async def gen():
                yield b"a bit"
                raise ClientDisconnect()
            return gen()

    asyncio.run(service._drain(Gone()))          # must not raise
