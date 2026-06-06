# 私のディレクトリ構成専用の薄いラッパー（PowerShell で実行）。
# 構成依存の処理だけを担い、汎用処理は jbig2_pdf.py に委譲する。
#
# 使い方:
#   .\run_jbig2.ps1 "10_Scan\250620_Seminaire 1-1"
#   .\run_jbig2.ps1 "10_Scan\250620_Seminaire 1-1" -Half   # 半分解像度（小さい）
#
# やること:
#   - <本のフォルダ>\out を TIFF フォルダとして jbig2_pdf.py に渡す
#   - <本のフォルダ>\out\cache があれば消す
#   - 出力ファイル名は <本のフォルダ名>.pdf にする
#   - 出力先は <本のフォルダ>\yomitoku にする
#   - -Half 指定時は jbig2_pdf.py に --half をそのまま渡す（既定は元解像度）
#   - 最終PDFは <本のフォルダ>\yomitoku\<本のフォルダ名>.pdf に出る
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,  # 本のフォルダ（例: 10_Scan\250620_Seminaire 1-1）
    [switch]$Half      # 指定時は半分解像度化（--half をパススルー）
)

$ErrorActionPreference = "Stop"

$tiffDir = Join-Path $ScanDir "out"          # TIFF 置き場
$cacheDir = Join-Path $tiffDir "cache"
$outDir = Join-Path $ScanDir "yomitoku"      # 中間+最終PDF の出力先

if (-not (Test-Path -LiteralPath $tiffDir -PathType Container)) {
    throw "input TIFF directory not found: $tiffDir"
}

if (Test-Path -LiteralPath $cacheDir -PathType Container) {
    Write-Host "removing cache: $cacheDir"
    Remove-Item -LiteralPath $cacheDir -Recurse -Force
}

$outputName = "$((Get-Item -LiteralPath $ScanDir).Name).pdf"   # 出力名 = フォルダ名

$pyArgs = @($tiffDir, "--out-dir", $outDir, "--output-name", $outputName)
if ($Half) { $pyArgs += "--half" }

uv run jbig2_pdf.py @pyArgs
