from pathlib import Path

from src.orchestrate import find_markdown, parse_document


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


def test_parse_document_resolves_relative_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("hello\n\nworld\n", encoding="utf-8")

    def fake_deepread(md_path: Path, work: Path) -> Path:
        assert work.is_absolute()
        assert md_path.is_absolute()
        dest = work / "doc_corpus.json"
        dest.write_text("{}", encoding="utf-8")
        return dest

    monkeypatch.setattr("src.orchestrate._deepread_parse_markdown", fake_deepread)
    result = parse_document(Path("doc.md"), Path("output/brg-2024/parse"))
    assert result.is_absolute()
    assert result == (tmp_path / "output/brg-2024/parse/doc_corpus.json").resolve()
