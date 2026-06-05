import json

import pytest

from marketwind.writer.client import parse_chat_completion


def test_parse_reads_message_content(fixtures_dir_writer):
    payload = json.loads((fixtures_dir_writer / "deepseek_writer.json").read_text("utf-8"))
    content = parse_chat_completion(payload)
    inner = json.loads(content)  # content itself is the WriterOutput JSON
    assert inner["claims"][0]["id"] == "c-001"


def test_parse_raises_on_empty_choices():
    with pytest.raises(ValueError):
        parse_chat_completion({"choices": []})
