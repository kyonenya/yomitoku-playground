# yomitoku-slimpdf

日本語書籍のスキャン画像（TIFF）から、YomiToku の OCR 位置精度を保ったまま、サイズの小さい検索可能 PDF を作るためのワークフロー。

YomiToku で検索可能 PDF を生成し、背景のページ画像を 1bit JBIG2 に差し替えることで、OCR テキスト層を維持したまま大幅にサイズを削減する（実測で元の約 4% 前後）。

推奨環境: Windows + NVIDIA GPU（CUDA）。Python 環境は [uv](https://docs.astral.sh/uv/) で管理する。

---

## 必要なもの

| 区分 | ツール | 備考 |
|---|---|---|
| パッケージ管理 | uv 0.11+ | Python と依存をすべて管理 |
| GPU | NVIDIA ドライバ | GeForce 等 |
| ネイティブ | jbig2enc（`jbig2.exe`, 0.31 x64） | uv 管理外。GitHub Release をルート直下へ展開する |

Python パッケージは `uv sync` が `uv.lock` から自動導入するので個別インストールは不要。

---

## セットアップ手順（Windows + NVIDIA）

### 1. NVIDIA ドライバ
GeForce/Quadro の最新ドライバが入っていれば OK。確認:
```powershell
nvidia-smi
```
GPU 名とドライバ版が表示されればよい（例: RTX 4070 Ti / 591.86）。

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
git clone <このリポジトリのURL> yomitoku-slimpdf
cd yomitoku-slimpdf
uv sync
```
- `uv sync` が Python 3.11 を用意し、`uv.lock` どおりに yomitoku・torch(cu126)・各ライブラリを `.venv` に導入する。
- 初回は torch(cu126) が約 2.7GB あるためダウンロードに時間がかかる。
- GPU が効いているか確認:
  ```powershell
  uv run python -c "import torch; print(torch.cuda.is_available())"
  # -> True なら GPU 利用可
  ```

### 4. jbig2enc（jbig2.exe）0.31 x64 をルート直下へ展開
JBIG2 圧縮に必須のネイティブツール。uv では管理せず、GitHub Release の x64 版をプロジェクトルート直下に展開する。展開したフォルダと ZIP は `.gitignore` 対象なので、リポジトリには含めない。

プロジェクトルートで実行:
```powershell
Invoke-WebRequest `
    -Uri "https://github.com/agl/jbig2enc/releases/download/0.31/jbig2enc-0.31-Windows-X64-MSVC.zip" `
    -OutFile "jbig2enc-0.31-Windows-X64-MSVC.zip"
Expand-Archive `
    -Path "jbig2enc-0.31-Windows-X64-MSVC.zip" `
    -DestinationPath "jbig2enc-0.31-Windows-X64-MSVC" `
    -Force
Remove-Item "jbig2enc-0.31-Windows-X64-MSVC.zip"

.\jbig2enc-0.31-Windows-X64-MSVC\bin\jbig2.exe --version
# -> jbig2enc 0.31
```

---

## 使い方

入力は 1ページ1枚の TIFF を集めたフォルダ。
処理は `yomitoku.py` が担う。プロジェクトのルートで `uv run` から実行する。
`--half` を付けると半分解像度化して PDF をさらに小さくできる（既定は元解像度）。

```powershell
uv run yomitoku.py "<入力フォルダ>" [--output "<出力PDFパス>"] [--workdir "<作業ディレクトリ>"] [--half]
uv run yomitoku.py "<入力フォルダ>" -o "<出力PDFパス>" -w "<作業ディレクトリ>" [--half]
```

引数・オプション:
- 第1引数: `*.tif` が直接入ったフォルダ。
- `--output <PDFパス>` / `-o <PDFパス>`: 最終 PDF の出力パス。省略時は実行ディレクトリ直下の `output.pdf`。
- `--workdir <作業ディレクトリ>` / `-w <作業ディレクトリ>`: YomiToku OCR 結果 PDF などの作業ファイル出力先。省略時は TIFF フォルダの親。
- `--half`: 二値化前に各ページを半分解像度へ縮小する（小さくなる）。省略時は元解像度。

### ラッパー
`yomitoku.ps1` は `<本のフォルダ>\out` を入力に、`cache` 削除・最終 PDF=`<本のフォルダ>\yomitoku\<本のフォルダ名>.pdf`・作業ディレクトリ=`<本のフォルダ>\yomitoku\yomitoku_pdf` を組み立てて渡す薄い PowerShell ラッパー。`-Half` で `--half` を渡す。
```powershell
.\yomitoku.ps1 <フォルダパス>
.\yomitoku.ps1 -Half <フォルダパス>
```

### 処理の流れ
1. 入力フォルダの `*.tif` を名前昇順で対象にする。
2. YomiToku を一括起動して各ページの検索可能 PDF を生成（`-f pdf --pdf_quality high`）。
3. 生成された PDF から順次、対応 TIFF を Otsu 二値化した 1bit TIFF にする（`--half` 指定時は二値化前に半分解像度へ縮小）。
4. ルート直下の `jbig2enc-0.31-Windows-X64-MSVC\bin\jbig2.exe --pdf` で JBIG2 ストリームを作り、PDF 内の背景画像 XObject だけを差し替える（OCR テキスト層は保持）。
5. 元 TIFF の DPI を基にページ内容とページサイズ（MediaBox/CropBox）を実寸ポイントへ補正する。
6. 全ページを結合し、ページ数・OCR テキスト層・JBIG2 背景・サイズを検証する。

---

## 仕組みのポイント / 注意

- GPU torch の固定: YomiToku は公開メタデータに CUDA 版 torch の索引を持たないため、`pyproject.toml` で torch/torchvision を cu126 wheel 索引（`[[tool.uv.index]]` + `[tool.uv.sources]`）に固定している。`uv tool install` / `uv run` では `--torch-backend` が使えない（`uv pip` 専用）ため、この方式が確実。
- PDF 品質: YomiToku は `--pdf_quality high` を使う。`middle` / `low` は OCR テキストの位置がずれることがある。
- 別 PC への移植: 同じ Windows + NVIDIA 環境なら `git clone` → `uv sync` → jbig2enc 0.31 x64 Release をルート直下へ展開、で同じ構成にできる。GPU が無い PC では cu126 torch は CPU 動作になり非常に遅い。

## 開発者向け

```
uv run ruff check .
uv run ruff format .
uv run ty check
```
