#requires -Version 7.0

[CmdletBinding()]
param([string]$ModelId = "ms-marco-MiniLM-L6-v2")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$revision = "eeed17e3bfc6fa06a790f2d12a9501fec587fccf"
$expectedModelHash = "C80A8B34256EA453093D612E3AC48D3D965A0C0A48C7906709AF8B8E28461BF9"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repositoryRoot "ONNX host service\models\$ModelId"
$baseUrl = "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/resolve/$revision"
$assets = [ordered]@{
    "model.onnx" = "onnx/model_quint8_avx2.onnx"
    "tokenizer.json" = "tokenizer.json"
    "tokenizer_config.json" = "tokenizer_config.json"
    "special_tokens_map.json" = "special_tokens_map.json"
    "config.json" = "config.json"
}
New-Item -ItemType Directory -Force -Path $target | Out-Null
foreach ($asset in $assets.GetEnumerator()) {
    $destination = Join-Path $target $asset.Key
    $download = "$destination.download"
    Invoke-WebRequest -Uri "$baseUrl/$($asset.Value)" -OutFile $download
    if ($asset.Key -eq "model.onnx") {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash
        if ($hash -ne $expectedModelHash) { Remove-Item -LiteralPath $download -Force; throw "Reranker checksum mismatch" }
    }
    Move-Item -LiteralPath $download -Destination $destination -Force
}
[ordered]@{
    task = "reranker"; tokenizer = "tokenizer.json"; output = "logits"; max_length = 512
    pad_id = 0; pad_token = "[PAD]"; positive_label = 0
    source = "cross-encoder/ms-marco-MiniLM-L6-v2"; revision = $revision
    model_sha256 = $expectedModelHash.ToLowerInvariant(); license = "apache-2.0"
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target "adapter.json") -Encoding utf8
Write-Host "Installed $ModelId at '$target'."
