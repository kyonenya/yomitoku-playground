[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScanDir,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)
$ErrorActionPreference = "Stop"

$inputDir = Join-Path $ScanDir "out"
if (-not (Test-Path -LiteralPath $inputDir -PathType Container)) {
    throw "input TIFF directory not found: $inputDir"
}

$outputDir = Join-Path $ScanDir "yomitoku"
$outputName = "$((Get-Item -LiteralPath $ScanDir).Name).pdf"
$pyArgs = @(
    $inputDir,
    "--output", (Join-Path $outputDir $outputName)
) + $Rest

uv run yomi.py @pyArgs
