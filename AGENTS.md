# スキャンOCRワークフロー メモ

このディレクトリでは、日本語書籍スキャン画像から、YomiToku のOCR位置精度を保ったまま、サイズの小さい検索可能PDFを作るための実験を行った。

## 環境管理（uv へ移行済み・2026-06-06）

pip による場当たり導入をやめ、全体を **uv** で管理する構成に作り直した。

- **パッケージ管理は uv に統一**（`winget install astral-sh.uv` で導入、現行 0.11.x）。
  - Python は **3.11 に統一**（`uv python install 3.11`）。旧来の「yomitoku=3.11 / ocrmypdf=3.13」併存はやめた。
  - Python 3.13 本体は他用途のため残してあるが、scan ワークフローでは使わない。
- **scan 直下が単一の uv プロジェクト**（`pyproject.toml` + `uv.lock`）。
  - 依存: `yomitoku==0.13.0`, `torch==2.8.0`, `torchvision==0.23.0`, `pikepdf`, `pillow`, `opencv-python`, `numpy`, `pdfminer.six`, `img2pdf`。
  - yomitoku と各スクリプトのライブラリは依存衝突しない（`pypdfium2==4.30.0` で共存可）。衝突するのは ocrmypdf だけなので別管理にした。
  - `.venv` は `uv sync` で生成。スクリプトは `uv run jbig2_half_pdf.py ...` で実行する。
- **GPU(CUDA) torch の固定**: yomitoku は公開メタデータに CUDA 版 torch の索引を持たないため、`pyproject.toml` で torch/torchvision を cu126 wheel 索引に固定している。
  ```toml
  [[tool.uv.index]]
  name = "pytorch-cu126"
  url = "https://download.pytorch.org/whl/cu126"
  explicit = true
  [tool.uv.sources]
  torch = { index = "pytorch-cu126" }
  torchvision = { index = "pytorch-cu126" }
  ```
  - `uv tool install` や `uv run` では `--torch-backend` が使えない（`uv pip` 専用）ため、この `[tool.uv.sources]` 方式で固定するのが確実。
  - 確認: `uv run python -c "import torch; print(torch.cuda.is_available())"` → `True`（RTX 4070 Ti、ドライバ591.86）。
  - CUDA Toolkit / `nvcc` は不要。cu126 の torch wheel が CUDA ランタイムを同梱しており、システム依存は NVIDIA ドライバのみ。
- **ocrmypdf は別 venv に隔離**: `uv tool install ocrmypdf --python 3.11`。
  - yomitoku の `pypdfium2==4.30.0` と ocrmypdf の新しい pypdfium2 が衝突するため、同居させず uv tool の独立 venv に分離。
  - シムは `%USERPROFILE%\.local\bin\ocrmypdf.exe`（`uv tool update-shell` で PATH 追加済み）。
  - Ghostscript・Tesseract・jbig2 は実行時に PATH から解決（現状維持）。
- **スクリプトの外部ツール解決を修正**: `jbig2_pdf.py` / `jbig2_half_pdf.py` のハードコードパスを廃止。
  - yomitoku: 環境変数 `YOMITOKU_EXE` 優先、無ければ `shutil.which("yomitoku")`（`uv run` 時に `.venv\Scripts` を解決）。
  - jbig2: 環境変数 `JBIG2_EXE` 優先、無ければ `shutil.which("jbig2")`（PATH から解決）。個人環境固有のパスは持たない。
- **旧 pip 導入分は削除済み**: Python 3.11 / 3.13 の user-site パッケージ（yomitoku・ocrmypdf・torch 等）をアンインストール。両環境とも `pip freeze --user` は空、`pip check` は `No broken requirements found`。
  - ロールバック用バックアップ: `backup_py311_freeze.txt`, `backup_py313_freeze.txt`。
- **uv 移行後の動作検証**（書籍1冊・90ページ）:
  - OCRテキスト層 90/90、JBIG2背景 90/90、YomiToku元 143.681 MB → 最終 5.651 MB（3.9%）。GPU 動作・圧縮率とも従来同等。

### 旧構成（履歴・参考）

> 以下は uv 移行前の pip ベースの手順。現在は上記 uv 構成を使う。

- Python 3.11 user site の `yomitoku` を更新した。
  - `yomitoku 0.9.5 -> 0.13.0`
  - まず `--no-deps` で入れて、GPU版PyTorchを崩さないようにした。
  - PyTorch は CUDA 版のまま残っていることを確認した。
    - `torch 2.8.0+cu126`
    - `torch.cuda.is_available() == True`
- Tesseract OCR を winget でインストールした。
  - パッケージ: `UB-Mannheim.TesseractOCR`
  - インストール先: `C:\Program Files\Tesseract-OCR\tesseract.exe`
  - 確認したバージョン: `5.4.0.20240606`
  - ユーザーPATHに `C:\Program Files\Tesseract-OCR` を追加した。
  - 利用可能言語は `eng`, `osd` のみだった。今回の用途ではYomiTokuがOCR済みなので問題なし。
