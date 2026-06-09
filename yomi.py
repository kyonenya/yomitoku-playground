import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pikepdf
from PIL import Image


def parse_args() -> argparse.Namespace:
    def positive_int(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if parsed <= 0:
            raise argparse.ArgumentTypeError("must be positive")
        return parsed

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
        "--dpi",
        type=positive_int,
        default=None,
        help="Downscale background images to this DPI (never upscales). Defaults to source resolution.",
    )
    parser.add_argument(
        "--chunk",
        type=positive_int,
        default=None,
        help="Split pages into this many chunks to reduce YomiToku memory use. Defaults to one chunk.",
    )
    return parser.parse_args()


def combine_tiff(tifs: list[Path], output: Path) -> Path:
    dest = output.with_name(f"{output.stem}.combined.tif")
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


def build_yomitoku_pdf(combined_tif: Path, output: Path) -> Path:
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
            str(output.parent),
        ],
        check=True,
    )
    produced = output.parent / f"{combined_tif.parent.name}_{combined_tif.stem}.pdf"
    if not produced.is_file():
        raise FileNotFoundError(f"YomiToku PDF was not created: {produced}")
    dest = output.with_name(f"{output.stem}.yomitoku.pdf")
    produced.replace(dest)
    return dest


def split_into_chunks(
    tifs: list[Path],
    requested_chunk_count: int | None,
) -> list[tuple[int, int, list[Path]]]:
    chunk_count = min(requested_chunk_count or 1, len(tifs))
    base_size, extra_count = divmod(len(tifs), chunk_count)

    def boundary(i: int) -> int:
        return i * base_size + min(i, extra_count)

    chunk_ranges = [(boundary(i), boundary(i + 1)) for i in range(chunk_count)]
    return [(start + 1, end, tifs[start:end]) for start, end in chunk_ranges]


def safe_read_dpi(src: Path) -> tuple[float, float]:
    with Image.open(src) as img:
        dpi = img.info.get("dpi")
    if dpi is None:
        raise RuntimeError(f"TIFF DPI metadata is missing: {src}")
    x_dpi, y_dpi = dpi
    return float(x_dpi), float(y_dpi)


def make_otsu_tif(src: Path, dest_dir: Path, *, target_dpi: int | None = None) -> Path:
    dest = dest_dir / src.name
    x_dpi, y_dpi = safe_read_dpi(src)
    scale = 1.0 if target_dpi is None else min(1.0, target_dpi / x_dpi)
    with Image.open(src) as img:
        gray = img.convert("L")
        if scale < 1.0:
            width, height = gray.size
            gray = gray.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.Resampling.LANCZOS,
            )

    _, bw_img = cv2.threshold(
        np.array(gray), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    dest.unlink(missing_ok=True)
    Image.fromarray(bw_img).convert("1").save(
        dest, compression="group4", dpi=(x_dpi * scale, y_dpi * scale)
    )
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


def encode_jbig2(otsu_tif: Path) -> bytes:
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
            f"jbig2 produced no stdout for {otsu_tif}: {proc.stderr.decode('utf-8', errors='replace')}"
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


def save_pdf(pdf: pikepdf.Pdf, output: Path) -> None:
    tmp_pdf = output.with_name(f"{output.stem}.tmp{output.suffix}")
    pdf.save(
        tmp_pdf,
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        deterministic_id=True,
    )
    tmp_pdf.replace(output)


def main() -> int:
    args = parse_args()
    print("Starting...", flush=True)
    tifs = sorted(args.input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {args.input_dir}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    chunks = split_into_chunks(tifs, args.chunk)
    multi = len(chunks) > 1
    final_yomitoku_pdf = args.output.with_name(f"{args.output.stem}.yomitoku.pdf")

    if final_yomitoku_pdf.exists():
        print(f"reuse {final_yomitoku_pdf.name}", flush=True)
    else:
        # チャンクごとにYomiTokuでOCRし、検索可能PDFを作る
        yomitoku_pdfs: list[Path] = []
        for idx, (start, end, chunk) in enumerate(chunks, start=1):
            out = (
                args.output.with_name(
                    f"{args.output.stem}.{start}-{end}{args.output.suffix}"
                )
                if multi
                else args.output
            )
            combined_tif = out.with_name(f"{out.stem}.combined.tif")
            print(f"[{idx}/{len(chunks)}] OCR pages {start}-{end}", flush=True)
            if not combined_tif.exists():
                combined_tif = combine_tiff(chunk, out)
            yomitoku_pdf = build_yomitoku_pdf(combined_tif, out)
            combined_tif.unlink(missing_ok=True)
            yomitoku_pdfs.append(yomitoku_pdf)

        # 複数チャンクのOCR結果を1つのPDFにまとめる
        if multi:
            with pikepdf.Pdf.new() as merged:
                for yomitoku_pdf in yomitoku_pdfs:
                    with pikepdf.Pdf.open(yomitoku_pdf) as src:
                        merged.pages.extend(src.pages)
                save_pdf(merged, final_yomitoku_pdf)

            for yomitoku_pdf in yomitoku_pdfs:
                yomitoku_pdf.unlink(missing_ok=True)

    merged = pikepdf.Pdf.open(final_yomitoku_pdf)
    if len(merged.pages) != len(tifs):
        merged.close()
        raise RuntimeError(
            f"Page count mismatch: {len(merged.pages)} PDF pages vs {len(tifs)} TIFFs."
        )

    # 全ページの背景画像をJBIG2へ一括で差し替える
    print(f"Replacing backgrounds with JBIG2 ({len(tifs)} pages)", flush=True)
    with tempfile.TemporaryDirectory(prefix="otsu_tif_") as tmp_dir:
        for tif, page in zip(tifs, merged.pages):
            otsu_tif = make_otsu_tif(tif, Path(tmp_dir), target_dpi=args.dpi)
            replace_page_jbig2_background(
                merged, page, encode_jbig2(otsu_tif), otsu_tif
            )
            correct_physical_page_size(merged, page, tif)

    # 最終PDFとして保存する
    merged.remove_unreferenced_resources()
    save_pdf(merged, args.output)
    merged.close()

    print(f"Output PDF: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
