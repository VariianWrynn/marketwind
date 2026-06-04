from datetime import datetime

from marketwind.scout.fixtures import source_from_html_fixture
from marketwind.scout.timeparse import CN_TZ


def test_source_from_html_fixture(fixtures_dir):
    html = (fixtures_dir / "cls_recap.html").read_text(encoding="utf-8")
    ingested = datetime(2026, 6, 1, 7, 0, tzinfo=CN_TZ)
    src = source_from_html_fixture(
        html, url="https://m.cls.cn/a/1", publish_raw="2026年5月28日 15:30",
        ingested_at=ingested,
    )
    assert src.domain == "m.cls.cn"
    assert src.publish_ts == datetime(2026, 5, 28, 15, 30, tzinfo=CN_TZ)
    assert len(src.quotes) >= 3
    # every span re-locates (RF-9) end-to-end through the fixture path
    for q in src.quotes:
        assert src.raw_content[q.span_start : q.span_end] == q.text
