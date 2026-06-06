import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pikepdf
from PIL import Image

JBIG2ENC_EXE = Path(__file__).resolve().parent / "jbig2enc-0.31-Windows-X64-MSVC" / "bin" / "jbig2.exe"

# コマンドライン引数を読み取る
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a searchable PDF and replace page images with JBIG2 backgrounds."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing source TIFF files directly.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output.pdf"),
        help="Final PDF path. Defaults to output.pdf in the current directory.",
    )
    parser.add_argument(
        "-w",
        "--workdir",
        type=Path,
        default=None,
        help="Directory for YomiToku OCR PDF work files. Defaults to the input directory's parent.",
    )
    parser.add_argument(
        "--half",
        action="store_true",
        help="Downscale each page to half resolution before binarization (smaller PDF).",
    )
    return parser.parse_args()

# TIFFをOtsu二値化した1bit TIFFにする。half=True なら二値化前に半分解像度へ縮小する
def make_otsu_tif(src: Path, dest: Path, *, half: bool = False) -> None:
    with Image.open(src) as img:
        gray = img.convert("L")
        dpi = img.info.get("dpi")
        if dpi is None:
            raise RuntimeError(f"TIFF DPI metadata is missing: {src}")
        if half:
            width, height = gray.size
            gray = gray.resize(
                (max(1, width // 2), max(1, height // 2)),
                Image.Resampling.LANCZOS,
            )

    _, bw_img = cv2.threshold(np.array(gray), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if dest.exists(): dest.unlink()
    Image.fromarray(bw_img).convert("1").save(dest, compression="group4", dpi=dpi)

# TIFFのDPIに合わせてページ内容とページサイズを補正する
def set_physical_page_size(pdf: pikepdf.Pdf, page: pikepdf.Page, src_tif: Path) -> None:
    def dpi_scale(src: Path) -> tuple[float, float]:
        with Image.open(src) as img:
            x_dpi, y_dpi = img.info.get("dpi")
        return 72 / float(x_dpi), 72 / float(y_dpi)

    scale_x, scale_y = dpi_scale(src_tif)
    contents = page.obj.get("/Contents", None)
    if contents is None:
        content_bytes = b""
    elif isinstance(contents, pikepdf.Array):
        content_bytes = b"\n".join(stream.read_bytes() for stream in contents)
    else:
        content_bytes = contents.read_bytes()

    media_box = page.MediaBox
    width = float(media_box[2]) - float(media_box[0])
    height = float(media_box[3]) - float(media_box[1])
    new_box = pikepdf.Array([0, 0, width * scale_x, height * scale_y])

    wrapped = (
        f"q\n{scale_x:.12g} 0 0 {scale_y:.12g} 0 0 cm\n".encode("ascii")
        + content_bytes
        + b"\nQ\n"
    )
    page.Contents = pikepdf.Stream(pdf, wrapped)
    page.MediaBox = new_box
    page.CropBox = new_box

# OCR層を残したままYomiTokuの背景画像XObjectをJBIG2へ差し替えた単ページPDFを返す
def replace_background_with_jbig2(
    pdf_path: Path, src_tif: Path, otsu_tif: Path
) -> pikepdf.Pdf:
    if not JBIG2ENC_EXE.is_file():
        raise FileNotFoundError(f"jbig2enc executable not found: {JBIG2ENC_EXE}")

    proc = subprocess.run(
        [str(JBIG2ENC_EXE), "--pdf", str(otsu_tif)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not proc.stdout:
        raise RuntimeError(
            "jbig2 produced no stdout for "
            f"{otsu_tif}: {proc.stderr.decode('utf-8', errors='replace') if proc.stderr else ''}"
        )

    with Image.open(otsu_tif) as img:
        width, height = img.size

    pdf = pikepdf.Pdf.open(pdf_path)
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
        proc.stdout,
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
    return pdf

# OCR PDF生成、JBIG2差し替え、結合を順に実行する
def main() -> int:
    args = parse_args()
    if not args.input_dir.is_dir():
        raise FileNotFoundError(f"Input TIFF directory not found: {args.input_dir}")
    if args.workdir is None:
        args.workdir = args.input_dir.parent

    tifs = sorted(args.input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {args.input_dir}")

    for path in (args.output.parent, args.workdir):
        path.mkdir(parents=True, exist_ok=True)

    yomi_pdfs = [args.workdir / f"{args.input_dir.name}_{tif.stem}_p1.pdf" for tif in tifs]
    if all(pdf.exists() for pdf in yomi_pdfs):
        print("Reusing existing YomiToku PDFs", flush=True)
    else:
        subprocess.run(
            [
                "yomitoku", str(args.input_dir),
                "-f", "pdf",
                "--pdf_quality", "high",
                "--outdir", str(args.workdir),
            ],
            check=True,
        )

    final = pikepdf.Pdf.new()
    with tempfile.TemporaryDirectory(prefix="otsu_tif_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        for index, (tif, yomi_pdf) in enumerate(zip(tifs, yomi_pdfs), start=1):
            if not yomi_pdf.exists():
                raise FileNotFoundError(f"YomiToku PDF was not created: {yomi_pdf}")

            otsu_tif = tmp_dir_path / tif.name
            make_otsu_tif(tif, otsu_tif, half=args.half)
            with replace_background_with_jbig2(yomi_pdf, tif, otsu_tif) as page_pdf:
                final.pages.append(page_pdf.pages[0])

    tmp_pdf = args.output.with_name(f"{args.output.stem}.tmp{args.output.suffix}")
    if tmp_pdf.exists(): tmp_pdf.unlink()

    final.remove_unreferenced_resources()
    final.save(
        tmp_pdf,
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        deterministic_id=True,
    )
    if args.output.exists(): args.output.unlink()
    tmp_pdf.replace(args.output)
    print(f"Output PDF: {args.output}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
