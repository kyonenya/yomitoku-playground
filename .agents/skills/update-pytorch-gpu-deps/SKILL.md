---
name: update-pytorch-gpu-deps
description: uv 管理の Python プロジェクトで PyTorch GPU 依存を pyproject.toml に設定・更新する。手元のGPUに合わせて torch/torchvision の対応バージョン、 wheel index を選ぶ。重い lock/sync/GPU検証コマンドはフォローアップとしてユーザーに提案する。
---

# PyTorch GPU 依存を更新する

このスキルの責務は `pyproject.toml` の編集まで。`uv lock`、`uv sync`、GPU検証は重い処理になりやすいので、実行せず、フォローアップとしてユーザーに提案する。

## 対象

- このスキルが手順を用意しているのは、NVIDIA GPU の CUDA wheel、AMD Radeon の ROCm wheel、GPUを使わない CPU wheel。
- Intel XPU、Apple MPS はこの手順書から外れるので、そのつど考える。`pyproject.toml` を置き換える前にユーザーへ確認する。

## 手順

1. プロジェクトの現状を確認する。
   - `pyproject.toml` を読む。
   - `requires-python`、既存の `torch` / `torchvision` pin、`[[tool.uv.index]]`、`[tool.uv.sources]` を確認する。
   - `torch` / `torchvision` に依存する他パッケージ（例: `yomitoku`）が torch のバージョン上限を持っていないか確認する。上限があれば、その範囲で選ぶ（上限が無ければ最新を狙ってよい）。
   - `torchaudio` も固定されている場合、またはユーザーが明示した場合だけ `torchaudio` も更新対象にする。
   - `.venv` があるか（＝すでに `uv sync` 済みか）も見る。フォローアップの出し分けに使う。

2. GPUとOSを判定する。
   - NVIDIA GPU なら CUDA 分岐へ進む。可能なら `nvidia-smi` を実行する。
   - AMD Radeon なら ROCm 分岐へ進む。Windows と Linux で手順が違うので、OSを必ず確認する。
   - GPUを使わない、または使えない場合は CPU 分岐へ進む。
   - GPUが不明、複数候補がある、または手順書から外れるGPUの場合は、変更前にユーザーへ確認する。

3. NVIDIA CUDA の場合。
   - `nvidia-smi` に表示される `CUDA Version` は「ローカルに入っているCUDA Toolkitのバージョン」ではなく、「そのNVIDIAドライバが対応できるCUDA runtimeの上限」として扱う。
   - `cu130`、`cu128`、`cu126` のように、その上限以下の PyTorch wheel CUDA tag を選ぶ。
   - まず `https://pytorch.org/get-started/previous-versions/` を見る。`torch` / `torchvision`（必要なら `torchaudio`）の対応行と、その行で使えるCUDA tagが一度に分かる。**バージョンの組み合わせはこのページを正とする。**
   - 必要なら `https://download.pytorch.org/whl/<cuda-tag>/{torch,torchvision}/` で、選んだバージョンに `requires-python` とローカルPython（cp311 など）・プラットフォーム（win_amd64 など）の wheel が実在するか確認する。
   - CUDA wheel は次の形で `pyproject.toml` に反映する。

     ```toml
     dependencies = [
         "torch==2.x.y",
         "torchvision==0.x.y",
     ]

     [[tool.uv.index]]
     name = "pytorch-cuXXX"
     url = "https://download.pytorch.org/whl/cuXXX"
     explicit = true

     [tool.uv.sources]
     torch = { index = "pytorch-cuXXX" }
     torchvision = { index = "pytorch-cuXXX" }
     ```

4. AMD Radeon ROCm on Linux の場合。
   - まず `https://pytorch.org/get-started/locally/` と `https://pytorch.org/get-started/previous-versions/` を見る。Linux + Pip + ROCm の公式行から、`torch` / `torchvision`（必要なら `torchaudio`）の対応バージョンと `rocmX.Y` tag を選ぶ。
   - 必要なら `https://download.pytorch.org/whl/<rocm-tag>/{torch,torchvision}/` で、選んだバージョンに `requires-python` とローカルPython（cp311 など）・プラットフォーム（linux_x86_64 など）の wheel が実在するか確認する。
   - Linux ROCm wheel は次の形で `pyproject.toml` に反映する。

     ```toml
     dependencies = [
         "torch==2.x.y",
         "torchvision==0.x.y",
     ]

     [[tool.uv.index]]
     name = "pytorch-rocmXY"
     url = "https://download.pytorch.org/whl/rocmX.Y"
     explicit = true

     [tool.uv.sources]
     torch = { index = "pytorch-rocmXY" }
     torchvision = { index = "pytorch-rocmXY" }
     ```

