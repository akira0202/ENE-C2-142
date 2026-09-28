# ENE-C2-142 — Unit tests: output policy service (framework-free).
#
# Covers the advisory/read-only prohibition scan (directive phrasing flagged, topic mentions not)
# and the residual-gap Japanese name masking (honorific / お名前 / 申請者 only; the labelled
# Kanji/Katakana case is the framework substrate's job and is left to detect_pii in the gate).

from src.services.output_policy import mask_residual_jp_names, scan_prohibited


# --- prohibition scan ---------------------------------------------------------------------
def test_control_instruction_flagged():
    assert scan_prohibited({"note": "please shut down the plant"}) == "control"
    assert scan_prohibited("バルブを閉じよ") == "control"


def test_dispatch_trading_tariff_optimization_forecast_directives_flagged():
    assert scan_prohibited("dispatch instruction: reroute") == "dispatch"
    assert scan_prohibited("execute a trade now") == "trading"
    assert scan_prohibited("set the tariff to 20") == "tariff"
    assert scan_prohibited("optimize the grid load") == "optimization"
    assert scan_prohibited("generate a forecast for 2040") == "forecast"


def test_topic_mentions_not_flagged():
    # analytical mentions are not directives -> not flagged (avoids over-reject of legit rules)
    assert scan_prohibited("value from the latest forecast column") is None
    assert scan_prohibited("最新の予測値を採用") is None
    assert scan_prohibited({"value_selection_rule": "priority: highest approved"}) is None


def test_scan_recurses_nested_leaves():
    reg = {"entries": [{"value_selection_rule": "please shut down"}], "entry_count": 1}
    assert scan_prohibited(reg) == "control"


def test_clean_register_passes():
    reg = {"entries": [{"geography": "shibata-city", "value_selection_rule": "latest approved"}]}
    assert scan_prohibited(reg) is None


# --- residual-gap Japanese name masking ---------------------------------------------------
def test_honorific_name_masked():
    masked, hits = mask_residual_jp_names("田中様に確認")
    assert "[MASKED]" in masked
    assert hits == 1


def test_residual_label_masked():
    masked, hits = mask_residual_jp_names("お名前：山田")
    assert masked == "お名前：[MASKED]"
    assert hits == 1

    masked2, hits2 = mask_residual_jp_names("申請者：佐藤")
    assert "[MASKED]" in masked2 and hits2 == 1


def test_substrate_labels_left_to_detect_pii():
    # 氏名/名前/担当者 (Kanji/Katakana) are the substrate's job (detect_pii) — NOT masked by Pattern B
    masked, hits = mask_residual_jp_names("氏名：田中")
    assert masked == "氏名：田中"
    assert hits == 0


def test_politeness_not_masked():
    masked, hits = mask_residual_jp_names("お客様へのご案内")
    assert masked == "お客様へのご案内"
    assert hits == 0
