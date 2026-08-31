from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DECK_SUFFIXES = {".ppt", ".pptx", ".pptm"}
WORD_SUFFIXES = {".doc", ".docx"}
OFFICE_SUFFIXES = DECK_SUFFIXES | WORD_SUFFIXES


def _convert_timeout_seconds(input_path: Path) -> float:
    size = input_path.stat().st_size if input_path.is_file() else 0
    if size >= 50 * 1024 * 1024:
        return 1800
    return 600


def soffice_bin() -> str | None:
    return shutil.which("soffice") or shutil.which("soffice.bin")


def check_soffice() -> dict:
    path = soffice_bin()
    return {"ok": bool(path), "path": path or ""}


def convert_office_to_pdf(
    input_path: Path,
    work: Path,
    *,
    allowed: set[str] | None = None,
) -> Path:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        return input_path
    allowed = allowed if allowed is not None else OFFICE_SUFFIXES
    if suffix not in allowed:
        names = ", ".join(sorted(allowed | {".pdf"}))
        raise RuntimeError(f"LibreOffice convert accepts {names}, got {input_path.name}")
    soffice = soffice_bin()
    if not soffice:
        raise RuntimeError(
            f"{suffix} needs LibreOffice (`soffice`) on PATH, or export to PDF first"
        )
    work.mkdir(parents=True, exist_ok=True)
    converted = work / f"{input_path.stem}.pdf"
    if (
        converted.is_file()
        and converted.stat().st_size > 0
        and converted.stat().st_mtime >= input_path.stat().st_mtime
    ):
        return converted
    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(input_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_convert_timeout_seconds(input_path),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"LibreOffice convert failed: {detail}")
    if converted.exists():
        return converted
    matches = sorted(work.glob("*.pdf"))
    if not matches:
        raise RuntimeError(f"LibreOffice produced no PDF under {work}")
    return matches[0]
