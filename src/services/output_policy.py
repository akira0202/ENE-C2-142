"""AgentCore Platform v1.0 — output policy for ENE-C2-142 (terminal S-3, Step 5).

Deterministic, side-effect-free, framework-free. Two domain output-safety helpers used by the output
gate node:
 1. scan_prohibited() — the advisory/read-only boundary: the register is evidence for a human, never
    an operational directive. Scans string leaves for forecast / optimization / tariff / dispatch /
    trading / control INSTRUCTIONS (imperative/command phrasing, not mere topic mentions) and returns
    the offending category so the gate can fail closed. v1 has no LLM sink or actuation, so this is
    defence-in-depth against a caller embedding a directive in free text (e.g. value_selection_rule).
    Precision is bounded and the fail-safe direction is over-reject.
 2. mask_residual_jp_names() — the residual-gap personal-name case ONLY (honorific-anchored names, and the
    お名前/申請者 labels). The labelled Kanji/Katakana case (氏名/名前/担当者) is the framework
    substrate's job and is masked in the gate via detect_pii()/mask_pii() reuse — never here.

Credential scanning and Latin/Kanji labelled name masking are NOT re-implemented here (framework
substrate / detect_pii reuse). This module owns only the domain-semantic prohibition and the
residual-gap name masking.
"""

import re
from collections.abc import Iterator
from typing import Any

# Fail-closed code for a terminal S-3 prohibited-output block.
ERR_PROHIBITED_OUTPUT = "ERR_PROHIBITED_OUTPUT"

# Advisory/read-only prohibition — imperative/command phrasing per category (EN + JA). Anchored to
# directives, not topics, so an analytical mention (e.g. "latest forecast column") is not flagged.
_PROHIBITED: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "control",
        re.compile(
            r"shut\s*down|power\s*off|(open|close)\s+the\s+valve|停止(せよ|しろ|する指示|命令)|遮断(せよ|しろ)|バルブを(閉|開)|制御(せよ|命令|指示)",
            re.I,
        ),
    ),
    ("dispatch", re.compile(r"dispatch\s+(instruction|order|command)|給電(指示|命令)|ディスパッチ(指示|命令)", re.I)),
    (
        "trading",
        re.compile(r"execute\s+(a\s+)?trade|place\s+(a\s+)?(buy|sell)\s+order|売買(注文|指示)|取引を(実行|指示)", re.I),
    ),
    ("tariff", re.compile(r"(set|adjust)\s+(the\s+)?tariff|料金を(設定|変更)(せよ|する指示)?|関税を設定", re.I)),
    ("optimization", re.compile(r"optimi[sz]e\s+the|run\s+(an?\s+)?optimization|最適化(せよ|を実行|する指示)", re.I)),
    ("forecast", re.compile(r"(generate|produce)\s+(a\s+)?forecast|予測(せよ|を生成|を作成)", re.I)),
)


def _string_leaves(value: Any) -> Iterator[str]:
    """Yield every string leaf, recursing dict / list / tuple (mirrors the S-3 credential scan)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _string_leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _string_leaves(v)


def scan_prohibited(value: Any) -> str | None:
    """Return the first prohibited category found in any string leaf, else None."""
    for leaf in _string_leaves(value):
        for category, pattern in _PROHIBITED:
            if pattern.search(leaf):
                return category
    return None


# --- residual-gap Japanese name masking (Pattern B; pure re) ---------------------
# Kanji + Hiragana + Katakana + the ー long-vowel mark.
_JP = r"一-鿿぀-ゟ゠-ヿー"
# Honorific-suffixed non-names — politeness, not PII (お客様 / 皆様 / 神様 …).
_NOT_NAMES = ("お客", "皆", "神", "奥", "貴", "王", "殿")
_HONORIFIC = re.compile(rf"([{_JP}]{{1,4}})(様|さん|氏|殿|君|ちゃん|先生)")
# Label arm — residual labels ONLY (お名前 / 申請者). 氏名/名前/担当者 are the shared detector's
# job (detect_pii name_jp), reused in the gate; duplicating them here instead of reusing the shared
# substrate would be a re-implementation of an existing capability.
_LABELLED_RESIDUAL = re.compile(rf"((?:お名前|申請者)\s*[:：]\s*)([{_JP}]{{2,6}})(?=[\s、。，．,.]|$)")


def mask_residual_jp_names(text: str) -> tuple[str, int]:
    """Mask honorific- and residual-label-anchored Japanese personal names. Returns (masked, count).
    Bounded precision by construction (anchored names only); over-masks in the fail-safe direction.
    Never logs the matched value."""
    hits = 0

    def _sub_honorific(m: "re.Match[str]") -> str:
        nonlocal hits
        if any(m.group(1).endswith(w) for w in _NOT_NAMES):
            return m.group(0)
        hits += 1
        return "[MASKED]" + m.group(2)

    def _sub_labelled(m: "re.Match[str]") -> str:
        nonlocal hits
        hits += 1
        return m.group(1) + "[MASKED]"

    text = _HONORIFIC.sub(_sub_honorific, text)
    text = _LABELLED_RESIDUAL.sub(_sub_labelled, text)
    return text, hits
