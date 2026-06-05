import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pikepdf
from PIL import Image

YOMITOKU_EXE = Path(
    r"C:\Users\kyone\AppData\Roaming\Python\Python311\Scripts\yomitoku.exe"
)
JBIG2_EXE = Path(r"C:\Users\kyone\Documents\jbig2enc\jbig2.exe")

# 使い方：
# cd C:\Users\kyone\scan
# py -3.11 jbig2_pdf.py "C:\Users\kyone\scan\10_Scan\250527_ウォルトン-フィクションとはなにか"

# コマンドライン引数を読み取る
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a searchable PDF and replace page images with JBIG2 backgrounds."
    )
    parser.add_argument(
        "scan_dir",
        type=Path,
        help="Scan directory containing an out subdirectory with source TIFF files.",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Final PDF filename. Defaults to the scan directory name with .pdf.",
    )
    return parser.parse_args()

# 外部コマンドを実行し、失敗時は例外にする
def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )

# YomiTokuの既定命名規則から単ページPDFパスを作る
def expected_yomitoku_pdf(yomitoku_dir: Path, input_dir: Path, tif: Path) -> Path:
    return yomitoku_dir / f"{input_dir.name}_{tif.stem}_p1.pdf"

# TIFFをOtsu二値化した1bit TIFFにする
def make_otsu_tif(src: Path, dest: Path) -> None:
    with Image.open(src) as img:
        gray = img.convert("L")
        dpi = img.info.get("dpi") or (300, 300)

    arr = np.array(gray)
    _, bw = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if dest.exists():
        dest.unlink()
    Image.fromarray(bw).convert("1").save(dest, compression="group4", dpi=dpi)

# TIFFのDPIをPDFポイントへの倍率に変換する
def dpi_scale(src: Path) -> tuple[float, float]:
    with Image.open(src) as img:
        dpi = img.info.get("dpi") or (300, 300)

    x_dpi, y_dpi = dpi
    if not x_dpi or not y_dpi:
        x_dpi, y_dpi = 300, 300
    return 72 / float(x_dpi), 72 / float(y_dpi)

# ページのコンテンツストリームをバイト列として読む
def page_contents_bytes(page: pikepdf.Page) -> bytes:
    contents = page.obj.get("/Contents", None)
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        return b"\n".join(stream.read_bytes() for stream in contents)
    return contents.read_bytes()

# TIFFのDPIに合わせてページ内容とページサイズを補正する
def set_physical_page_size(pdf: pikepdf.Pdf, page: pikepdf.Page, src_tif: Path) -> None:
    scale_x, scale_y = dpi_scale(src_tif)
    media_box = page.MediaBox
    width = float(media_box[2]) - float(media_box[0])
    height = float(media_box[3]) - float(media_box[1])
    new_box = pikepdf.Array([0, 0, width * scale_x, height * scale_y])

    wrapped = (
        f"q\n{scale_x:.12g} 0 0 {scale_y:.12g} 0 0 cm\n".encode("ascii")
        + page_contents_bytes(page)
        + b"\nQ\n"
    )
    page.Contents = pikepdf.Stream(pdf, wrapped)
    page.MediaBox = new_box
    page.CropBox = new_box

# 1bit TIFFをPDF埋め込み用JBIG2ストリームにする
def jbig2_stream(tif: Path) -> bytes:
    proc = run([str(JBIG2_EXE), "--pdf", str(tif)], capture=True)
    if not proc.stdout:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"jbig2 produced no stdout for {tif}: {stderr}")
    return proc.stdout

