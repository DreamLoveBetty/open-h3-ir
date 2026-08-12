"""Exact token counting with the tokenizer H3 actually uses.

H3's shipped `Ref2VA/tokenizer/vocab.json` is byte-identical to the one ComfyUI bundles
(git blob sha1 4783fe10ac3adce15ac8f358ef5462739852c569 matches the HF etag), so counts
from this module are what the conditioning encoder really sees.

Note for anyone tempted to "fix" dialogue markup: `<d>`, `</d>`, `<scenetrans>` and
`<cutoff>` are NOT special tokens. H3's own tokenizer_config.json carries exactly the
same 26 added tokens as stock Qwen2.5. `<d>` BPE-splits to ['<d', '>'] and that is
correct. It does mean the markers must be byte-exact.
"""
from __future__ import annotations

import functools
import json

from .config import get_config

PAT = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)"
    r"|[^\r\n\p{L}\p{N}]?\p{L}+"
    r"|\p{N}"
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+"
    r"|\s+(?!\S)"
    r"|\s+"
)

# The 26 added tokens present in both ComfyUI's and H3's tokenizer configs.
ADDED_TOKENS = {
    "<|endoftext|>": 151643, "<|im_start|>": 151644, "<|im_end|>": 151645,
    "<|object_ref_start|>": 151646, "<|object_ref_end|>": 151647,
    "<|box_start|>": 151648, "<|box_end|>": 151649,
    "<|quad_start|>": 151650, "<|quad_end|>": 151651,
    "<|vision_start|>": 151652, "<|vision_end|>": 151653,
    "<|vision_pad|>": 151654, "<|image_pad|>": 151655, "<|video_pad|>": 151656,
    "<tool_call>": 151657, "</tool_call>": 151658,
    "<|fim_prefix|>": 151659, "<|fim_middle|>": 151660, "<|fim_suffix|>": 151661,
    "<|fim_pad|>": 151662, "<|repo_name|>": 151663, "<|file_sep|>": 151664,
    "<tool_response>": 151665, "</tool_response>": 151666,
    "<think>": 151667, "</think>": 151668,
}


def _bytes_to_unicode() -> dict[int, str]:
    bs = (list(range(ord("!"), ord("~") + 1))
          + list(range(ord("\xa1"), ord("\xac") + 1))
          + list(range(ord("\xae"), ord("\xff") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


@functools.lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    tok_dir = get_config().paths.tokenizer_dir
    vocab = json.loads((tok_dir / "vocab.json").read_text(encoding="utf-8"))
    u2b = {v: k for k, v in _bytes_to_unicode().items()}
    ranks: dict[bytes, int] = {}
    for token, tid in vocab.items():
        if token in ADDED_TOKENS:
            continue
        try:
            ranks[bytes(u2b[ch] for ch in token)] = tid
        except KeyError:
            continue
    return tiktoken.Encoding(name="qwen25-h3", pat_str=PAT, mergeable_ranks=ranks,
                             special_tokens=dict(ADDED_TOKENS))


def count(text: str) -> int:
    """Exact H3-encoder token count for a piece of prompt text."""
    enc = _encoding()
    return len(enc.encode(text, allowed_special=set(ADDED_TOKENS)))


def word_count(text: str) -> int:
    """The spec talks in English words, so the planner and validator need this too."""
    import re

    return len(re.findall(r"\b[\w'-]+\b", text))


def label_cost() -> dict[str, int]:
    """Token cost of the labels the runtime injects, for the budget report."""
    return {s: count(s) for s in ("<Picture 1>: ", "<Video 1>: ", "<Audio 1>: ",
                                  "<0.5 seconds>", "<Subject 1>")}
