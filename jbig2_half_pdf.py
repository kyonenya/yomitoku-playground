import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pikepdf
from pdfminer.high_level import extract_text
from PIL import Image


# YomiToku は scan プロジェクトの uv venv 内に導入される。
# `uv run jbig2_half_pdf.py ...` で実行すると venv の Scripts が PATH に乗るため which で解決できる。
# 環境変数 YOMITOKU_EXE で明示的に上書きも可能。
YOMITOKU_EXE = os.environ.get("YOMITOKU_EXE") or shutil.which("yomitoku") or "yomitoku"

# jbig2enc のネイティブ実行ファイル。環境変数 JBIG2_EXE 優先、無ければ PATH から解決。
JBIG2_EXE = os.environ.get("JBIG2_EXE") or shutil.which("jbig2") or "jbig2"

PDF_STABLE_SECONDS = 0.4
POLL_SECONDS = 0.2


@dataclass(frozen=True)
class PageJob:
    index: int
    tif: Path
    yomi_pdf: Path
    half_tif: Path
    page_pdf: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a searchable PDF with YomiToku, then replace page images "
            "with half-resolution JBIG2 backgrounds."
        )
    )
    parser.add_argument("input_dir", type=Path, help="Directory containing source TIFF files.")
    parser.add_argument(
        "--output-name",
        default=None,
        help=(
            "Final PDF filename. Defaults to the input directory's parent "
            "folder name with .pdf."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to input_dir.parent / output name stem.",
    )
    return parser.parse_args()


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def expected_yomitoku_pdf(yomitoku_dir: Path, input_dir: Path, tif: Path) -> Path:
    return yomitoku_dir / f"{input_dir.name}_{tif.stem}_p1.pdf"


def make_half_tif(src: Path, dest: Path) -> None:
    if dest.exists():
        return

    with Image.open(src) as img:
        gray = img.convert("L")
        width, height = gray.size
        half = gray.resize(
            (max(1, width // 2), max(1, height // 2)),
            Image.Resampling.LANCZOS,
        )

    arr = np.array(half)
    _, bw = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    Image.fromarray(bw).convert("1").save(dest, compression="group4", dpi=(300, 300))


def dpi_scale(src: Path) -> tuple[float, float]:
    with Image.open(src) as img:
        dpi = img.info.get("dpi") or (600, 600)

    x_dpi, y_dpi = dpi
    if not x_dpi or not y_dpi:
        x_dpi, y_dpi = 600, 600
    return 72 / float(x_dpi), 72 / float(y_dpi)


def page_contents_bytes(page: pikepdf.Page) -> bytes:
    contents = page.obj.get("/Contents", None)
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        return b"\n".join(stream.read_bytes() for stream in contents)
    return contents.read_bytes()


def set_physical_page_size(pdf: pikepdf.Pdf, page: pikepdf.Page, src_tif: Path) -> None:
    scale_x, scale_y = dpi_scale(src_tif)
    media_box = page.MediaBox
    width = float(media_box[2]) - float(media_box[0])
    height = float(media_box[3]) - float(media_box[1])
    new_box = pikepdf.Array([0, 0, width * scale_x, height * scale_y])

    original_contents = page_contents_bytes(page)
    wrapped = (
        f"q\n{scale_x:.12g} 0 0 {scale_y:.12g} 0 0 cm\n".encode("ascii")
        + original_contents
        + b"\nQ\n"
    )
    page.Contents = pikepdf.Stream(pdf, wrapped)
    page.MediaBox = new_box
    page.CropBox = new_box


def jbig2_stream(tif: Path) -> bytes:
    proc = run([str(JBIG2_EXE), "--pdf", str(tif)], capture=True)
    if not proc.stdout:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"jbig2 produced no stdout for {tif}: {stderr}")
    return proc.stdout


def replace_background_with_jbig2(
    pdf_path: Path, src_tif: Path, half_tif: Path, out_pdf: Path
) -> None:
    stream = jbig2_stream(half_tif)
    with Image.open(half_tif) as img:
        width, height = img.size

    with pikepdf.Pdf.open(pdf_path) as pdf:
        if len(pdf.pages) != 1:
            raise RuntimeError(f"Expected one page PDF: {pdf_path}")

        page = pdf.pages[0]
        xobjects = page.Resources.get("/XObject", {})
        image_entries = [
            (name, obj)
            for name, obj in xobjects.items()
            if obj.get("/Subtype", None) == pikepdf.Name("/Image")
        ]
        if len(image_entries) != 1:
            raise RuntimeError(
                f"Expected one image XObject in {pdf_path}, found {len(image_entries)}"
            )

        image_name, _ = image_entries[0]
        xobjects[image_name] = pikepdf.Stream(
            pdf,
            stream,
            {
                "/Type": pikepdf.Name("/XObject"),
                "/Subtype": pikepdf.Name("/Image"),
                "/Width": width,
                "/Height": height,
                "/BitsPerComponent": 1,
                "/ColorSpace": pikepdf.Name("/DeviceGray"),
                "/Filter": pikepdf.Name("/JBIG2Decode"),
            },
        )
        set_physical_page_size(pdf, page, src_tif)
        if out_pdf.exists():
            out_pdf.unlink()
        pdf.save(out_pdf)


def process_page(job: PageJob, total: int) -> Path:
    print(f"[{job.index}/{total}] {job.tif.name}: half TIFF", flush=True)
    make_half_tif(job.tif, job.half_tif)

    print(f"[{job.index}/{total}] {job.tif.name}: JBIG2 replace", flush=True)
    replace_background_with_jbig2(job.yomi_pdf, job.tif, job.half_tif, job.page_pdf)
    return job.page_pdf


def pdf_is_complete(path: Path, last_seen: dict[Path, tuple[int, float, float]]) -> bool:
    if not path.exists():
        return False

    now = time.monotonic()
    size = path.stat().st_size
    old_size, old_time, complete_time = last_seen.get(path, (-1, now, 0.0))
    if size != old_size:
        last_seen[path] = (size, now, 0.0)
        return False

    if now - old_time < PDF_STABLE_SECONDS:
        return False

    if complete_time:
        return True

    try:
        with pikepdf.Pdf.open(path) as pdf:
            complete = len(pdf.pages) == 1
    except pikepdf.PdfError:
        return False

    if complete:
        last_seen[path] = (size, old_time, now)
    return complete


def launch_yomitoku(input_dir: Path, yomitoku_dir: Path) -> subprocess.Popen:
    cmd = [
        str(YOMITOKU_EXE),
        str(input_dir),
        "-f",
        "pdf",
        "--pdf_quality",
        "high",
        "-o",
        str(yomitoku_dir),
    ]
    print("Starting YomiToku:", " ".join(cmd), flush=True)
    return subprocess.Popen(cmd)


def merge_pages(page_pdfs: list[Path], final_pdf: Path) -> None:
    final = pikepdf.Pdf.new()
    for page_pdf in page_pdfs:
        with pikepdf.Pdf.open(page_pdf) as src:
            final.pages.extend(src.pages)
    final.save(final_pdf)


def count_jbig2_pages(pdf_path: Path) -> int:
    count = 0
    with pikepdf.Pdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            xobjects = page.Resources.get("/XObject", {})
            for obj in xobjects.values():
                if (
                    obj.get("/Subtype", None) == pikepdf.Name("/Image")
                    and obj.get("/Filter", None) == pikepdf.Name("/JBIG2Decode")
                ):
                    count += 1
    return count


def count_text_pages(pdf_path: Path, page_count: int) -> int:
    text_pages = 0
    for page_number in range(page_count):
        text = extract_text(str(pdf_path), page_numbers=[page_number])
        if text.strip():
            text_pages += 1
    return text_pages


def verify(
    final_pdf: Path,
    tifs: list[Path],
    yomitoku_dir: Path,
    page_pdf_dir: Path,
) -> None:
    with pikepdf.Pdf.open(final_pdf) as pdf:
        page_count = len(pdf.pages)

    yomi_pdfs = list(yomitoku_dir.glob("*.pdf"))
    page_pdfs = list(page_pdf_dir.glob("*.pdf"))
    text_pages = count_text_pages(final_pdf, page_count)
    jbig2_pages = count_jbig2_pages(final_pdf)
    yomi_size = sum(p.stat().st_size for p in yomi_pdfs)
    final_size = final_pdf.stat().st_size

    print(f"Final PDF: {final_pdf}", flush=True)
    print(f"Pages: {page_count}", flush=True)
    print(f"OCR text pages: {text_pages}", flush=True)
    print(f"JBIG2 image pages: {jbig2_pages}", flush=True)
    print(f"YomiToku PDFs: {len(yomi_pdfs)}", flush=True)
    print(f"Lightweight page PDFs: {len(page_pdfs)}", flush=True)
    print(f"YomiToku total size: {yomi_size / 1024 / 1024:.3f} MB", flush=True)
    print(f"Final size: {final_size / 1024 / 1024:.3f} MB", flush=True)
    if yomi_size:
        print(f"Ratio: {final_size / yomi_size * 100:.1f}%", flush=True)

    expected = len(tifs)
    if page_count != expected:
        raise RuntimeError(f"Final page count mismatch: {page_count} != {expected}")
    if len(yomi_pdfs) != expected:
        raise RuntimeError(f"YomiToku PDF count mismatch: {len(yomi_pdfs)} != {expected}")
    if len(page_pdfs) != expected:
        raise RuntimeError(f"Page PDF count mismatch: {len(page_pdfs)} != {expected}")
    if text_pages != expected:
        raise RuntimeError(f"OCR text page count mismatch: {text_pages} != {expected}")
    if jbig2_pages != expected:
        raise RuntimeError(f"JBIG2 page count mismatch: {jbig2_pages} != {expected}")


def main() -> int:
    args = parse_args()

    input_dir = args.input_dir
    output_name = Path(args.output_name).name if args.output_name else f"{input_dir.parent.name}.pdf"
    out_dir = args.out_dir or (input_dir.parent / Path(output_name).stem)
    final_pdf = out_dir / output_name
    yomitoku_dir = out_dir / "yomitoku_pdf"
    half_tif_dir = out_dir / "half_tif"
    page_pdf_dir = out_dir / "jbig2_pages"

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    if is_relative_to(out_dir, input_dir):
        raise ValueError(f"--out-dir must not be inside input_dir: {out_dir}")

    tifs = sorted(input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {input_dir}")

    cache_dir = input_dir / "cache"
    if cache_dir.exists():
        print(f"Removing cache: {cache_dir}", flush=True)
        shutil.rmtree(cache_dir)

    for path in (out_dir, yomitoku_dir, half_tif_dir, page_pdf_dir):
        path.mkdir(parents=True, exist_ok=True)

    expected_jobs = [
        PageJob(
            index=index,
            tif=tif,
            yomi_pdf=expected_yomitoku_pdf(yomitoku_dir, input_dir, tif),
            half_tif=half_tif_dir / tif.name,
            page_pdf=page_pdf_dir / f"{tif.stem}.pdf",
        )
        for index, tif in enumerate(tifs, start=1)
    ]

    print(f"TIFF files: {len(tifs)}", flush=True)
    submitted: set[Path] = set()
    completed: set[Path] = set()
    last_seen: dict[Path, tuple[int, float, float]] = {}

    yomi_proc = None
    if all(job.yomi_pdf.exists() for job in expected_jobs):
        print("Reusing existing YomiToku PDFs", flush=True)
    else:
        yomi_proc = launch_yomitoku(input_dir, yomitoku_dir)

    try:
        while len(completed) < len(expected_jobs):
            made_progress = False
            for job in expected_jobs:
                if job.yomi_pdf in submitted:
                    continue
                if pdf_is_complete(job.yomi_pdf, last_seen):
                    print(f"[{job.index}/{len(tifs)}] {job.tif.name}: PDF ready", flush=True)
                    submitted.add(job.yomi_pdf)
                    try:
                        completed.add(process_page(job, len(tifs)))
                    except Exception as exc:
                        if yomi_proc and yomi_proc.poll() is None:
                            yomi_proc.terminate()
                        raise RuntimeError(f"Failed to process {job.tif.name}") from exc
                    made_progress = True

            if yomi_proc and yomi_proc.poll() is not None and yomi_proc.returncode != 0:
                raise RuntimeError(f"YomiToku failed with exit code {yomi_proc.returncode}")

            if yomi_proc and yomi_proc.poll() is not None:
                missing = [job.yomi_pdf for job in expected_jobs if not job.yomi_pdf.exists()]
                if missing:
                    raise RuntimeError(f"YomiToku finished but PDFs are missing: {missing[:3]}")

            if not made_progress:
                time.sleep(POLL_SECONDS)
    finally:
        if yomi_proc and yomi_proc.poll() is None:
            yomi_proc.wait()

    page_pdfs = [job.page_pdf for job in expected_jobs]
    missing_pages = [p for p in page_pdfs if not p.exists()]
    if missing_pages:
        raise RuntimeError(f"Missing lightweight page PDFs: {missing_pages[:3]}")

    print("Merging pages", flush=True)
    merge_pages(page_pdfs, final_pdf)
    verify(final_pdf, tifs, yomitoku_dir, page_pdf_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise
