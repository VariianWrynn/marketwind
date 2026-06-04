from marketwind.scout.clean import clean_main_content, extract_quotes


def test_clean_strips_boilerplate(fixtures_dir):
    html = (fixtures_dir / "cls_recap.html").read_text(encoding="utf-8")
    raw = clean_main_content(html)
    assert "科创50指数收盘涨0.36%" in raw
    assert "广告" not in raw
    assert "更多推荐" not in raw


def test_clean_is_deterministic(fixtures_dir):
    html = (fixtures_dir / "cls_recap.html").read_text(encoding="utf-8")
    assert clean_main_content(html) == clean_main_content(html)


def test_extract_quotes_spans_relocate_exactly(fixtures_dir):
    html = (fixtures_dir / "cls_recap.html").read_text(encoding="utf-8")
    raw = clean_main_content(html)
    quotes = extract_quotes(raw)
    assert quotes, "expected at least one quote"
    for q in quotes:
        assert raw[q.span_start : q.span_end] == q.text
        reconstructed = (q.context_before or "") + q.text + (q.context_after or "")
        assert reconstructed in raw


def test_extract_marks_quantitative(fixtures_dir):
    raw = clean_main_content((fixtures_dir / "cls_recap.html").read_text(encoding="utf-8"))
    quotes = extract_quotes(raw)
    quant = [q for q in quotes if q.is_quantitative]
    assert any("0.36%" in q.text or "3.24万亿" in q.text for q in quant)
