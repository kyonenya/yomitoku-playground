# yomitoku-slimpdf

[YomiToku](https://github.com/kotaro-kinoshita/yomitoku) で出力した検索可能 PDF のファイルサイズを劇的に削減するワークフロー

出力された PDF の背景ページ画像を軽量な白黒 JBIG2 画像に差し替えることで、OCR テキスト層を維持したままファイルサイズを20分の1以下に削減できる。

## サイズ比較

このリポジトリに入っているサンプルを処理した例。

| 内容 | サイズ | 比率 |
|---|---:|---:|
| YomiToku 生成 PDF<br />[`sample.yomitoku.pdf`](sample/yomitoku_expected/sample.yomitoku.pdf) | 24.5 MB | 100% |
| JBIG2 軽量化済 PDF<br />[`sample.pdf`](sample/yomitoku_expected/sample.pdf) | 874 KB | **3.5%** |

## 使い方

```powershell
uv run yomi.py sample/out -o sample/yomitoku/sample.pdf
```
```powershell
uv run yomi.py "<入力フォルダ>" -o "<出力PDFパス>" [--dpi <値>] [--chunk <分割数>]
```

引数・オプション:

- 第1引数: `*.tif` が直接入ったフォルダ。
- `--output <PDFパス>` / `-o <PDFパス>`: 最終 PDF の出力パス。省略時は実行ディレクトリ直下の `output.pdf`。
- `--dpi <値>`: 背景画像を指定 DPI へ縮小する（小さくなる）。元解像度を上回る指定では拡大しない。省略時は元解像度。
- `--chunk <分割数>`: YomiToku のOCR処理を指定数に分割する。例: 527ページで `--chunk 3` なら、おおむね3等分して処理する。省略時は1分割。

`--dpi <値>` を付けると背景画像をその DPI へ縮小して PDF を小さくできる（既定は元解像度のまま）。
`--chunk <分割数>` を付けると、YomiToku のOCR処理を指定数に分割してメモリ使用量を抑えられる。
YomiToku が生成した素の検索可能 PDF は、最終 PDF の隣に `<出力名>.yomitoku.pdf` として残る。これが既に存在する場合は YomiToku の再実行（遅い GPU OCR）をスキップして再利用するので、`--dpi` の付け替えなどを素早く試せる。作り直したいときはこのファイルを消す。

### ラッパースクリプト

`yomi.ps1` は `<本のフォルダ>\out` を入力に、最終 PDF=`<本のフォルダ>\yomitoku\<本のフォルダ名>.pdf` を組み立てて渡す薄い PowerShell ラッパー。素の検索可能 PDF は同じ `yomitoku` フォルダに `<本のフォルダ名>.yomitoku.pdf` として残る。`-Dpi <値>` で `--dpi`、`-Chunk <分割数>` で `--chunk` を渡す。

```powershell
.\yomi.ps1 sample
```
```powershell
.\yomi.ps1 sample -Dpi 300 -Chunk 2
```

## セットアップ手順

推奨環境: Windows + NVIDIA GPU

```powershell
nvidia-smi
# -> CUDA Version: 13.1
```

### 1. このリポジトリをクローン

```powershell
git clone git@github.com:kyonenya/yomitoku-slimpdf.git
cd yomitoku-slimpdf
```

### 2. uv をインストール

```powershell
winget install --id=astral-sh.uv -e
```

インストール後はシェルを開き直す（PATH 反映のため）。確認:

```powershell
uv --version
```

### 3. PyTorch CUDA 依存を更新する

`pyproject.toml` の PyTorch CUDA 依存関係を自身の GPU に合うように更新する。

この手順はエージェント用スキルとして [`update-pytorch-cuda-deps`](.agents/skills/update-pytorch-cuda-deps/SKILL.md) を用意してある。
Codex / Claude Code など任意のエージェントで実行できる。

```text
スキル .agents/skills/update-pytorch-cuda-deps/SKILL.md を実行して
```

### 4. Python 依存関係をインストール

```powershell
uv sync
```

初回は PyTorch が数 GB あるためダウンロードに時間がかかる。
完了後、GPU が効いているか確認する。

```powershell
uv run python -c "import torch; print(torch.cuda.is_available())"
# -> True
```

### 5. jbig2enc をルート直下へ展開

JBIG2 圧縮に使うネイティブツール [jbig2enc](https://github.com/agl/jbig2enc) を プロジェクトルート直下に展開する。

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
