import json
from pathlib import Path

import pytest

from src.excel_ingest import (
    classify_table,
    excel_to_chunks,
    parse_excel_workbook,
    parse_tabular_input,
    table_to_chunks,
    _skip_duplicate_crosstab_sheet,
    _tables_from_grid,
)
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


def _crosstab_counts_grid() -> list[list[object]]:
    return [
        [None, None, None, None, "USA", "Japan", "Global", "Global", "Global", "Global", "USA", "USA", "USA", "USA"],
        [None, None, None, None, None, None, 1, 2, 3, 4, 1, 2, 3, 4],
        ["hidden for country", "USA", "Value", 1004, 1004, 0, 163, 326, 265, 250, 163, 326, 265, 250],
        [None, None, "Column Percentage", 0.08, 1, 0, 0.16, 0.32, 0.26, 0.25, 1, 1, 1, 1],
        ["What age group do you fall under?", "25-34", "Value", 1500, 120, 80, 40, 50, 30, 20, 10, 20, 40, 50],
        [None, None, "Column Percentage", 0.124, 0.12, 0.079, 0.1, 0.2, 0.15, 0.08, 0.05, 0.1, 0.2, 0.25],
        ["${custom170}", "x", "Value", 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1],
    ]


def test_crosstab_headers_use_country_and_cluster() -> None:
    tables = _tables_from_grid("Crosstabulation Counts & %", _crosstab_counts_grid())
    assert len(tables) == 1
    headers = tables[0].headers
    assert headers[:4] == ["question", "option", "metric", "Overall"]
    assert "USA" in headers
    assert "Japan" in headers
    assert "USA cluster 1" in headers
    assert "Global cluster 4" in headers
    assert headers.count("USA") == 1
    assert classify_table(headers, tables[0].rows) == "crosstab"


def test_crosstab_chunks_pair_value_and_percent_and_skip_junk() -> None:
    tables = _tables_from_grid("Crosstabulation Counts & %", _crosstab_counts_grid())
    table = tables[0]
    table.kind = "crosstab"
    chunks = table_to_chunks(table, "crosstab.xlsx")
    assert len(chunks) == 1
    text = chunks[0]["text"]
    assert "Question: What age group do you fall under?" in text
    assert "Answer: 25-34" in text
    assert "USA cluster 1: 10" in text
    assert "Column percentage:" in text
    assert "USA cluster 1: 5.0%" in text
    assert "hidden for country" not in text
    assert "${custom170}" not in text
    assert chunks[0]["metadata"]["sheet_kind"] == "crosstab"


def test_heatmap_sheets_are_skipped(tmp_path: Path) -> None:
    from openpyxl import Workbook

    assert _skip_duplicate_crosstab_sheet("Crosstabulation % Heat Map")
    assert _skip_duplicate_crosstab_sheet("Ranking Q Top 2 % Heat Map")
    assert not _skip_duplicate_crosstab_sheet("Crosstabulation Counts & %")

    path = tmp_path / "crosstab.xlsx"
    wb = Workbook()
    heat = wb.active
    assert heat is not None
    heat.title = "Crosstabulation % Heat Map"
    heat["A1"] = "USA"
    heat["B1"] = "USA"
    heat["C1"] = "USA"
    heat["D1"] = "USA"
    heat["A2"] = 1
    heat["B2"] = 2
    heat["C2"] = 3
    heat["D2"] = 4
    heat["E1"] = "Japan"
    heat["F1"] = "Japan"
    heat["G1"] = "Japan"
    heat["H1"] = "Japan"
    heat["E2"] = 1
    heat["F2"] = 2
    heat["G2"] = 3
    heat["H2"] = 4
    heat["A3"] = "Must Have"
    heat["A3"] = "Quiet"
    counts = wb.create_sheet("Ranking Q Top 2 Counts")
    counts["A1"] = None
    counts["B1"] = "Overall"
    counts["C1"] = "Global"
    counts["D1"] = "Global"
    counts["E1"] = "Global"
    counts["F1"] = "Global"
    counts["G1"] = "USA"
    counts["H1"] = "USA"
    counts["I1"] = "USA"
    counts["J1"] = "USA"
    for col, cid in enumerate([1, 2, 3, 4, 1, 2, 3, 4], start=3):
        counts.cell(2, col, cid)
    counts["A3"] = "Out of all the options below, please rank the top 3."
    counts["A4"] = "Brand website"
    counts["B4"] = 1153
    counts["C4"] = 33
    counts["D4"] = 763
    counts["E4"] = 200
    counts["F4"] = 157
    counts["G4"] = 10
    counts["H4"] = 20
    counts["I4"] = 30
    counts["J4"] = 40
    wb.save(path)

    chunks = excel_to_chunks(path)
    assert chunks
    assert all(c["metadata"]["excel_sheet"] != "Crosstabulation % Heat Map" for c in chunks)
    text = chunks[0]["text"]
    assert "Brand website" in text
    assert "Out of all the options below" in text
    assert "USA cluster 1: 10" in text
    assert any(c["metadata"].get("chunk_type") == "excel_catalog" for c in chunks)


def _write_crosstab_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Crosstabulation Counts & %"
    for row_index, row in enumerate(_crosstab_counts_grid(), start=1):
        for col_index, value in enumerate(row, start=1):
            sheet.cell(row_index, col_index, value)
    heat = wb.create_sheet("Crosstabulation % Heat Map")
    heat["A1"] = "USA"
    heat["A2"] = 1
    heat["A3"] = "Quiet"
    wb.save(path)


def test_crosstab_unpivot_and_catalog_sidecars(tmp_path: Path) -> None:
    path = tmp_path / "crosstab.xlsx"
    _write_crosstab_xlsx(path)

    chunks, long_rows, catalog = parse_excel_workbook(path)
    assert any(c["metadata"].get("chunk_type") == "excel_catalog" for c in chunks)
    assert all(row["sheet"] != "Crosstabulation % Heat Map" for row in long_rows)

    japan_pct = next(
        row
        for row in long_rows
        if row["question"] == "What age group do you fall under?"
        and row["option"] == "25-34"
        and row["country"] == "Japan"
        and row["cluster"] is None
        and row["metric"] == "pct"
    )
    assert japan_pct["value"] == pytest.approx(0.079)

    japan_c2 = next(
        row
        for row in long_rows
        if row["country"] == "Global"
        and row["cluster"] == 2
        and row["metric"] == "pct"
        and row["option"] == "25-34"
    )
    assert japan_c2["value"] == pytest.approx(0.2)

    age = next(entry for entry in catalog if "age group" in entry["question"].lower())
    assert "25-34" in age["options"]
    assert "Japan" in age["countries"]
    assert 2 in age["clusters"]

    dest = parse_tabular_input(path, tmp_path / "parse")
    long_path = dest.parent / "crosstab_long.jsonl.gz"
    catalog_path = dest.parent / "question_catalog.json"
    assert long_path.is_file()
    assert catalog_path.is_file()
    catalog_disk = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_disk[0]["question"]
