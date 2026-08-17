import json
from pathlib import Path

from src.orchestrate import (
    _mineru_client_cmd,
    _page_chunks,
    find_markdown,
    parse_document,
)


def test_find_markdown_prefers_nested_vlm_output(tmp_path: Path) -> None:
    vlm = tmp_path / "BRG" / "vlm"
    vlm.mkdir(parents=True)
    md = vlm / "BRG.md"
    md.write_text("# hello\n", encoding="utf-8")
    (tmp_path / "ignore_origin.md").write_text("skip\n", encoding="utf-8")
    found = find_markdown(tmp_path)
    assert found == md


def test_find_markdown_prefers_hybrid_auto_output(tmp_path: Path) -> None:
    hybrid = tmp_path / "BRG" / "hybrid_auto"
    hybrid.mkdir(parents=True)
    md = hybrid / "BRG.md"
    md.write_text("# hybrid\n", encoding="utf-8")
    (tmp_path / "ignore_origin.md").write_text("skip\n", encoding="utf-8")
    found = find_markdown(tmp_path)
    assert found == md


def test_page_chunks_cover_odd_remainders() -> None:
    assert _page_chunks(211, 128) == [(0, 127), (128, 210)]
    assert _page_chunks(50, 128) == [(0, 49)]
    assert _page_chunks(128, 128) == [(0, 127)]


def test_mineru_client_cmd_keeps_tables_when_formula_disabled(tmp_path: Path) -> None:
    cmd = _mineru_client_cmd(
        py="python",
        pdf_path=tmp_path / "doc.pdf",
        chunk_dir=tmp_path / "out",
        start=0,
        end=127,
        backend="vlm-engine",
        formula=False,
        table=True,
        effort="high",
        api_url="http://127.0.0.1:8757",
    )
    assert cmd[cmd.index("-f") + 1] == "false"
    assert cmd[cmd.index("-t") + 1] == "true"
    assert "--effort" not in cmd


def test_parse_document_resolves_relative_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("# Hello\n\nworld\n", encoding="utf-8")

    result = parse_document(Path("doc.md"), Path("output/brg-2024/parse"))
    assert result.is_absolute()
    dest = (tmp_path / "output/brg-2024/parse/doc_corpus.json").resolve()
    assert result == dest
    corpus = json.loads(dest.read_text(encoding="utf-8"))
    assert corpus["nodes"][0]["title"] == "Hello"
    assert corpus["nodes"][0]["paragraphs"] == ["world"]
