# yomitoku-playground

日本語書籍のスキャン画像（TIFF）から、**YomiToku の OCR 位置精度を保ったまま、サイズの小さい検索可能 PDF** を作るためのワークフロー。

YomiToku で検索可能 PDF を生成し、背景のページ画像を **1bit JBIG2** に差し替えることで、OCR テキスト層を維持したまま大幅にサイズを削減する（実測で元の約 4% 前後）。

対象環境: **Windows + NVIDIA GPU**（CUDA）。Python 環境は [uv](https://docs.astral.sh/uv/) で管理する。

---

## 必要なもの

| 区分 | ツール | 備考 |
|---|---|---|
| パッケージ管理 | **uv** 0.11+ | Python と依存をすべて管理 |
| GPU | **NVIDIA ドライバ** | GeForce 等。CUDA Toolkit / nvcc は**不要**（torch の cu126 wheel がランタイムを同梱） |
| ネイティブ | **jbig2enc**（`jbig2.exe`, 0.29） | uv 管理外。手動で導入し PATH に通す |

Python パッケージ（yomitoku, torch+cu126, pikepdf, pillow, opencv-python, numpy, pdfminer.six, img2pdf）は **`uv sync` が `uv.lock` から自動導入**するので個別インストールは不要。

---

## セットアップ手順（Windows + NVIDIA）

### 1. NVIDIA ドライバ
GeForce/Quadro の最新ドライバが入っていれば OK。確認:
```powershell
nvidia-smi
```
GPU 名とドライバ版が表示されればよい（例: RTX 4070 Ti / 591.86）。**CUDA Toolkit のインストールは不要**。

### 2. uv をインストール
```powershell
winget install --id=astral-sh.uv -e
```
インストール後はシェルを開き直す（PATH 反映のため）。確認:
```powershell
uv --version
```

### 3. リポジトリを取得して Python 環境を構築
```powershell
git clone <このリポジトリのURL> yomitoku-playground
cd yomitoku-playground
uv sync
```
- `uv sync` が Python 3.11 を用意し、`uv.lock` どおりに yomitoku・torch(cu126)・各ライブラリを `.venv` に導入する。
- 初回は torch(cu126) が約 2.7GB あるためダウンロードに時間がかかる。
- GPU が効いているか確認:
  ```powershell
  uv run python -c "import torch; print(torch.cuda.is_available())"
  # -> True なら GPU 利用可
  ```

### 4. jbig2enc（jbig2.exe）を導入して PATH に通す
JBIG2 圧縮に必須のネイティブツール。uv では管理しない。

1. Windows 向けの `jbig2enc`（`jbig2.exe`）を入手し、任意のフォルダに置く（例: `C:\Tools\jbig2enc`）。
2. そのフォルダを**ユーザー PATH に追加**する。
3. 動作確認:
   ```powershell
   jbig2 --version
   # -> jbig2enc 0.29
   ```

> **トラブル: `jbig2.exe` が起動しない場合**
> `jbig2.exe`（0.29）は 32bit 実行ファイルで、32bit 版 `MSVCR120.dll`（Visual C++ 2013 ランタイム x86）を要求する。
> - `winget install Microsoft.VCRedist.2013.x86` を試す。
> - それでも `MSVCR120.dll` が見つからない場合は、32bit 版 `msvcr120.dll` を `jbig2.exe` と同じフォルダに置くと単体起動できる。

スクリプトは `jbig2` を **PATH から自動解決**する（環境変数 `JBIG2_EXE` に実行ファイルのパスを設定して上書きも可能）。

---

## 使い方

入力は **1ページ1枚の TIFF を集めたフォルダ**（このリポジトリの慣習では `out` フォルダ）。
プロジェクトのルートで `uv run` から実行する。
**2つのスクリプトで引数の渡し方が異なる**ので注意。

### 半分解像度 JBIG2 版（推奨・最小サイズ）
引数は **`out` フォルダそのもの**を渡す。
```powershell
uv run jbig2_half_pdf.py "10_Scan\<本のフォルダ>\out"
```
オプション:
- `--output-name <名前.pdf>`: 最終 PDF 名。省略時は**入力フォルダの親フォルダ名**。
- `--out-dir <出力先>`: 出力先。省略時は `入力フォルダの親 / 出力名のstem`。
  - 注意: `--out-dir` を入力フォルダの配下にすると YomiToku の再帰処理に巻き込まれるためエラーになる。

### 元解像度 JBIG2 版

`jbig2_pdf.py`（汎用ツール）と `run_jbig2.ps1`（このリポジトリの構成専用ラッパー）に分かれている。

**推奨: ラッパー経由**（本のフォルダを渡すだけ）
```powershell
.\run_jbig2.ps1 "10_Scan\<本のフォルダ>"
```
- `<本のフォルダ>\out` を入力 TIFF として処理する。
- `<本のフォルダ>\out\cache` があれば消す。
- 出力名は `<本のフォルダ名>.pdf`、出力先は `<本のフォルダ>\yomitoku\`。
- 最終 PDF は `<本のフォルダ>\yomitoku\<本のフォルダ名>.pdf` に出る。

**汎用ツールを直接呼ぶ場合**（任意の TIFF フォルダ）
```powershell
uv run jbig2_pdf.py "<TIFFフォルダ>"
```
引数・オプション:
- 第1引数: `*.tif` が直接入ったフォルダ。
- `--out-dir <出力先>`: 中間ファイルと最終 PDF の出力先。省略時は **TIFF フォルダの親**。
- `--output-name <名前.pdf>`: 最終 PDF 名（basename のみ）。省略時は `output.pdf`。

### 処理の流れ（`jbig2_half_pdf.py`）
1. 入力フォルダの `*.tif` を名前昇順で対象にする。
2. YomiToku を一括起動して各ページの検索可能 PDF を生成（`-f pdf --pdf_quality high`）。
3. 生成された PDF から順次、対応 TIFF を半分解像度・Otsu 二値化した 1bit TIFF にする。
4. `jbig2 --pdf` で JBIG2 ストリームを作り、PDF 内の背景画像 XObject だけを差し替える（OCR テキスト層は保持）。
5. 全ページを結合し、ページ数・OCR テキスト層・JBIG2 背景・サイズを検証する。

---

## 仕組みのポイント / 注意

- **GPU torch の固定**: YomiToku は公開メタデータに CUDA 版 torch の索引を持たないため、`pyproject.toml` で torch/torchvision を cu126 wheel 索引（`[[tool.uv.index]]` + `[tool.uv.sources]`）に固定している。`uv tool install` / `uv run` では `--torch-backend` が使えない（`uv pip` 専用）ため、この方式が確実。
- **PDF 品質**: YomiToku は `--pdf_quality high` を使う。`middle` / `low` は OCR テキストの位置がずれることがある。
- **入力データはリポジトリに含めない**: `*.tif` `*.pdf` `10_Scan` は `.gitignore` 済み。スクリプトと設定（`pyproject.toml` / `uv.lock`）だけが版管理対象。
- **別 PC への移植**: 同じ Windows + NVIDIA 環境なら `git clone` → `uv sync` → `jbig2enc` を PATH に通す、でそのまま動く。GPU が無い PC では cu126 torch は CPU 動作になり非常に遅い。

詳細な実験ログや調査結果は [AGENTS.md](AGENTS.md) を参照。
