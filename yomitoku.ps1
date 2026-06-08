[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,
    [int]$Dpi = 0
)
$ErrorActionPreference = "Stop"

$inputDir = Join-Path $ScanDir "out"
if (-not (Test-Path -LiteralPath $inputDir -PathType Container)) {
    throw "input TIFF directory not found: $inputDir"
}

$cacheDir = Join-Path $inputDir "cache"
if (Test-Path -LiteralPath $cacheDir -PathType Container) {
    Write-Host "removing cache: $cacheDir"
    Remove-Item -LiteralPath $cacheDir -Recurse -Force
}

$outputDir = Join-Path $ScanDir "yomitoku"
$pyArgs = @(
    $inputDir,
    "--output", (Join-Path $outputDir "$((Get-Item -LiteralPath $ScanDir).Name).pdf")
)
if ($Dpi -gt 0) { $pyArgs += @("--dpi", $Dpi) }

uv run yomitoku.py @pyArgs
