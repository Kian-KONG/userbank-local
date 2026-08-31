from pathlib import Path

from src.deck_synth import merge_synth_parts, parse_synth_json
from src.flatten import flatten_deck, flatten_for_export, format_overview_text


def test_flatten_deck_includes_overview_and_page_prefix():
    corpus = {
        "source_type": "image",
        "overview": {
            "argument": "Heat pumps grow in Germany.",
            "outline": [
                {
                    "section": "Market",
                    "pages": [1, 2],
                    "claim": "Installed base is rising",
                }
            ],
        },
        "pages": [
            {
                "page_number": 2,
                "title": "DELTA-EE",
                "description": "Stacked bars by year.",
                "section": "Market",
                "role": "evidence",
                "continues": 1,
                "refers_to": [1],
            }
        ],
    }
    points = flatten_deck(corpus, "doc-1")
    assert points[0]["id"] == "doc-1:overview"
    assert points[0]["text"].startswith("[deck_overview]")
    assert "Heat pumps grow" in points[0]["text"]
    assert points[0]["metadata"]["chunk_type"] == "deck_overview"
    assert points[0]["metadata"]["page_number"] == 0
    assert points[1]["id"] == "doc-1:2"
    assert points[1]["text"].startswith("[Slide 2 | Market | evidence | continues 1]")
    assert "Stacked bars" in points[1]["text"]
    assert points[1]["metadata"]["refers_to"] == [1]


def test_flatten_for_export_routes_image_corpus():
    corpus = {
        "source_type": "image",
        "overview": {"argument": "A", "outline": []},
        "pages": [
            {
                "page_number": 1,
                "description": "Title slide",
                "section": "",
                "role": "title",
            }
        ],
    }
    points = flatten_for_export(corpus, "x")
    assert any(p["metadata"]["chunk_type"] == "deck_overview" for p in points)
    assert any(p["metadata"]["chunk_type"] == "image_page" for p in points)


def test_parse_synth_json_fills_missing_pages_and_roles():
    raw = """
    ```json
    {
      "argument": "Thesis",
      "outline": [{"section": "Intro", "pages": [1], "claim": "hook"}],
      "pages": [{"page": 1, "section": "Intro", "role": "weird", "continues": "x", "refers_to": [2, "no"]}]
    }
    ```
    """
    parsed = parse_synth_json(raw, [1, 2])
    assert parsed["argument"] == "Thesis"
    assert parsed["pages"][0]["role"] == "evidence"
    assert parsed["pages"][0]["continues"] is None
    assert parsed["pages"][0]["refers_to"] == [2]
    assert parsed["pages"][1]["page"] == 2
    assert parsed["pages"][1]["role"] == "evidence"


def test_merge_synth_parts_joins_windows():
    merged = merge_synth_parts(
        [
            {
                "argument": "Buyers first.",
                "outline": [{"section": "Buyers", "pages": [1], "claim": "who"}],
                "pages": [
                    {
                        "page": 1,
                        "section": "Buyers",
                        "role": "title",
                        "continues": None,
                        "refers_to": [],
                    }
                ],
            },
            {
                "argument": "Installers next.",
                "outline": [{"section": "Installers", "pages": [2], "claim": "who"}],
                "pages": [
                    {
                        "page": 2,
                        "section": "Installers",
                        "role": "evidence",
                        "continues": None,
                        "refers_to": [],
                    }
                ],
            },
        ],
        [1, 2, 3],
    )
    assert merged["argument"] == "Buyers first. Installers next."
    assert [entry["section"] for entry in merged["outline"]] == ["Buyers", "Installers"]
    assert merged["pages"][0]["role"] == "title"
    assert merged["pages"][2]["page"] == 3
    assert merged["pages"][2]["role"] == "evidence"


def test_convert_office_pdf_passthrough(tmp_path: Path):
    from src.image_ingest import convert_office_to_pdf

    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert convert_office_to_pdf(pdf, tmp_path / "office") == pdf


def test_ppt_raster_uses_local_python_not_mineru(monkeypatch, tmp_path: Path):
    import sys

    from src.image_ingest import render_pdf_pages

    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        out = tmp_path / "pages"
        out.mkdir(parents=True, exist_ok=True)
        (out / "page_001.png").write_bytes(b"png")
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": "1"})()

    monkeypatch.setattr("src.image_ingest.subprocess.run", fake_run)
    pages = render_pdf_pages(tmp_path / "deck.pdf", tmp_path / "pages")
    assert seen["cmd"][0] == sys.executable
    assert "resolved_mineru_python" not in "".join(seen["cmd"])
    assert pages[0].name == "page_001.png"


def test_vision_checkpoint_roundtrip(tmp_path: Path):
    from src.image_ingest import _load_vision_checkpoint, _save_vision_checkpoint

    _save_vision_checkpoint(
        tmp_path,
        [{"page_number": 2, "title": "Market", "description": "Heat pumps"}],
    )
    cached = _load_vision_checkpoint(tmp_path)
    assert cached[2]["description"] == "Heat pumps"
    assert _load_vision_checkpoint(tmp_path / "missing") == {}
