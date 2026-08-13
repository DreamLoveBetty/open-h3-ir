"""The frame grid, and every duration fact that follows from it.

Verified against ComfyUI's `comfy_extras/nodes_minimax_h3.py`:
    align_frame_count: snaps up until n % 17 == 5
    video_latent_t:    2 if n <= 5 else ((n-5)//17)*5 + 2
    audio latent:      round(n/24 * 40)
Node-stated trained range is ~124..362 frames, i.e. 5.167 s .. 15.083 s.

Two different second-values matter and are routinely conflated:
  * `effective_seconds` = frames/24  -> the real length of the render. Cut times must
    fall strictly inside it.
  * `nominal_seconds`   = what was asked for -> what the instruction line's S.SS says,
    because the hosted API takes integer durations and the spec's own L2VA example
    uses 6.00, which is not on this grid at all.
"""
from __future__ import annotations

from dataclasses import dataclass

FPS = 24
AUDIO_LATENT_FPS = 40
FRAME_MODULUS = 17
FRAME_REMAINDER = 5
TRAINED_MIN_FRAMES = 124
TRAINED_MAX_FRAMES = 362

CANVAS_MULTIPLE = 32
BASE_SHORT_EDGE = 768
MAX_PIXELS = 768 * 1344

# How many of each kind the runtime can actually take, read off its socket templates in
# `MiniMaxH3ReferenceToVideo` (`nodes_minimax_h3.py`): `ref_image_` min=0 max=9, `ref_video_` max=3,
# `ref_video_audio_` max=3, `ref_audio_` max=3. A tenth image has no socket to arrive on, so a
# manifest that publishes `<Picture 10>` / `ref_image_10` describes a graph nobody can wire.
#
# There is deliberately NO total-file ceiling here. The service used to publish `total_files: 12`,
# which the runtime does not impose: 9 images plus 3 videos plus their 3 soundtracks plus 3
# standalone audios all have sockets. A limit that refuses a legal call is worse than no limit, and
# the runtime outranks the note.
MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3
MAX_REF_VIDEO_SOUNDTRACKS = 3

# `execute` truncates a reference video to the target's frame count (`frames[:frame_count]`) and
# raises outright below 5 frames ("MiniMax H3 reference videos need at least 5 frames"). Both are
# silent from here unless this layer says so.
MIN_REF_VIDEO_FRAMES = 5


def align_frame_count(n: int) -> int:
    """Snap up to the model's 17k+5 grid."""
    n = max(FRAME_REMAINDER, int(n))
    while n % FRAME_MODULUS != FRAME_REMAINDER:
        n += 1
    return n


def video_latent_t(frames: int) -> int:
    return 2 if frames <= 5 else ((frames - FRAME_REMAINDER) // FRAME_MODULUS) * 5 + 2


def audio_latent_t(frames: int) -> int:
    return round(frames / FPS * AUDIO_LATENT_FPS)


def legal_frames(trained_only: bool = True, max_frames: int | None = None) -> list[int]:
    """Aligned frame counts. `trained_only` bounds the list to the node's stated band, which is a
    note about training rather than a ceiling -- longer durations render, just slower."""
    lo = TRAINED_MIN_FRAMES if trained_only else FRAME_REMAINDER
    hi = max_frames or (TRAINED_MAX_FRAMES if trained_only else 24 * 60)
    return [n for n in range(lo, hi + 1) if n % FRAME_MODULUS == FRAME_REMAINDER]


def frames_for_seconds(seconds: float) -> int:
    """Snap a requested duration up onto the grid."""
    return align_frame_count(round(seconds * FPS))


def rows_per_latent_frame(width: int, height: int) -> int:
    """Packed-sequence rows one latent frame occupies (patchify 1x2x2 over a /16 latent)."""
    return (width // 32) * (height // 32)


def adapt_canvas(width: int, height: int) -> tuple[int, int]:
    """768-short-edge canvas with the 768*1344 area cap, per-axis round to 32."""
    import math

    ratio = width / height
    if ratio >= 1.0:
        nom_w, nom_h = BASE_SHORT_EDGE * ratio, float(BASE_SHORT_EDGE)
    else:
        nom_w, nom_h = float(BASE_SHORT_EDGE), BASE_SHORT_EDGE / ratio
    if nom_w * nom_h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (nom_w * nom_h))
        nom_w, nom_h = nom_w * s, nom_h * s
    return (max(CANVAS_MULTIPLE, round(nom_w / CANVAS_MULTIPLE) * CANVAS_MULTIPLE),
            max(CANVAS_MULTIPLE, round(nom_h / CANVAS_MULTIPLE) * CANVAS_MULTIPLE))


def canvas_for_aspect(aspect: str) -> tuple[int, int]:
    """'16:9' -> (1344, 768). Accepts 'W:H' or 'WxH'."""
    sep = ":" if ":" in aspect else "x"
    a, b = aspect.split(sep, 1)
    return adapt_canvas(int(float(a) * 1000), int(float(b) * 1000))


@dataclass(frozen=True)
class Target:
    """Everything downstream needs to know about time and size."""

    nominal_seconds: float
    frames: int
    canvas: tuple[int, int]
    fps: int = FPS

    @property
    def effective_seconds(self) -> float:
        return self.frames / self.fps

    @property
    def latent_t(self) -> int:
        return video_latent_t(self.frames)

    @property
    def video_rows(self) -> int:
        return self.latent_t * rows_per_latent_frame(*self.canvas)

    @property
    def audio_rows(self) -> int:
        return audio_latent_t(self.frames) * 2

    @property
    def in_trained_range(self) -> bool:
        """Informational. Outside this band still renders; it is not a supported/unsupported line."""
        return TRAINED_MIN_FRAMES <= self.frames <= TRAINED_MAX_FRAMES

    def s_ss(self, policy: str = "nominal") -> str:
        """The instruction line's S.SS value. See module docstring for why nominal is default.

        Rounded half-UP explicitly: Python's default formatting is round-half-even, so
        f"{10.125:.2f}" is "10.12" -- not what anyone reading the spec would write.
        """
        from decimal import ROUND_HALF_UP, Decimal
        v = self.nominal_seconds if policy == "nominal" else self.effective_seconds
        return str(Decimal(repr(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @classmethod
    def build(cls, seconds: float, aspect: str = "16:9",
              canvas: tuple[int, int] | None = None) -> "Target":
        """`canvas` pins an exact size. Needed when matching another render's geometry, where
        the derived 768-short-edge canvas would silently differ and invalidate the comparison."""
        if canvas is not None:
            w, h = int(canvas[0]), int(canvas[1])
            if w % CANVAS_MULTIPLE or h % CANVAS_MULTIPLE:
                raise ValueError(f"canvas {w}x{h} must be a multiple of {CANVAS_MULTIPLE}")
            return cls(nominal_seconds=float(seconds), frames=frames_for_seconds(seconds),
                       canvas=(w, h))
        return cls(nominal_seconds=float(seconds),
                   frames=frames_for_seconds(seconds),
                   canvas=canvas_for_aspect(aspect))


def ms_to_timestamp(ms: int) -> str:
    """1_500 -> '00:01.500'. The spec's mandated MM:SS.mmm."""
    if ms < 0:
        raise ValueError("negative timestamp")
    total_s, milli = divmod(int(round(ms)), 1000)
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes:02d}:{seconds:02d}.{milli:03d}"


def timestamp_to_ms(ts: str) -> int:
    mm, rest = ts.split(":", 1)
    ss, mmm = rest.split(".", 1)
    return (int(mm) * 60 + int(ss)) * 1000 + int(mmm)
