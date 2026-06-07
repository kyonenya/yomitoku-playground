import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pikepdf
from PIL import Image


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
        "--half",
        action="store_true",
        help="Downscale each page to half resolution before binarization (smaller PDF).",
    )
    return parser.parse_args()


# 単ページTIFF群を1本のマルチページTIFFへ束ねる
def build_combined_tiff(tifs: list[Path], dest_dir: Path) -> Path:
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


# 結合TIFFを --combine でOCRする
def run_yomitoku_combine(combined_tif: Path, dest_dir: Path) -> Path:
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
    # 出力名はtempの親フォルダ名依存なので、生成された唯一のPDFをglobで拾う
    produced = sorted(dest_dir.glob("*.pdf"))
    if len(produced) != 1:
        raise RuntimeError(
            f"Expected exactly one YomiToku PDF in {dest_dir}, found {len(produced)}"
        )
    return produced[0]


# TIFFを大津二値化した1bit TIFFにする
def make_otsu_tif(src: Path, dest_dir: Path, *, half: bool = False) -> Path:
    dest = dest_dir / src.name
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

    _, bw_img = cv2.threshold(
        np.array(gray), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    if dest.exists():
        dest.unlink()
    Image.fromarray(bw_img).convert("1").save(dest, compression="group4", dpi=dpi)
    return dest


# TIFFのDPIに合わせてページ内容とページサイズを補正する
def set_physical_page_size(pdf: pikepdf.Pdf, page: pikepdf.Page, src_tif: Path) -> None:
    def dpi_scale(src: Path) -> tuple[float, float]:
        with Image.open(src) as img:
            dpi = cast(tuple[float, float], img.info.get("dpi"))
        x_dpi, y_dpi = dpi
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


# 1bit TIFFを jbig2.exe でPDF埋め込み用のJBIG2ストリーム（bytes）にする
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


# ページ内の唯一の背景画像XObjectを、JBIG2ストリームの画像へ差し替える（OCR層は残す）
def set_page_jbig2_background(
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
            f"Expected exactly one image XObject on the page for {otsu_tif.name}, "
            f"found {len(image_entries)}"
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


# 入力TIFFを確認し、YomiTokuで結合PDFを作り、背景をJBIG2へ差し替えて保存する
def main() -> int:
    args = parse_args()

    # 入力TIFFを確認する
    if not args.input_dir.is_dir():
        raise FileNotFoundError(f"Input TIFF directory not found: {args.input_dir}")
    tifs = sorted(args.input_dir.glob("*.tif"), key=lambda p: p.name)
    if not tifs:
        raise RuntimeError(f"No TIFF files found in {args.input_dir}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # YomiToku用の結合PDFを用意する（既存ならOCRをスキップして再利用）
    yomitoku_pdf = args.output.with_name(f"{args.output.stem}.yomitoku.pdf")
    if yomitoku_pdf.exists():
        print("Reusing existing YomiToku PDF", flush=True)
    else:
        with tempfile.TemporaryDirectory(prefix="yomitoku_combine_") as tmp_dir:
            # 単ページTIFF群を1本のマルチページTIFFへ束ね、--combine で1本のPDFを作る
            work_dir = Path(tmp_dir)
            combined_tif = build_combined_tiff(tifs, work_dir)
            produced = run_yomitoku_combine(combined_tif, work_dir)
            shutil.move(str(produced), str(yomitoku_pdf))

    # 各ページの背景画像をJBIG2へ差し替える
    with pikepdf.Pdf.open(yomitoku_pdf) as pdf:
        if len(pdf.pages) != len(tifs):
            raise RuntimeError(
                f"YomiToku PDF page count ({len(pdf.pages)}) does not match "
                f"the number of source TIFFs ({len(tifs)})"
            )

        with tempfile.TemporaryDirectory(prefix="otsu_tif_") as tmp_dir:
            tmp_dir_path = Path(tmp_dir)
            for tif, page in zip(tifs, pdf.pages):
                otsu_tif = make_otsu_tif(tif, tmp_dir_path, half=args.half)
                jbig2 = jbig2_encode(otsu_tif)
                set_page_jbig2_background(pdf, page, jbig2, otsu_tif)
                set_physical_page_size(pdf, page, tif)

        # 最終PDFとして保存する
        tmp_pdf = args.output.with_name(f"{args.output.stem}.tmp{args.output.suffix}")
        if tmp_pdf.exists():
            tmp_pdf.unlink()
        pdf.remove_unreferenced_resources()
        pdf.save(
            tmp_pdf,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            deterministic_id=True,
        )
    if args.output.exists():
        args.output.unlink()
    tmp_pdf.replace(args.output)
    print(f"Output PDF: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
