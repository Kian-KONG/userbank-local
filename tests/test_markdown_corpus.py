import json
from pathlib import Path

from src.flatten import flatten_corpus
from src.markdown_corpus import parse_markdown_to_corpus, write_corpus


def test_parse_splits_headings_and_keeps_html_table() -> None:
    text = "\n".join(
        [
            "# Boilers",
            "",
            "Intro paragraph.",
            "",
            "<table><tr><td>Gas Wall Hung</td><td>383 020</td></tr></table>",
            "",
            "# Heat Pumps",
            "",
            "Another section.",
            "",
        ]
    )
    corpus = parse_markdown_to_corpus(text, filename="doc.md")
    titles = [n["title"] for n in corpus["nodes"]]
    assert titles == ["Boilers", "Heat Pumps"]
    boilers = corpus["nodes"][0]
    assert boilers["paragraphs"][0] == "Intro paragraph."
    assert "<table>" in boilers["paragraphs"][1]
    assert "383 020" in boilers["paragraphs"][1]


def test_image_path_resolves_against_markdown_dir(tmp_path: Path) -> None:
    md_dir = tmp_path / "mineru_out"
    img = md_dir / "chunk_0000-0049" / "images"
    img.mkdir(parents=True)
    pic = img / "chart.jpg"
    pic.write_bytes(b"x")
    md = md_dir / "merged.md"
    md.write_text(
        "# Cover\n\n![](chunk_0000-0049/images/chart.jpg)\n",
        encoding="utf-8",
    )
    dest = write_corpus(md, tmp_path / "parse")
    corpus = json.loads(dest.read_text(encoding="utf-8"))
    para = corpus["nodes"][0]["paragraphs"][0]
    assert para["type"] == "image"
    assert para["image_path"] == str(pic)
    assert (tmp_path / "parse" / "doc.md").is_file()


def test_flatten_keeps_table_as_one_chunk() -> None:
    corpus = parse_markdown_to_corpus(
        "# A\n\n<table><tr><td>1</td></tr></table>\n",
        filename="doc.md",
    )
    points = flatten_corpus(corpus, "doc-1")
    assert len(points) == 1
    assert points[0]["metadata"]["section_title"] == "A"
    assert "<table>" in points[0]["text"]
