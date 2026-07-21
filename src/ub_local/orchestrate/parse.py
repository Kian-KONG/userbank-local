from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ub_local.config import get_settings


def check_mineru() -> dict:
    settings = get_settings()
    path = settings.resolved_mineru_dir()
    ok = path.is_dir()
    mineru_bin = shutil.which("mineru")
    venv_bin = path / ".venv" / "bin" / "mineru"
    return {
        "ok": ok,
        "path": str(path),
        "cli": mineru_bin or (str(venv_bin) if venv_bin.is_file() else None),
    }


def check_deepread() -> dict:
    settings = get_settings()
    path = settings.resolved_deepread_dir()
    entry = path / "deepread.py"
    return {"ok": path.is_dir() and entry.is_file(), "path": str(path), "entry": str(entry)}


def run_mineru(input_path: Path, output_dir: Path, log=print) -> Path:
    """Run MinerU CLI on a PDF/Office file. Returns output directory with markdown."""
    settings = get_settings()
    status = check_mineru()
    if not status["ok"]:
        raise RuntimeError(f"MinerU not found at {status['path']}")
    cli = status["cli"]
    if not cli:
        raise RuntimeError(
            "mineru CLI not found. Install: pip install -e '../MinerU[core]' "
            "(CN: -i https://pypi.tuna.tsinghua.edu.cn/simple)"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        cli,
        "-p",
        str(input_path),
        "-o",
        str(output_dir),
        "-b",
        settings.mineru_backend,
    ]
    if settings.mineru_backend == "vlm-http-client":
        cmd.extend(["-u", settings.mineru_api_url])
    log(f"running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"mineru failed ({proc.returncode}): {proc.stderr[-2000:] or proc.stdout[-2000:]}"
        )
    return output_dir


def run_deepread_parse(
    input_path: Path,
    output_dir: Path,
    *,
    name: str | None = None,
    log=print,
) -> Path:
    """Parse PDF or markdown into DeepRead *_corpus.json. Returns corpus path."""
    settings = get_settings()
    status = check_deepread()
    if not status["ok"]:
        raise RuntimeError(f"DeepRead not found at {status['path']}")
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_name = name or input_path.stem
    py = settings.mineru_python
    deepread_py = Path(status["entry"])
    cmd = [
        py,
        str(deepread_py),
        "parse",
        str(input_path),
        "-o",
        str(output_dir),
        "--name",
        doc_name,
    ]
    log(f"running: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(deepread_py.parent),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"deepread parse failed ({proc.returncode}): "
            f"{proc.stderr[-2000:] or proc.stdout[-2000:]}"
        )
    corpus = output_dir / f"{doc_name}_corpus.json"
    if not corpus.is_file():
        # DeepRead may write name_corpus.json variants
        matches = list(output_dir.glob("*_corpus.json"))
        if not matches:
            raise RuntimeError(f"deepread produced no *_corpus.json under {output_dir}")
        corpus = matches[0]
    return corpus


def parse_document(
    input_path: Path | str,
    work_dir: Path | str,
    *,
    skip_mineru: bool = False,
    log=print,
) -> Path:
    """
    Full local parse: optional MinerU then DeepRead → *_corpus.json.
    If input is already .md / .json, skip MinerU.
    """
    src = Path(input_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    out = Path(work_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    parse_dir = out / f"parse_{src.stem}"
    parse_dir.mkdir(parents=True, exist_ok=True)

    lower = src.suffix.lower()
    if lower in {".md", ".markdown"} or skip_mineru:
        return run_deepread_parse(src, parse_dir, name=src.stem, log=log)
    if lower == ".json" and src.name.endswith("_corpus.json"):
        dest = parse_dir / src.name
        dest.write_bytes(src.read_bytes())
        return dest

    # PDF / Office → MinerU → find md → DeepRead
    mineru_out = parse_dir / "mineru"
    run_mineru(src, mineru_out, log=log)
    md_files = list(mineru_out.rglob("*.md"))
    if not md_files:
        # fall back: DeepRead may OCR PDF directly
        log("MinerU produced no markdown; trying DeepRead on original PDF")
        return run_deepread_parse(src, parse_dir, name=src.stem, log=log)
    md = sorted(md_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return run_deepread_parse(md, parse_dir, name=src.stem, log=log)
