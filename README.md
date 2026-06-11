# yomitoku-slimpdf

[YomiToku](https://github.com/kotaro-kinoshita/yomitoku) で生成した検索可能 PDF のファイルサイズを劇的に削減するワークフロー

出力された PDF の背景ページ画像を軽量な白黒 JBIG2 画像に差し替えることで、OCR テキスト層を維持したままファイルサイズを20分の1以下に削減できる。

## サイズ比較

このリポジトリに入っているサンプルを処理した例。

| 内容 | サイズ | 比率 |
|---|---:|---:|
| YomiToku 生成 PDF<br />[`sample.yomitoku.pdf`](sample/yomitoku_expected/sample.yomitoku.pdf) | 24.5 MB | 100% |
| JBIG2 軽量化済 PDF<br />[`sample.pdf`](sample/yomitoku_expected/sample.pdf) | 874 KB | **3.5%** |

## 使い方

```bash
uv run yomi.py sample/out --output sample/yomitoku/sample.pdf
```

```bash
uv run yomi.py sample/out -o sample/yomitoku/sample.pdf --dpi 300 --chunk 2
```

- 引数に `*.tif` が含まれるフォルダを指定する
- `--output`(`-o`) で出力 PDF のパスを指定できる。省略時は `./output.pdf`
- `--dpi` で出力される PDF の DPI を指定できる
- `--chunk` で YomiToku の OCR 処理を指定された数に分割して実行できる（メモリリーク対策）

### ラッパースクリプト

[ScanTailor](https://github.com/ImageProcessing-ElectronicPublications/scantailor-experimental) 系のフォルダ構成を前提としている。

```powershell
.\yomi.ps1 sample
```

```powershell
.\yomi.ps1 sample -Dpi 300 -Chunk 2
```

指定されたフォルダの `out/*.tif` を処理し、同じフォルダの `yomitoku/<folder_name>.pdf` に出力する。

## セットアップ手順

推奨環境: Windows + NVIDIA GPU

```bash
nvidia-smi
# -> CUDA Version: 1x.x
```

### 1. このリポジトリをクローン

```bash
git clone git@github.com:kyonenya/yomitoku-slimpdf.git
cd yomitoku-slimpdf
```

### 2. uv をインストール

[Installation | uv](https://docs.astral.sh/uv/getting-started/installation/#pypi) を参考に [uv](https://github.com/astral-sh/uv) をインストールする。

### 3. PyTorch CUDA 依存を更新する

`pyproject.toml` の PyTorch CUDA 依存関係を自身の GPU に合うように更新する。
この手順はエージェント用スキルとして [`update-pytorch-cuda-deps`](.agents/skills/update-pytorch-cuda-deps/SKILL.md) を用意してある。

```markdown
スキル .agents/skills/update-pytorch-cuda-deps/SKILL.md を実行して
```

Codex / Claude Code など任意のエージェントで実行できる。

### 4. Python 依存関係をインストール

```bash
uv sync
```

初回は PyTorch が数 GB あるためダウンロードに時間がかかる。
完了後、GPU が効いているか確認する。

```bash
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

```bash
uv run ruff format .
```

typecheck

```bash
uv run ty check .
```

lint

```bash
uv run ruff check .
```