- OCRmyPDF は Python 3.13 側に入れた。
  - コマンド: `py -3.13 -m pip install --user --upgrade ocrmypdf`
  - 確認したバージョン: `OCRmyPDF 17.5.0`
  - 理由: OCRmyPDF は新しい `pypdfium2` を要求する一方、YomiToku 0.13.0 は `pypdfium2==4.30.0` 固定。Python 3.11 側に同居させると依存衝突するため、OCRmyPDF は 3.13 側に分離した。
- 一度 OCRmyPDF を Python 3.11 側へ入れてしまったため、YomiToku 環境を修復した。
  - 実行した修復コマンド:
    - `python -m pip install --user --upgrade "pypdfium2==4.30.0" "networkx>=3.4.2" "onnxscript>=0.5.4"`
  - 修復後、`python -m pip check` は `No broken requirements found` になった。
- Windowsネイティブの jbig2enc を使えるようにした。
  - 任意のフォルダ（例: `C:\Tools\jbig2enc`）に配置した。
  - そのフォルダをユーザーPATHに追加した。
  - `jbig2.exe` は32bit実行ファイルで、32bit版 `MSVCR120.dll` が必要だった。
  - Visual C++ 2013 Redistributable x86 を winget で強制再インストールしたが、`C:\Windows\SysWOW64\MSVCR120.dll` は見つからなかった。
  - 32bit版DLLを以下で確認した。
    - `C:\Program Files\Microsoft Office\root\vfs\ProgramFilesX86\Microsoft Office\Office16\msvcr120.dll`
  - そのDLLを jbig2enc フォルダ（`jbig2.exe` と同じ場所）へコピーし、単体で起動できるようにした。
  - 確認結果:
    - `jbig2 --version` -> `jbig2enc 0.29`
    - `py -3.13 -c "from ocrmypdf._exec import jbig2enc; print(jbig2enc.available(), jbig2enc.version())"` -> `True 0.29`
- Ghostscript は既にインストール済みだった。
  - 実行ファイル: `gswin64c.exe`
  - 確認したバージョン: `10.6.0.0`

## 重要な調査結果

- YomiToku の `-f pdf --pdf_quality high` はOCRテキストの位置精度が非常に良い。
- 一方で、YomiToku の `--pdf_quality middle` や `low` はOCRテキスト位置が壊れることがある。PDF生成時は `high` 固定にして、後段でサイズ削減する方針がよい。
- YomiToku の検索可能PDFは、背景ページ画像を 8bit RGB JPEG として埋め込む。そのため、白黒本文だけのページでもPDFサイズが大きくなる。
- ある参考PDF（サイズが小さかった既存PDF）が小さい理由は、背景画像が 1bit 白黒かつ JBIG2 圧縮だったため。
- OCRmyPDF や Ghostscript の一般的な最適化コマンドだけでは、YomiToku のRGB JPEG背景を、OCR座標を保ったまま 1bit JBIG2/CCITT に直接変換するのは難しかった。
- 成功した方法は、YomiToku PDF全体を作り直すのではなく、透明OCRテキスト層を残したまま、背景画像XObjectだけを対応TIFF由来の1bit画像に差し替える方法。

## 成功した圧縮方針

YomiToku PDFと対応するTIFFのペアごとに以下を行う。

1. `pikepdf` で YomiToku PDF を開く。
2. ページ内の単一の背景画像XObjectを探す。
3. 対応するTIFFから1bit画像を作る。
4. 画像XObjectのストリームと画像辞書だけを差し替える。
5. ページの MediaBox、コンテンツストリーム、透明OCRテキスト層は触らない。

PDFのページ座標系とOCRテキスト層を作り直さないため、OCR座標がズレにくい。

## CCITT G4版

- `img2pdf` で 1bit TIFF を PDF-ready な CCITT Group 4 画像ストリームに変換した。
- 画像XObjectは以下の形にした。
  - `/Filter /CCITTFaxDecode`
  - `/BitsPerComponent 1`
  - `/ColorSpace /DeviceGray`
  - `/DecodeParms` に `/K -1`, `/Columns`, `/Rows`, 正しい `/BlackIs1` を設定
- 元解像度の出力先:
  - `src\bw_ccitt`
- 半分解像度の出力先:
  - `src\bw_ccitt_half`

## JBIG2版

- Windowsネイティブの `jbig2.exe` (`jbig2enc 0.29`) を使用した。
- PDF-ready なJBIG2ストリームを作るコマンド形:
  - `jbig2 --pdf input.tif`
