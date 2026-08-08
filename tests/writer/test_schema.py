import json

import pytest

from marketwind.writer.schema import SchemaViolation, parse_and_validate

VALID_QIDS = {"q1", "q2"}
VALID_SIDS = {"s1", "s2"}

GOOD = json.dumps({
    "claims": [{"id": "c-001", "statement": "科创50收涨0.36%", "quote_ids": ["q1"]}],
    "sentences": [
        {"sentence": "## 大盘动态", "claim_ids": [], "source_ids": [], "sentence_type": "structural"},
        {"sentence": "科创50上一交易日收涨0.36%。", "claim_ids": ["c-001"],
         "source_ids": ["s1"], "sentence_type": "factual"},
    ],
})


def test_valid_output_parses_and_resolves():
    out = parse_and_validate(GOOD, VALID_QIDS, VALID_SIDS)
    assert len(out.claims) == 1
    assert len(out.sentences) == 2
    assert out.sentences[1].claim_ids == ["c-001"]


def test_free_form_text_rejected():
    with pytest.raises(SchemaViolation):
        parse_and_validate("这是一段自由文本，不是 JSON。", VALID_QIDS, VALID_SIDS)


def test_factual_sentence_without_claim_rejected():
    bad = json.dumps({
        "claims": [],
        "sentences": [{"sentence": "科创50收涨。", "claim_ids": [],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_structural_sentence_with_claim_rejected():
    bad = json.dumps({
        "claims": [{"id": "c-001", "statement": "x", "quote_ids": ["q1"]}],
        "sentences": [{"sentence": "## 标题", "claim_ids": ["c-001"],
                       "source_ids": [], "sentence_type": "structural"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_unresolvable_claim_id_rejected():
    bad = json.dumps({
        "claims": [{"id": "c-001", "statement": "x", "quote_ids": ["q1"]}],
        "sentences": [{"sentence": "句子。", "claim_ids": ["c-999"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_unresolvable_quote_id_rejected():
    bad = json.dumps({
        "claims": [{"id": "c-001", "statement": "x", "quote_ids": ["q-nope"]}],
        "sentences": [{"sentence": "句子。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_unresolvable_source_id_rejected():
    bad = json.dumps({
        "claims": [{"id": "c-001", "statement": "x", "quote_ids": ["q1"]}],
        "sentences": [{"sentence": "句子。", "claim_ids": ["c-001"],
                       "source_ids": ["s-nope"], "sentence_type": "factual"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_duplicate_claim_id_rejected():
    # Two claims share an id → local-id→uuid mapping would silently drop one
    # on persist (data corruption). Fail closed instead.
    bad = json.dumps({
        "claims": [
            {"id": "c-001", "statement": "甲", "quote_ids": ["q1"]},
            {"id": "c-001", "statement": "乙", "quote_ids": ["q2"]},
        ],
        "sentences": [{"sentence": "句子。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_non_list_claims_rejected():
    # Malformed shape (claims is null) must raise SchemaViolation, not a raw
    # TypeError that escapes the fail-closed contract.
    bad = json.dumps({"claims": None, "sentences": []})
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


def test_non_list_sentences_rejected():
    bad = json.dumps({"claims": [], "sentences": "not a list"})
    with pytest.raises(SchemaViolation):
        parse_and_validate(bad, VALID_QIDS, VALID_SIDS)


# ---- I12 category / methodology tests ----

_QIDS = {"q1"}
_SIDS = {"s1"}


def _raw(category=None, methodology=None):
    claim = {"id": "c-001", "statement": "陈述", "quote_ids": ["q1"]}
    if category is not None:
        claim["category"] = category
    if methodology is not None:
        claim["methodology"] = methodology
    return json.dumps({
        "claims": [claim],
        "sentences": [{"sentence": "陈述。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })


def test_schema_parses_category_and_methodology():
    out = parse_and_validate(_raw("derived_metric", "按净利润计"), _QIDS, _SIDS)
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology == "按净利润计"


def test_schema_defaults_category_when_absent():
    out = parse_and_validate(_raw(), _QIDS, _SIDS)
    assert out.claims[0].category == "quantitative"
    assert out.claims[0].methodology is None


def test_schema_rejects_unknown_category():
    with pytest.raises(SchemaViolation):
        parse_and_validate(_raw("bogus_category"), _QIDS, _SIDS)


def test_schema_does_not_reject_derived_without_methodology():
    out = parse_and_validate(_raw("derived_metric"), _QIDS, _SIDS)
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology is None


def test_schema_parses_time_window():
    raw = json.dumps({
        "claims": [{"id": "c-001", "statement": "test", "quote_ids": ["q1"],
                     "category": "quantitative", "time_window": "2026-Q1"}],
        "sentences": [{"sentence": "test.", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    out = parse_and_validate(raw, {"q1"}, {"s1"})
    assert out.claims[0].time_window == "2026-Q1"


def test_schema_time_window_defaults_to_none():
    raw = json.dumps({
        "claims": [{"id": "c-001", "statement": "test", "quote_ids": ["q1"]}],
        "sentences": [{"sentence": "test.", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    out = parse_and_validate(raw, {"q1"}, {"s1"})
    assert out.claims[0].time_window is None
