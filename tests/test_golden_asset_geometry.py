"""The declared size of a reference image must match the file on disk.

Every place that builds a brief from `golden/assets/*.png` passes the pixel dimensions as a
literal, and nothing ever opens the image to check. That is a silent failure: the row budget is
computed from the declared geometry, so a swapped asset of a different size makes every downstream
number wrong while the whole suite stays green and tells you nothing.

It happened. The two reference images were replaced and the literals kept the old sizes for a
while, with no test able to notice. This is that check, so the next swap cannot repeat it.

The dimensions are read from the PNG IHDR header with the standard library rather than an imaging
dependency, because the package deliberately has none.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from h3ir.config import get_config
from h3ir.evalloop.suite import suite_briefs

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_dimensions(path: Path) -> tuple[int, int]:
    """Width and height from the IHDR chunk, which a valid PNG must open with."""
    head = path.read_bytes()[:33]
    if head[:8] != PNG_MAGIC or head[12:16] != b"IHDR":
        raise AssertionError(f"{path} is not a PNG whose first chunk is IHDR")
    return struct.unpack(">II", head[16:24])


def _declared() -> list[tuple[str, str, tuple[int, int]]]:
    """Every declaration the eval suite makes about a real asset, as (brief, filename, px).

    Deliberately a list and not a dict keyed by filename. Two different briefs declare `ref1.png`,
    so a dict collapses them and one correct declaration masks a wrong one — which is how the first
    version of this test passed while a literal was deliberately broken to check it could fail.
    """
    out: list[tuple[str, str, tuple[int, int]]] = []
    for name, brief in suite_briefs().items():
        for a in brief.assets:
            if a.path and a.px:
                out.append((name, Path(a.path).name, tuple(a.px)))
    return out


def test_the_reference_assets_are_pngs_and_present():
    assets = get_config().paths.golden_dir / "assets"
    found = sorted(p.name for p in assets.glob("*.png"))
    if not found:
        pytest.skip("no golden assets in this checkout")
    for name in found:
        w, h = png_dimensions(assets / name)
        assert w > 0 and h > 0, f"{name} reports a zero dimension"


def test_declared_dimensions_match_the_file_on_disk():
    assets = get_config().paths.golden_dir / "assets"
    declared = _declared()
    if not declared:
        pytest.skip("no brief in the suite declares a real asset")

    wrong = []
    for brief, name, px in declared:
        p = assets / name
        if not p.exists():
            continue
        real = png_dimensions(p)
        if px != real:
            wrong.append(f"{brief} declares {name} as {px}, file is {real}")

    assert not wrong, (
        "a brief declares a geometry the image does not have, so the row budget is computed "
        "from a lie:\n  " + "\n  ".join(wrong))