- `jbig2 --pdf` の出力は完全なPDFではなく、画像XObjectに埋め込むためのJBIG2ストリーム。
- 画像XObjectは以下の形にした。
  - `/Filter /JBIG2Decode`
  - `/BitsPerComponent 1`
  - `/ColorSpace /DeviceGray`
- 元解像度の出力先:
  - `src\jbig2_full`
- 半分解像度の出力先:
  - `src\jbig2_half`

## サイズ比較（ある書籍の連続7ページ）

元のYomiToku PDF:

- 場所: `src`
- 対象: ある書籍の連続する7ページ分の単ページPDF
- 合計: `16.798 MB`
- 平均: `2457.3 KB/page`

| 解像度 | 圧縮 | 出力先 | 合計 | 平均/page | 元YomiToku比 |
|---|---|---|---:|---:|---:|
| 元解像度 | CCITT G4 | `src\bw_ccitt` | `0.953 MB` | `139.4 KB` | `5.7%` |
| 半分 | CCITT G4 | `src\bw_ccitt_half` | `0.686 MB` | `100.3 KB` | `4.1%` |
| 元解像度 | JBIG2 | `src\jbig2_full` | `0.784 MB` | `114.7 KB` | `4.7%` |
| 半分 | JBIG2 | `src\jbig2_half` | `0.581 MB` | `85.1 KB` | `3.5%` |

相対比較:

- 半分CCITTは、元解像度CCITTの `72.0%`。
- 元解像度JBIG2は、元解像度CCITTの `82.3%`。
- 半分JBIG2は、半分CCITTの `84.8%`。
- 半分JBIG2は、元解像度CCITTの `61.0%`。

`jbig2_full` と `jbig2_half` の全PDFについて、`pdfminer` でOCRテキスト層が残っていることを確認した。

## 実用上のおすすめ

- YomiTokuで検索可能PDFを作るときは `--pdf_quality high` を使う。
- 書籍本文のような白黒テキスト中心のスキャンでは、後処理で背景画像XObjectだけを1bit画像に差し替える。
- これまでの最小サイズは、半分解像度JBIG2版 (`src\jbig2_half`)。
- より単純で安全寄りの代替は、半分解像度CCITT G4版 (`src\bw_ccitt_half`)。
- 最終確認が終わるまでは、YomiTokuが作った元PDFを残しておく。OCRテキスト層の元データとして必要。

## 注意点

- OCR位置を重視する場合、YomiToku の `middle` / `low` は使わない。座標が壊れることがある。
- 複数のTIFFを結合してからYomiTokuにかけるより、1ページずつYomiToku PDFを作り、必要なら後でPDF結合する方が安定した。
- YomiToku の `--combine` は、1つの入力ファイル内の複数ページを結合するもの。ディレクトリ内の複数TIFFを横断して1つにまとめるものではない。
- 半分解像度CCITT画像を作るとき、`/BlackIs1` を固定値にすると白黒反転することがあった。`img2pdf` が生成した画像の `BlackIs1` を確認して反映すること。
- JBIG2のlossy symbol substitutionは文字化け・文字置換リスクがある。今回のテストでは `jbig2 --pdf` のみを使い、symbol-modeやlossyオプションは使っていない。
- `pngquant` は今回の成功ルートでは不要。OCRmyPDFのPNG最適化用であり、TIFF由来のCCITT/JBIG2背景差し替えには関係ない。

## 定型化スクリプト `jbig2_half_pdf.py`

YomiToku PDF生成、半分解像度JBIG2背景差し替え、PDF結合をまとめた定型スクリプトを作成した。

- 場所:
  - `jbig2_half_pdf.py`（プロジェクト直下）
- 基本実行例（uv 経由）:
  - `uv run jbig2_half_pdf.py "10_Scan\<本のフォルダ>\out"`
  - scan ディレクトリで実行する。`uv run` が `.venv`（yomitoku/torch/各ライブラリ）を自動で使う。
- `--output-name` を省略した場合:
  - 入力フォルダの親フォルダ名をPDF名にする。
  - 例: 入力 `10_Scan\<本のフォルダ>\out`
  - 出力PDF名: `<本のフォルダ>.pdf`
  - 出力先: `10_Scan\<本のフォルダ>\<本のフォルダ>`
- `--out-dir` を指定すると出力先を変更できる。
- `--out-dir` が `input_dir` 配下の場合は、YomiTokuの再帰処理に巻き込まれるためエラーにする。

処理の流れ:

1. `input_dir/cache` があれば削除する。
2. `input_dir` 直下の `*.tif` だけを名前昇順で対象にする。
3. YomiTokuをフォルダ指定で1回だけ起動する。
   - `yomitoku.exe input_dir -f pdf --pdf_quality high -o out_dir\yomitoku_pdf`
   - 1ページずつ `yomitoku.exe` を起動しない。モデル初期化を1回にするため。
