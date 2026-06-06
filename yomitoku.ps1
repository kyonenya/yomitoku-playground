[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,
    [switch]$Half
)

$ErrorActionPreference = "Stop"

$tiffDir = Join-Path $ScanDir "out"
$cacheDir = Join-Path $tiffDir "cache"
$outDir = Join-Path $ScanDir "yomitoku"

if (-not (Test-Path -LiteralPath $tiffDir -PathType Container)) {
    throw "input TIFF directory not found: $tiffDir"
}

if (Test-Path -LiteralPath $cacheDir -PathType Container) {
    Write-Host "removing cache: $cacheDir"
    Remove-Item -LiteralPath $cacheDir -Recurse -Force
}

$outputName = "$((Get-Item -LiteralPath $ScanDir).Name).pdf"

$pyArgs = @($tiffDir, "--out-dir", $outDir, "--output-name", $outputName)
if ($Half) { $pyArgs += "--half" }

uv run yomitoku.py @pyArgs
