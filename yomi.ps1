[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,
    [Nullable[int]]$Dpi,
    [Nullable[int]]$Chunk
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
if ($null -ne $Dpi) { $pyArgs += @("--dpi", $Dpi) }
if ($null -ne $Chunk) { $pyArgs += @("--chunk", $Chunk) }

uv run yomi.py @pyArgs
