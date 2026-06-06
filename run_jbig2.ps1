[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir
)

$ErrorActionPreference = "Stop"

$tiffDir = Join-Path $ScanDir "out"
$outDir = Join-Path $ScanDir "yomitoku"
$cacheDir = Join-Path $tiffDir "cache"
$outputName = "$((Get-Item -LiteralPath $ScanDir).Name).pdf"

if (-not (Test-Path -LiteralPath $tiffDir -PathType Container)) {
    throw "input TIFF directory not found: $tiffDir"
}

if (Test-Path -LiteralPath $cacheDir -PathType Container) {
    Write-Host "removing cache: $cacheDir"
    Remove-Item -LiteralPath $cacheDir -Recurse -Force
}

uv run jbig2_pdf.py $tiffDir --out-dir $outDir --output-name $outputName
