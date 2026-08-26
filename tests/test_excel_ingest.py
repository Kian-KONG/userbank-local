import json
from pathlib import Path

from src.excel_ingest import classify_table, excel_to_chunks, parse_tabular_input
from src.excel_ingest import _tables_from_grid
from src.flatten import flatten_for_export
from src.routing import file_kind


def test_file_kind_routes_by_suffix(tmp_path: Path) -> None:
    assert file_kind(tmp_path / "deck.pptm") == "deck"
    assert file_kind(tmp_path / "notes.docx") == "document"
    assert file_kind(tmp_path / "data.xlsx") == "tabular"
    assert file_kind(tmp_path / "rows.jsonl.gz") == "tabular"
    assert file_kind(tmp_path / "paper.pdf") == "document"


def test_skip_title_row_keeps_real_headers() -> None:
    grid = [
        ["Sales report 2024", None, None],
        ["Region", "Product", "Units"],
        ["EU", "Heat pump", 10],
        ["DE", "Boiler", 5],
    ]
    tables = _tables_from_grid("Sales", grid)
    assert len(tables) == 1
    assert tables[0].headers == ["Region", "Product", "Units"]
    assert tables[0].rows[0][0] == 3
    assert classify_table(tables[0].headers, tables[0].rows) == "data_table"


def test_two_column_records_stay_data_table() -> None:
    headers = ["persona", "score"]
    rows = [(2, ["Anna", 9]), (3, ["Bob", 7])]
    assert classify_table(headers, rows) == "data_table"


def test_classify_kv_form() -> None:
    headers = ["Field", "Value"]
    rows = [(2, ["Company", "Bosch"]), (3, ["Year", "2024"])]
    assert classify_table(headers, rows) == "kv_form"


def test_classify_codebook_and_matrix() -> None:
    codebook_headers = ["variable", "code", "value_label"]
    codebook_rows = [(2, ["age", 1, "18-24"]), (3, ["age", 2, "25-34"])]
    assert classify_table(codebook_headers, codebook_rows) == "codebook"

    matrix_headers = ["Question", "Strongly disagree", "Disagree", "Agree"]
    matrix_rows = [
        (2, ["The product is reliable enough for daily use in winter.", "1", "", ""]),
        (3, ["I would recommend this system to a neighbour after one season.", "", "1", ""]),
    ]
    assert classify_table(matrix_headers, matrix_rows) == "matrix_questionnaire"


def test_xlsx_roundtrip_named_headers(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "survey.xlsx"
    wb = Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Responses"
    sheet["A1"] = "Fieldwork 2024"
    sheet["A2"] = "persona"
    sheet["B2"] = "q1_nps"
    sheet["A3"] = "Anna"
    sheet["B3"] = 9
    wb.save(path)

    chunks = excel_to_chunks(path, track="survey")
    assert chunks
    text = chunks[0]["text"]
    assert "persona: Anna" in text
    assert "q1_nps: 9" in text
    assert "col_0" not in text
    assert chunks[0]["metadata"]["persona"] == "Anna"
    assert chunks[0]["metadata"]["excel_sheet"] == "Responses"

    dest = parse_tabular_input(path, tmp_path / "parse", "survey")
    corpus = json.loads(dest.read_text(encoding="utf-8"))
    assert corpus["source_type"] == "excel"
    points = flatten_for_export(corpus, "doc-1")
    assert points[0]["id"].startswith("doc-1:")
    assert points[0]["metadata"]["sheet_kind"] == "data_table"
