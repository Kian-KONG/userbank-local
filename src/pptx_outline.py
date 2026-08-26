from __future__ import annotations

import zipfile
from pathlib import Path

try:
    from defusedxml import ElementTree as ET
except ImportError:  # local ingest of user-owned PPTX
    from xml.etree import ElementTree as ET

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def extract_pptx_slide_titles(path: Path) -> dict[int, str]:
    """Best-effort slide titles from PPTX zip XML. 1-based page numbers."""
    if path.suffix.lower() not in {".pptx", ".pptm"}:
        return {}
    try:
        with zipfile.ZipFile(path) as zf:
            order = _slide_order(zf)
            titles: dict[int, str] = {}
            for index, slide_name in enumerate(order, start=1):
                try:
                    xml = zf.read(slide_name)
                except KeyError:
                    continue
                title = _first_text(xml)
                if title:
                    titles[index] = title
            return titles
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return {}


def _slide_order(zf: zipfile.ZipFile) -> list[str]:
    try:
        rels = ET.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
    except KeyError:
        names = [
            name
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]
        return sorted(names, key=_slide_sort_key)
    rel_map = {}
    for rel in rels:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            rel_map[rid] = target
    try:
        presentation = ET.fromstring(zf.read("ppt/presentation.xml"))
    except KeyError:
        return []
    ordered: list[str] = []
    for sld_id in presentation.findall(".//p:sldIdLst/p:sldId", _NS):
        rid = sld_id.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = rel_map.get(rid or "")
        if not target:
            continue
        if target.startswith("/"):
            ordered.append(target.lstrip("/"))
        else:
            ordered.append(str(Path("ppt") / target).replace("\\", "/"))
    return ordered


def _slide_sort_key(name: str) -> tuple[int, str]:
    digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
    return (int(digits) if digits else 0, name)


def _first_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    parts: list[str] = []
    for node in root.findall(".//a:t", _NS):
        text = (node.text or "").strip()
        if text:
            parts.append(text)
        if sum(len(p) for p in parts) >= 180:
            break
    return " ".join(parts).strip()[:180]