5. AMD Radeon ROCm on Windows の場合。
   - PyTorch公式の汎用selectorではなく、AMD公式の Radeon/Ryzen 向け手順を正とする。
   - 参照先:
     - `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html`
     - `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html`
   - AMD docs の対応表で、Windows 11、対応Radeon GPU、PyTorch版、ROCm版、Python版を確認する。
   - AMD公式が direct wheel URL を提示している場合、通常indexではなく direct URL dependency として `pyproject.toml` に反映する。既存の `torch` / `torchvision` に対する `[tool.uv.sources]` の index 指定は、direct URL と競合しないように削除する。

     ```toml
     dependencies = [
         "torch @ https://repo.radeon.com/rocm/windows/rocm-rel-X.Y.Z/torch-...-win_amd64.whl",
         "torchvision @ https://repo.radeon.com/rocm/windows/rocm-rel-X.Y.Z/torchvision-...-win_amd64.whl",
     ]
     ```

   - AMD公式手順が ROCm SDK wheel や tarball の追加インストールを要求している場合、それらは `pyproject.toml` へ無理に押し込まず、フォローアップタスクとして明示する。
   - cp312専用などで `requires-python` やローカルPython変更が必要な場合は、勝手に広範囲変更せず、必要な後続作業としてユーザーに伝える。

6. CPU（GPUを使わない）の場合。
   - GPUドライバや CUDA/ROCm tag の判定は不要。`requires-python` とローカルPython・プラットフォームに合う `torch` / `torchvision`（必要なら `torchaudio`）の対応版を選ぶ。
   - バージョンの組み合わせは `https://pytorch.org/get-started/previous-versions/` を正とする。必要なら `https://download.pytorch.org/whl/cpu/{torch,torchvision}/` で wheel が実在するか確認する。
   - CPU wheel は次の形で `pyproject.toml` に反映する。

     ```toml
     dependencies = [
         "torch==2.x.y",
         "torchvision==0.x.y",
     ]

     [[tool.uv.index]]
     name = "pytorch-cpu"
     url = "https://download.pytorch.org/whl/cpu"
     explicit = true

     [tool.uv.sources]
     torch = { index = "pytorch-cpu" }
     torchvision = { index = "pytorch-cpu" }
     ```

7. 共通の選定ルール。
   - `torch` と `torchvision` は、必ず公式が示す同じ組み合わせを使う。
   - whl index には previous-versions にまだ載っていない新しい版が出ることがある。**index 同士でバージョンを突き合わせてペアを組まない**。
   - 最新のCUDA/ROCm tagやPyTorchバージョンで解決できない場合は、任意に混ぜず、次に古い公式tagまたは公式バージョンへ下げる。
   - 既存の書き方に合わせ、無関係な整形や依存変更はしない。

8. フォローアップを提案する。
   - `uv.lock` は手で編集しない。
   - 提案する後続コマンドはプロジェクトの状態で変える。
     - すでに `uv sync` 済みで `.venv` がある既存プロジェクトの更新なら、torch/torchvision を確実に貼り替えるため `--upgrade-package` を使う。

       ```powershell
       uv lock --upgrade-package torch --upgrade-package torchvision
       uv sync
       ```

     - クローン直後でまだ一度も `uv sync` していない（`.venv` が無い）なら、`--upgrade-package` は不要。初回構築として `uv sync` だけでよい（pyproject と lock が食い違っていれば自動で取り直される）。

       ```powershell
       uv sync
       ```

   - 構築後の検証コマンドはどちらも共通。

     ```powershell
     uv run python -c "import torch, torchvision; print(torch.__version__); print(torchvision.__version__); print(torch.cuda.is_available()); print(torch.version.cuda)"
     ```

   - 検証結果の見方も伝える。
     - NVIDIA CUDA は `torch.cuda.is_available()` が `True` になり、`torch.version.cuda` が選んだ wheel 系列（たとえば `12.6`、`12.8`、`13.0`）と合っていれば成功。
     - ROCm build でもPyTorch API上は `torch.cuda.is_available()` を使うことがある。Radeonの場合は、AMD公式docsの検証手順を優先し、device名がRadeonになっているかも確認するよう提案する。
     - CPU wheel は `torch.cuda.is_available()` が `False`、`torch.version.cuda` が `None` で正常。

## 注意

- NVIDIAはCUDA、AMD RadeonはROCm。`cuXXX` と `rocmX.Y` は混ぜない。
- prebuilt のPyTorch wheelを使う場合、NVIDIAではローカルの CUDA Toolkit や `nvcc` は通常不要。重要なのはNVIDIAドライバとPyTorch wheelに同梱されたCUDA runtime。
- Radeon on Windows は対応GPU・Python版・ROCm版の制約が強い。AMD公式の対応表に載っていない構成では、`pyproject.toml` を書き換える前にユーザーへリスクを伝える。
