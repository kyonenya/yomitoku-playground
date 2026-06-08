import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pikepdf
from PIL import Image


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
        "--half",
        action="store_true",
        help="Downscale each page to half resolution before binarization (smaller PDF).",
    )
    return parser.parse_args()


def combine_tiff(tifs: list[Path], dest_dir: Path) -> Path:
    dest = dest_dir / "combined.tif"
    images = [Image.open(tif) for tif in tifs]
    try:
        first, rest = images[0], images[1:]
        first.save(
            dest,
            save_all=True,
            append_images=rest,
            compression="tiff_deflate",
        )
    finally:
        for img in images:
            img.close()
    return dest


def build_yomitoku_pdf(combined_tif: Path, dest_dir: Path) -> Path:
    subprocess.run(
        [
            "yomitoku",
            str(combined_tif),
            "-f",
            "pdf",
            "--pdf_quality",
            "high",
            "--combine",
            "--outdir",
            str(dest_dir),
        ],
        check=True,
    )
    expected_dest = dest_dir / f"{combined_tif.parent.name}_{combined_tif.stem}.pdf"
    if not expected_dest.is_file():
        raise FileNotFoundError(f"YomiToku PDF was not created: {expected_dest}")
    return expected_dest


def safe_read_dpi(src: Path) -> tuple[float, float]:
    with Image.open(src) as img:
        dpi = img.info.get("dpi")
    if dpi is None:
        raise RuntimeError(f"TIFF DPI metadata is missing: {src}")
    x_dpi, y_dpi = dpi
    return float(x_dpi), float(y_dpi)


def make_otsu_tif(src: Path, dest_dir: Path, *, half: bool = False) -> Path:
    dest = dest_dir / src.name
    dpi = safe_read_dpi(src)
    with Image.open(src) as img:
        gray = img.convert("L")
        if half:
            width, height = gray.size
            gray = gray.resize(
                (max(1, width // 2), max(1, height // 2)),
                Image.Resampling.LANCZOS,
            )

    # 大津の二値化
    _, bw_img = cv2.threshold(
        np.array(gray), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    if dest.exists():
        dest.unlink()
    Image.fromarray(bw_img).convert("1").save(dest, compression="group4", dpi=dpi)
    return dest


def correct_physical_page_size(
    pdf: pikepdf.Pdf, page: pikepdf.Page, src_tif: Path
) -> None:
    x_dpi, y_dpi = safe_read_dpi(src_tif)
    scale_x, scale_y = 72 / x_dpi, 72 / y_dpi

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

    page.Contents = pikepdf.Stream(
        pdf,
        (
            f"q\n{scale_x:.12g} 0 0 {scale_y:.12g} 0 0 cm\n".encode("ascii")
            + content_bytes
            + b"\nQ\n"
        ),
    )
    page.MediaBox = new_box
    page.CropBox = new_box


def jbig2_encode(otsu_tif: Path) -> bytes:
    JBIG2ENC_EXE = (
        Path(__file__).resolve().parent / "jbig2enc-0.31-Windows-X64-MSVC/bin/jbig2.exe"
    )
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
    return proc.stdout


def replace_page_jbig2_background(
    pdf: pikepdf.Pdf, page: pikepdf.Page, jbig2: bytes, otsu_tif: Path
) -> None:
    with Image.open(otsu_tif) as img:
        width, height = img.size

    xobjects = page.Resources.get("/XObject", {})
    image_entries = [
        (name, obj)
        for name, obj in xobjects.items()
        if obj.get("/Subtype", None) == pikepdf.Name("/Image")
    ]
    if len(image_entries) != 1:
        raise RuntimeError(
            f"Expected 1 image XObject on {otsu_tif.name}, found {len(image_entries)}"
        )

    image_name, _ = image_entries[0]
    xobjects[image_name] = pikepdf.Stream(
        pdf,
        jbig2,
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


def main() -> int:
    args = parse_args()
    tifs = sorted(args.input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {args.input_dir}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # YomiTokuで検索可能PDFを生成する
    yomitoku_pdf = args.output.with_name(f"{args.output.stem}.yomitoku.pdf")
    if yomitoku_pdf.exists():
        print("Reusing existing YomiToku PDF", flush=True)
    else:
        with tempfile.TemporaryDirectory(prefix="yomitoku_combine_") as tmp_dir:
            combined_tif = combine_tiff(tifs, Path(tmp_dir))
            produced_pdf = build_yomitoku_pdf(combined_tif, Path(tmp_dir))
            shutil.move(str(produced_pdf), str(yomitoku_pdf))

    # 各ページの背景画像をJBIG2へ差し替える
    with pikepdf.Pdf.open(yomitoku_pdf) as pdf:
        if len(pdf.pages) != len(tifs):
            raise RuntimeError(
                f"Page count mismatch: {len(pdf.pages)} PDF pages vs {len(tifs)} TIFFs"
            )

        with tempfile.TemporaryDirectory(prefix="otsu_tif_") as tmp_dir:
            for tif, page in zip(tifs, pdf.pages):
                otsu_tif = make_otsu_tif(tif, Path(tmp_dir), half=args.half)
                jbig2 = jbig2_encode(otsu_tif)
                replace_page_jbig2_background(pdf, page, jbig2, otsu_tif)
                correct_physical_page_size(pdf, page, tif)

        # 最終PDFとして保存する（atomic save）
        tmp_pdf = args.output.with_name(f"{args.output.stem}.tmp{args.output.suffix}")
        pdf.remove_unreferenced_resources()
        pdf.save(
            tmp_pdf,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            deterministic_id=True,
        )
    tmp_pdf.replace(args.output)
    print(f"Output PDF: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
