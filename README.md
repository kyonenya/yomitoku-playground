# yomitoku-slimpdf

[YomiToku](https://github.com/kotaro-kinoshita/yomitoku) で出力した検索可能 PDF のファイルサイズを劇的に削減するワークフロー

出力された PDF の背景ページ画像を軽量な白黒 JBIG2 画像に差し替えることで、OCR テキスト層を維持したままファイルサイズを20分の1に削減できる。

推奨環境: Windows + NVIDIA GPU

## サイズ比較

このリポジトリに入っているサンプルを処理した例。

| 内容 | サイズ | YomiToku素PDF比 |
|---|---:|---:|
| YomiToku が生成した素の PDF（[`sample.yomitoku.pdf`](sample/yomitoku_expected/sample.yomitoku.pdf)） | 25.7 MB | 100% |
| 背景画像を JBIG2 に差し替えた PDF（[`sample.pdf`](sample/yomitoku_expected/sample.pdf)） | 895 KB | 3.5% |

## 使い方

入力は 1ページ1枚の TIFF を集めたフォルダ。
処理は `yomi.py` が担う。プロジェクトのルートで `uv run` から実行する。
`--dpi <値>` を付けると背景画像をその DPI へ縮小して PDF を小さくできる（既定は元解像度のまま）。
`--chunk <分割数>` を付けると、YomiToku のOCR処理を指定数に分割してメモリ使用量を抑えられる。

```powershell
uv run yomi.py "<入力フォルダ>" [--output "<出力PDFパス>"] [--dpi <値>] [--chunk <分割数>]
uv run yomi.py "<入力フォルダ>" -o "<出力PDFパス>" [--dpi <値>] [--chunk <分割数>]
```

引数・オプション:

- 第1引数: `*.tif` が直接入ったフォルダ。
- `--output <PDFパス>` / `-o <PDFパス>`: 最終 PDF の出力パス。省略時は実行ディレクトリ直下の `output.pdf`。
- `--dpi <値>`: 背景画像を指定 DPI へ縮小する（小さくなる）。元解像度を上回る指定では拡大しない。省略時は元解像度。
- `--chunk <分割数>`: YomiToku のOCR処理を指定数に分割する。例: 527ページで `--chunk 3` なら、おおむね3等分して処理する。省略時は1分割。

YomiToku が生成した素の検索可能 PDF は、最終 PDF の隣に `<出力名>.yomitoku.pdf` として残る。これが既に存在する場合は YomiToku の再実行（遅い GPU OCR）をスキップして再利用するので、`--dpi` の付け替えなどを素早く試せる。作り直したいときはこのファイルを消す。

### ラッパー

`yomi.ps1` は `<本のフォルダ>\out` を入力に、最終 PDF=`<本のフォルダ>\yomitoku\<本のフォルダ名>.pdf` を組み立てて渡す薄い PowerShell ラッパー。素の検索可能 PDF は同じ `yomitoku` フォルダに `<本のフォルダ名>.yomitoku.pdf` として残る。`-Dpi <値>` で `--dpi`、`-Chunk <分割数>` で `--chunk` を渡す。

```powershell
.\yomi.ps1 sample
.\yomi.ps1 sample -Dpi 300 -Chunk 2
```

## 必要なもの

- パッケージ管理：[uv](https://github.com/astral-sh/uv) 0.11+
- GPU：NVIDIA ドライバ（GeForce 等）
- ネイティブ：[jbig2enc](https://github.com/agl/jbig2enc)（`jbig2.exe`, 0.31 x64）uv 管理外。GitHub Release をルート直下へ展開する

## セットアップ手順（Windows + NVIDIA）

### 1. NVIDIA ドライバ

GeForce/Quadro の最新ドライバが入っていれば OK。確認:

```powershell
nvidia-smi
```

GPU 名とドライバ版が表示されればよい（例: RTX 4070 Ti / 591.86）。

### 2. PyTorch CUDA 依存を更新する

`pyproject.toml` の PyTorch CUDA 依存（`torch`, `torchvision`, `pytorch-cu126`）を自身の GPU に合うように更新する。
この手順はエージェント用スキルとして [`update-pytorch-cuda-deps/SKILL.md`](.agents/skills/update-pytorch-cuda-deps/SKILL.md) を用意してある。

Codex / Claude Code など任意のエージェントに SKILL.md を読ませて実行する。

```text
スキル .agents/skills/update-pytorch-cuda-deps/SKILL.md を実行して
```

### 3. uv をインストール

```powershell
winget install --id=astral-sh.uv -e
```

インストール後はシェルを開き直す（PATH 反映のため）。確認:

```powershell
uv --version
```

### 4. リポジトリを取得して Python 環境を構築

```powershell
git clone git@github.com:kotaro-kinoshita/yomitoku.git
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

### 5. jbig2enc をルート直下へ展開

JBIG2 圧縮に使うネイティブツール [jbig2enc](https://github.com/agl/jbig2enc) 64bit 版を GitHub Release からプロジェクトルート直下に展開する。

プロジェクトルートで実行:

```powershell
Invoke-WebRequest `
    -Uri "https://github.com/agl/jbig2enc/releases/download/0.31/jbig2enc-0.31-Windows-X64-MSVC.zip" `
    -OutFile "jbig2enc-0.31-Windows-X64-MSVC.zip"
Expand-Archive `
    -Path "jbig2enc-0.31-Windows-X64-MSVC.zip" `
    -Force
Remove-Item "jbig2enc-0.31-Windows-X64-MSVC.zip"

.\jbig2enc-0.31-Windows-X64-MSVC\bin\jbig2.exe --version
# -> jbig2enc 0.31
```

## 開発者向け

format

```powershell
uv run ruff format .
```

typecheck

```powershell
uv run ty check
```

lint

```powershell
uv run ruff check .
```