# OCR層を残したままYomiTokuの背景画像XObjectを差し替える
def replace_background_with_jbig2(
    pdf_path: Path, src_tif: Path, otsu_tif: Path, out_pdf: Path
) -> None:
    stream = jbig2_stream(otsu_tif)
    with Image.open(otsu_tif) as img:
        width, height = img.size

    with pikepdf.Pdf.open(pdf_path) as pdf:
        page = pdf.pages[0]
        xobjects = page.Resources.get("/XObject", {})
        image_entries = [
            (name, obj)
            for name, obj in xobjects.items()
            if obj.get("/Subtype", None) == pikepdf.Name("/Image")
        ]
        if len(pdf.pages) != 1 or len(image_entries) != 1:
            raise RuntimeError(f"Unexpected YomiToku PDF structure: {pdf_path}")

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

# 進捗を表示しながら単ページPDFを最終PDFへ結合する
def merge_pages(page_pdfs: list[Path], final_pdf: Path) -> None:
    tmp_pdf = final_pdf.with_name(f"{final_pdf.stem}.tmp{final_pdf.suffix}")
    if tmp_pdf.exists():
        tmp_pdf.unlink()

    final = pikepdf.Pdf.new()
    total = len(page_pdfs)
    for index, page_pdf in enumerate(page_pdfs, start=1):
        print(f"Merging pages: {index}/{total}", flush=True)
        with pikepdf.Pdf.open(page_pdf) as src:
            final.pages.extend(src.pages)

    final.remove_unreferenced_resources()
    final.save(
        tmp_pdf,
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        deterministic_id=True,
    )
    if final_pdf.exists():
        final_pdf.unlink()
    tmp_pdf.replace(final_pdf)

# OCR PDF生成、JBIG2差し替え、結合を順に実行する
def main() -> int:
    args = parse_args()
    scan_dir = args.scan_dir
    input_dir = scan_dir / "out"
    output_name = Path(args.output_name).name if args.output_name else f"{scan_dir.name}.pdf"
    out_dir = scan_dir / "yomitoku"

    if not scan_dir.is_dir():
        raise FileNotFoundError(f"Scan directory not found: {scan_dir}")
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input TIFF directory not found: {input_dir}")

    tifs = sorted(input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {input_dir}")

    cache_dir = input_dir / "cache"
    if cache_dir.exists():
        print(f"Removing cache: {cache_dir}", flush=True)
        shutil.rmtree(cache_dir)

    final_pdf = out_dir / output_name
    yomitoku_dir = out_dir / "yomitoku_pdf"
    otsu_tif_dir = out_dir / "otsu_tif"
    page_pdf_dir = out_dir / "jbig2_pages"
    for path in (out_dir, yomitoku_dir, otsu_tif_dir, page_pdf_dir):
        path.mkdir(parents=True, exist_ok=True)

    yomi_pdfs = [expected_yomitoku_pdf(yomitoku_dir, input_dir, tif) for tif in tifs]
    if all(pdf.exists() for pdf in yomi_pdfs):
        print("Reusing existing YomiToku PDFs", flush=True)
    else:
        run(
            [
                str(YOMITOKU_EXE),
                str(input_dir),
                "-f",
                "pdf",
                "--pdf_quality",
                "high",
                "-o",
                str(yomitoku_dir),
            ]
        )

    page_pdfs = []
    total = len(tifs)
    for index, (tif, yomi_pdf) in enumerate(zip(tifs, yomi_pdfs), start=1):
        if not yomi_pdf.exists():
            raise FileNotFoundError(f"YomiToku PDF was not created: {yomi_pdf}")

        otsu_tif = otsu_tif_dir / tif.name
        page_pdf = page_pdf_dir / f"{tif.stem}.pdf"
        print(f"[{index}/{total}] {tif.name}: Otsu TIFF", flush=True)
        make_otsu_tif(tif, otsu_tif)
        print(f"[{index}/{total}] {tif.name}: JBIG2 PDF", flush=True)
        replace_background_with_jbig2(yomi_pdf, tif, otsu_tif, page_pdf)
        page_pdfs.append(page_pdf)

    merge_pages(page_pdfs, final_pdf)
    print(f"Final PDF: {final_pdf}", flush=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise
