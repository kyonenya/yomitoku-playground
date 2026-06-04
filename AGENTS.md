# スキャンOCRワークフロー メモ

このディレクトリでは、日本語書籍スキャン画像から、YomiToku のOCR位置精度を保ったまま、サイズの小さい検索可能PDFを作るための実験を行った。

## 実施した環境変更

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
  - ユーザーが `C:\Users\kyone\Documents\jbig2enc` に配置した。
  - ユーザーPATHに `C:\Users\kyone\Documents\jbig2enc` を追加した。
  - `jbig2.exe` は32bit実行ファイルで、32bit版 `MSVCR120.dll` が必要だった。
  - Visual C++ 2013 Redistributable x86 を winget で強制再インストールしたが、`C:\Windows\SysWOW64\MSVCR120.dll` は見つからなかった。
  - 32bit版DLLを以下で確認した。
    - `C:\Program Files\Microsoft Office\root\vfs\ProgramFilesX86\Microsoft Office\Office16\msvcr120.dll`
  - そのDLLを以下へコピーし、jbig2encフォルダ単体で起動できるようにした。
    - `C:\Users\kyone\Documents\jbig2enc\msvcr120.dll`
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
- 参考PDF `C:\Users\kyone\scan\フィクションを怖がる.pdf` が小さい理由は、背景画像が 1bit 白黒かつ JBIG2 圧縮だったため。
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
  - `C:\Users\kyone\scan\src\bw_ccitt`
- 半分解像度の出力先:
  - `C:\Users\kyone\scan\src\bw_ccitt_half`

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
  - `C:\Users\kyone\scan\src\jbig2_full`
- 半分解像度の出力先:
  - `C:\Users\kyone\scan\src\jbig2_half`

## ページ257-263でのサイズ比較

元のYomiToku PDF:

- 場所: `C:\Users\kyone\scan\src`
- 対象: `src_フィクションとは何か_ページ_257.pdf` から `263.pdf`
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
  - `C:\Users\kyone\scan\jbig2_half_pdf.py`
- 基本実行例:
  - `py -3.11 jbig2_half_pdf.py "10_Scan\250527_ウォルトン-フィクションとはなにか\out"`
- `--output-name` を省略した場合:
  - 入力フォルダの親フォルダ名をPDF名にする。
  - 例: `10_Scan\250527_ウォルトン-フィクションとはなにか\out`
  - 出力PDF名: `250527_ウォルトン-フィクションとはなにか.pdf`
  - 出力先: `10_Scan\250527_ウォルトン-フィクションとはなにか\250527_ウォルトン-フィクションとはなにか`
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

`10_Scan\260601_私メタ\out`:

- 対象: 26 TIFF
- 出力: `out\260601_私メタ\260601_私メタ.pdf`
- OCRテキスト層: 26/26
- JBIG2背景: 26/26
- YomiToku元PDF合計: `37.266 MB`
- 最終PDF: `1.448 MB`
- 圧縮率: `3.9%`

`10_Scan\260601_感じられたものの文法\out`:

- 対象: 11 TIFF
- 出力: `10_Scan\260601_感じられたものの文法\感じられたものの文法\感じられたものの文法.pdf`
- OCRテキスト層: 11/11
- JBIG2背景: 11/11
- YomiToku元PDF合計: `25.792 MB`
- 最終PDF: `0.942 MB`
- 圧縮率: `3.7%`
- YomiToku一括起動中に、生成済みPDFから順次後段処理できることを確認した。

`10_Scan\230408_フィクションを怖がる\out`:

- 対象: 43 TIFF
- 出力: `フィクションを怖がる_jobs1_measure\フィクションを怖がる.pdf`
- OCRテキスト層: 43/43
- JBIG2背景: 43/43
- YomiToku元PDF合計: `85.359 MB`
- 最終PDF: `3.164 MB` からページサイズ補正後 `3.166 MB`
- 圧縮率: `3.7%`

