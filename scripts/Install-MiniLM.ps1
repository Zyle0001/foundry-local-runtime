#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$ModelId = "all-MiniLM-L6-v2"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$revision = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
$expectedModelHash = "6FD5D72FE4589F189F8EBC006442DBB529BB7CE38F8082112682524616046452"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repositoryRoot "ONNX host service\models\$ModelId"
$baseUrl = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/$revision"

$assets = [ordered]@{
    "model.onnx" = "onnx/model.onnx"
    "tokenizer.json" = "tokenizer.json"
    "tokenizer_config.json" = "tokenizer_config.json"
    "special_tokens_map.json" = "special_tokens_map.json"
    "config.json" = "config.json"
    "sentence_bert_config.json" = "sentence_bert_config.json"
    "pooling_config.json" = "1_Pooling/config.json"
}

New-Item -ItemType Directory -Force -Path $target | Out-Null

foreach ($asset in $assets.GetEnumerator()) {
    $destination = Join-Path $target $asset.Key
    $download = "$destination.download"
    Write-Host "Downloading $($asset.Key)..."
    Invoke-WebRequest -Uri "$baseUrl/$($asset.Value)" -OutFile $download
    if ($asset.Key -eq "model.onnx") {
        $downloadHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash
        if ($downloadHash -ne $expectedModelHash) {
            Remove-Item -LiteralPath $download -Force
            throw "MiniLM model checksum mismatch. Expected $expectedModelHash, received $downloadHash."
        }
    }
    Move-Item -LiteralPath $download -Destination $destination -Force
}

$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $target "model.onnx")).Hash
if ($actualHash -ne $expectedModelHash) {
    throw "MiniLM model checksum mismatch. Expected $expectedModelHash, received $actualHash."
}

$adapter = [ordered]@{
    task = "text-embedding"
    tokenizer = "tokenizer.json"
    output = "last_hidden_state"
    pooling = "mean"
    normalize = $true
    max_length = 256
    dimensions = 384
    pad_id = 0
    pad_token = "[PAD]"
    source = "sentence-transformers/all-MiniLM-L6-v2"
    revision = $revision
    model_sha256 = $expectedModelHash.ToLowerInvariant()
    license = "apache-2.0"
}

$adapter | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target "adapter.json") -Encoding utf8
Write-Host "Installed $ModelId at '$target'."
