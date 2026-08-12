"""A missing ffmpeg has to say so, not raise a path error nobody typed.

Video references need `ffprobe` for the duration and `ffmpeg` for the frames. Both were invoked
with a bare `subprocess.run`, which raises `FileNotFoundError` when the binary is absent. That
reached the caller as an OS error naming `ffprobe`, a program they never mentioned, with no
suggestion of what to install.

It also made the test suite environment-dependent in a way that only showed up somewhere else: a
runner without ffmpeg failed `test_an_unreadable_file_raises_rather_than_yielding_zero_frames`,
because the code raised the wrong exception type rather than the one the test expects. Green on any
machine with ffmpeg installed, red on any machine without, and the failure named neither cause.
"""
from __future__ import annotations

import shutil

import pytest

from h3ir.analyse import AssetAnalysisError, probe_seconds, sample_frames


def test_a_missing_ffprobe_names_itself_and_says_what_to_install(tmp_path, monkeypatch):
    """Simulated rather than requiring a machine without ffmpeg, so it runs everywhere."""
    import h3ir.analyse as A

    def no_binary(argv, capture_output=True, text=True, timeout=None):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(A.subprocess if hasattr(A, "subprocess") else A, "run", no_binary,
                        raising=False)
    # _run_ff imports subprocess locally, so patch the module the import resolves to
    import subprocess
    monkeypatch.setattr(subprocess, "run", no_binary)

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not really a video")

    with pytest.raises(AssetAnalysisError) as e:
        probe_seconds(f)
    msg = str(e.value)
    assert "ffprobe" in msg, "the message must name the binary that is missing"
    assert "ffmpeg" in msg, "and tell the reader what package provides it"
    assert "not installed" in msg


def test_the_frame_sampler_fails_the_same_way(tmp_path, monkeypatch):
    import subprocess

    def no_binary(argv, capture_output=True, text=True, timeout=None):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(subprocess, "run", no_binary)
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not really a video")

    with pytest.raises(AssetAnalysisError) as e:
        sample_frames(f, "d" * 64)
    assert "not installed" in str(e.value)


@pytest.mark.skipif(shutil.which("ffprobe") is None,
                    reason="ffprobe absent, which the tests above already cover")
def test_a_real_ffprobe_on_a_non_video_still_raises_the_domain_error(tmp_path):
    """The pre-existing behaviour, kept honest: with ffprobe present, an unreadable file is an
    analysis failure rather than a missing-binary failure. The two must not be conflated."""
    f = tmp_path / "not-a-video.mp4"
    f.write_bytes(b"this is not a video file")
    with pytest.raises(AssetAnalysisError) as e:
        probe_seconds(f)
    assert "not installed" not in str(e.value), (
        "a present-but-failing ffprobe must not report itself as missing")