4. YomiTokuの既定出力名に依存して、単ページPDFを対応づける。
   - 期待名: `<input_dir.name>_<tif.stem>_p1.pdf`
   - `out` フォルダなら `out_scan229_1R_p1.pdf` のようになる。
5. PDFが生成され、サイズが安定し、`pikepdf` で開けたものから順次処理する。
6. 対応TIFFをPillowでグレースケール化し、半分解像度へ縮小する。
7. OpenCVのOtsu二値化で1bit TIFFへ戻す。
8. `jbig2 --pdf half.tif` でJBIG2ストリームを作る。
9. `pikepdf` でYomiToku PDF内の単一背景画像XObjectをJBIG2画像へ差し替える。
10. 単ページPDFを名前昇順で結合する。
11. ページ数、OCRテキスト層、JBIG2背景、サイズを検証する。

## `jbig2_pdf.py` の汎用化とシェルラッパー分離（2026-06-06）

`jbig2_pdf.py` に混在していた「私のディレクトリ構成依存の処理」と「普遍的な処理」を分離した。

- `jbig2_pdf.py` は**汎用ツール**にした。単独でも呼べる。
  - 引数は `tiff_dir`（`*.tif` が直接入ったフォルダ）、`--out-dir`（中間+最終PDFの出力先、省略時は `tiff_dir` の親）、`--output-name`（省略時 `output.pdf`、basename のみ）。
  - `/out` を付ける・`/cache` を消す・出力名をフォルダ名にする・出力先を決める、といった構成依存は**持たない**。
  - 実行例: `uv run jbig2_pdf.py "<TIFFフォルダ>" --out-dir "<出力先>" --output-name "本.pdf"`
- 構成依存の処理は**薄いラッパー `run_jbig2.ps1`** に切り出した（PowerShell で実行）。
  - `<本のフォルダ>\out` を TIFF フォルダとして `jbig2_pdf.py` に渡す。
  - `<本のフォルダ>\out\cache` があれば消す。
  - 出力名を `<本のフォルダ名>.pdf`、出力先を `<本のフォルダ>\yomitoku` にする。
  - 結果として最終PDFは従来どおり `<本のフォルダ>\yomitoku\<本のフォルダ名>.pdf` に出る。
  - 実行例: `.\run_jbig2.ps1 "10_Scan\250620_Seminaire 1-1"`
  - PowerShell にしたのは、`uv` が git bash の PATH に乗らず（winget 配置のため）`.sh` から呼べなかったため。
  - 日本語コメント入りの `.ps1` は **UTF-8 BOM 付き**で保存する。Windows PowerShell 5.1 は BOM なしを Shift-JIS と誤認してパースエラーになる。

## 定型化で分かった注意点

- `jbig2_half_pdf.py` は既存の半分TIFFを再利用するが、JBIG2差し替え済み単ページPDFは毎回再生成する。
  - ページサイズ補正のようなロジック変更を反映するため。
- YomiTokuのPDFは、ページMediaBoxが画像ピクセル数のままになる。
  - 例: 600dpiの `3340 x 4432` ピクセルが `3340pt x 4432pt` と扱われ、実寸が約 `1178mm x 1564mm` の巨大ページになる。
  - そのままではA5程度の本でもPDFページサイズが壊れる。
- 定型スクリプトでは、元TIFFのDPIを読み、ページ内容全体を `72 / DPI` で縮小してから、MediaBox/CropBoxを実寸ポイントへ直す。
  - 例: `3340 x 4432` ピクセル、600dpiの場合は `400.8pt x 531.84pt`、約 `141.4mm x 187.6mm` になる。
  - 透明OCRテキスト層と背景画像を同じ変換で包むため、OCR位置関係は保たれる。
- 以前の「MediaBox、コンテンツストリームは触らない」という方針は、OCR座標保護には安全だったが、PDF物理サイズが壊れるため定型スクリプトでは採用しない。

## 実行・計測結果メモ

※ 具体的な書名は伏せ、結果のみ記録する。

書籍A:

- 対象: 26 TIFF
- OCRテキスト層: 26/26
- JBIG2背景: 26/26
- YomiToku元PDF合計: `37.266 MB`
- 最終PDF: `1.448 MB`
- 圧縮率: `3.9%`

書籍B:

- 対象: 11 TIFF
- OCRテキスト層: 11/11
- JBIG2背景: 11/11
- YomiToku元PDF合計: `25.792 MB`
- 最終PDF: `0.942 MB`
- 圧縮率: `3.7%`
- YomiToku一括起動中に、生成済みPDFから順次後段処理できることを確認した。

書籍C:

- 対象: 43 TIFF
- OCRテキスト層: 43/43
- JBIG2背景: 43/43
- YomiToku元PDF合計: `85.359 MB`
- 最終PDF: `3.164 MB` からページサイズ補正後 `3.166 MB`
- 圧縮率: `3.7%`

