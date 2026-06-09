---
name: update-pytorch-cuda-deps
description: uv 管理の Python プロジェクトで、NVIDIA GPU 向けの PyTorch CUDA 依存を pyproject.toml に設定・更新する。nvidia-smi の CUDA Version を読んで torch/torchvision の対応バージョンを選んで、cu126/cu128/cu130 などの PyTorch wheel index を切り替える。重い lock/sync/検証コマンドはフォローアップとしてユーザーに提案する場面で使う。
---

# PyTorch CUDA 依存を更新する

`uv` プロジェクトの `torch`、`torchvision`、PyTorch CUDA wheel index を `pyproject.toml` に反映する。

このスキルの責務は `pyproject.toml` の編集まで。`uv lock`、`uv sync`、CUDA検証は重い処理になりやすいので、実行せず、フォローアップとしてユーザーに提案する。

## 手順

1. プロジェクトの現状を確認する。
   - `pyproject.toml` を読む。
   - `requires-python`、既存の `torch` / `torchvision` pin、`[[tool.uv.index]]`、`[tool.uv.sources]` を確認する。
   - `torch` / `torchvision` に依存する他パッケージ（例: `yomitoku`）が torch のバージョン上限を持っていないか確認する。上限があれば、その範囲で選ぶ（上限が無ければ最新を狙ってよい）。
   - `torchaudio` も固定されている場合、またはユーザーが明示した場合だけ `torchaudio` も更新対象にする。

2. NVIDIA ドライバを確認する。
   - `nvidia-smi` を実行する。
   - 表示される `CUDA Version` は「ローカルに入っているCUDA Toolkitのバージョン」ではなく、「そのNVIDIAドライバが対応できるCUDA runtimeの上限」として扱う。
   - `cu130`、`cu128`、`cu126` のように、その上限以下の PyTorch wheel CUDA tag を選ぶ。

3. 公式の組み合わせを選ぶ。
   - まず `https://pytorch.org/get-started/previous-versions/` を見る。`torch` / `torchvision`（必要なら `torchaudio`）の対応行と、その行で使えるCUDA tag（cu126 / cu128 / cu130 など）が一度に分かる。**バージョンの組み合わせはこのページを正とする。**
   - 必要なら `https://download.pytorch.org/whl/<cuda-tag>/{torch,torchvision}/` で、選んだバージョンに `requires-python` とローカルPython（cp311 など）・プラットフォーム（win_amd64 など）の wheel が実在するか確認する。
   - whl index には previous-versions にまだ載っていない新しい版が出ることがある。**index 同士でバージョンを突き合わせてペアを組まない**。公式の同じ行に載っている `torch` / `torchvision` の組み合わせだけを使う。
   - 最新のCUDA tagやPyTorchバージョンで解決できない場合は、任意に混ぜず、次に古い公式CUDA tagまたは公式バージョンへ下げる。

4. `pyproject.toml` を編集する。
   - dependency pin を更新する。

     ```toml
     "torch==2.x.y",
     "torchvision==0.x.y",
     ```

   - 明示的な PyTorch index を更新する。

     ```toml
     [[tool.uv.index]]
     name = "pytorch-cuXXX"
     url = "https://download.pytorch.org/whl/cuXXX"
     explicit = true

     [tool.uv.sources]
     torch = { index = "pytorch-cuXXX" }
     torchvision = { index = "pytorch-cuXXX" }
     ```

   - 既存の書き方に合わせ、無関係な整形や依存変更はしない。

5. フォローアップを提案する。
   - `uv.lock` は手で編集しない。
   - `uv lock`、`uv sync`、CUDA検証はこのスキル内で実行しない。
   - `pyproject.toml` 編集後、次のような後続コマンドをユーザーに提案する。

     ```powershell
     uv lock --upgrade-package torch --upgrade-package torchvision
     uv sync
     uv run python -c "import torch, torchvision; print(torch.__version__); print(torchvision.__version__); print(torch.cuda.is_available()); print(torch.version.cuda)"
     ```

   - 検証結果の見方も伝える。`torch.cuda.is_available()` が `True` になり、`torch.version.cuda` が選んだ wheel 系列、たとえば `12.6`、`12.8`、`13.0` と合っていれば成功。

## 注意

- prebuilt の PyTorch wheel を使う場合、ローカルの CUDA Toolkit や `nvcc` は通常不要。重要なのは NVIDIA ドライバと PyTorch wheel に同梱されたCUDA runtime。
- `nvidia-smi` が使えない、NVIDIA GPUではない、またはCPU-onlyにしたい場合は、CUDA wheel をCPU wheelへ置き換える前にユーザーへ確認する。
