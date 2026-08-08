#requires -Version 7.0

[CmdletBinding()]
param([string]$ModelId = "nli-MiniLM2-L6-H768")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$revision = "b95119ce93d3e065de6214e38cd4a97b0f2f2c6d"
$expectedModelHash = "44391A5241A62E0083C1A8899A71E69A092B95AEA5BA89E14062925468ECEAC7"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repositoryRoot "ONNX host service\models\$ModelId"
$baseUrl = "https://huggingface.co/cross-encoder/nli-MiniLM2-L6-H768/resolve/$revision"
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
        if ($hash -ne $expectedModelHash) { Remove-Item -LiteralPath $download -Force; throw "NLI model checksum mismatch" }
    }
    Move-Item -LiteralPath $download -Destination $destination -Force
}
[ordered]@{
    task = "nli"; tokenizer = "tokenizer.json"; output = "logits"; max_length = 512
    pad_id = 1; pad_token = "<pad>"
    labels = [ordered]@{ "0" = "contradiction"; "1" = "entailment"; "2" = "neutral" }
    source = "cross-encoder/nli-MiniLM2-L6-H768"; revision = $revision
    model_sha256 = $expectedModelHash.ToLowerInvariant(); license = "apache-2.0"
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $target "adapter.json") -Encoding utf8
Write-Host "Installed $ModelId at '$target'."
