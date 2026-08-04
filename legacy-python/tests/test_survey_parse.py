import gzip
import json
from pathlib import Path

from openpyxl import Workbook

from ub_local.orchestrate.survey_parse import parse_survey_input


def test_parse_survey_xlsx(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append(["persona", "q1", "q2"])
    ws.append(["Theo", "yes", "no"])
    xlsx = tmp_path / "sample.xlsx"
    wb.save(xlsx)

    out = parse_survey_input(xlsx, tmp_path / "out")
    assert out.name == "chunks.jsonl.gz"
    with gzip.open(out, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    assert len(rows) == 1
    assert "Theo" in rows[0]["text"]
    assert rows[0]["metadata"]["excel_row"] == 2


def test_parse_survey_jsonl(tmp_path: Path):
    src = tmp_path / "in.jsonl"
    src.write_text(
        json.dumps({"id": "a", "text": "hello", "metadata": {"persona_id": "p1"}}) + "\n",
        encoding="utf-8",
    )
    out = parse_survey_input(src, tmp_path / "out2")
    with gzip.open(out, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    assert rows[0]["text"] == "hello"
