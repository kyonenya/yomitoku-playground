[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,
    [int]$Dpi = 0,
    [int]$Chunk = 0
)
$ErrorActionPreference = "Stop"

$inputDir = Join-Path $ScanDir "out"
if (-not (Test-Path -LiteralPath $inputDir -PathType Container)) {
    throw "input TIFF directory not found: $inputDir"
}

$outputDir = Join-Path $ScanDir "yomitoku"
$pyArgs = @(
    $inputDir,
    "--output", (Join-Path $outputDir "$((Get-Item -LiteralPath $ScanDir).Name).pdf")
)
if ($Dpi -gt 0) { $pyArgs += @("--dpi", $Dpi) }
if ($Chunk -gt 0) { $pyArgs += @("--chunk", $Chunk) }

uv run yomi.py @pyArgs
