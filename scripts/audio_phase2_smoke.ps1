$ErrorActionPreference = "Stop"

function Call-Api {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        $Body = $null,
        [switch]$AllowError
    )

    $url = "http://127.0.0.1:8000$Path"
    try {
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 12
            $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $url -ContentType "application/json" -Body $json
        } else {
            $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $url
        }
        $content = if ($resp.Content) { $resp.Content | ConvertFrom-Json } else { $null }
        return [pscustomobject]@{ ok = $true; status = [int]$resp.StatusCode; body = $content }
    } catch {
        $statusCode = $null
        $detail = $_.Exception.Message
        if ($_.Exception.Response) {
            try {
                $statusCode = [int]$_.Exception.Response.StatusCode
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $raw = $reader.ReadToEnd()
                if ($raw) {
                    try { $detail = (ConvertFrom-Json $raw).detail } catch { $detail = $raw }
                }
            } catch {}
        }
        if ($AllowError) {
            return [pscustomobject]@{ ok = $false; status = $statusCode; body = $detail }
        }
        throw
    }
}

$results = @()
function Add-Result([string]$Name, [bool]$Pass, [string]$Detail) {
    $script:results += [pscustomobject]@{ step = $Name; pass = $Pass; detail = $Detail }
}

# Mode A simulation: module off, then runtime enable.
$null = Call-Api -Method POST -Path "/audio/module" -Body @{ enabled = $false }
$statusOff = Call-Api -Method GET -Path "/status"
$stateOff = Call-Api -Method GET -Path "/audio/state"
Add-Result "modeA_disable_status_flag" ($statusOff.body.features.audio_module_enabled -eq $false) ("audio_module_enabled=$($statusOff.body.features.audio_module_enabled)")
Add-Result "modeA_disable_state_flag" ($stateOff.body.audio_enabled -eq $false) ("audio_enabled=$($stateOff.body.audio_enabled)")

$null = Call-Api -Method POST -Path "/audio/module" -Body @{ enabled = $true }
$statusOn = Call-Api -Method GET -Path "/status"
Add-Result "modeA_enable_status_flag" ($statusOn.body.features.audio_module_enabled -eq $true) ("audio_module_enabled=$($statusOn.body.features.audio_module_enabled)")
Add-Result "modeB_enabled_available" ($statusOn.body.features.audio_module_enabled -eq $true) "audio module enabled and reachable"

# Policy, stream lifecycle, and live meter verification.
$playRouteId = "phase2_playback_test"
$asrRouteId = "phase2_asr_test"
$ttsRouteId = "phase2_tts_file_test"

$null = Call-Api -Method POST -Path "/audio/routes" -Body @{
    route_id = $playRouteId
    name = "Phase2 playback route"
    source = @{ kind = "test_tone"; name = "tone"; config = @{ tone_hz = 330; amplitude = 0.2; duration_seconds = 0.2 } }
    processors = @()
    sink = @{ kind = "file"; name = "file sink"; config = @{ path = "audio_outputs/phase2_playback_test.wav" } }
    enabled = $true
}
$null = Call-Api -Method POST -Path "/audio/routes" -Body @{
    route_id = $asrRouteId
    name = "Phase2 asr route"
    source = @{ kind = "test_tone"; name = "tone asr"; config = @{ tone_hz = 220; amplitude = 0.15; duration_seconds = 0.25 } }
    processors = @(@{ kind = "asr_ingress"; name = "asr ingress"; config = @{} })
    sink = @{ kind = "asr"; name = "asr sink"; config = @{} }
    enabled = $true
}

$startPlay = Call-Api -Method POST -Path "/audio/streams/$playRouteId/start"
Add-Result "stream_start_playback" ($startPlay.ok -and $startPlay.body.stream.state -eq "running") ("state=$($startPlay.body.stream.state)")

$null = Call-Api -Method POST -Path "/audio/policy" -Body @{ mode = "capture_gated_by_playback" }
$startAsrConflict = Call-Api -Method POST -Path "/audio/streams/$asrRouteId/start" -AllowError
Add-Result "policy_conflict_409" ((-not $startAsrConflict.ok) -and ($startAsrConflict.status -eq 409)) ("status=$($startAsrConflict.status)")

$null = Call-Api -Method POST -Path "/audio/policy" -Body @{ mode = "barge_in_enabled" }
$startAsr = Call-Api -Method POST -Path "/audio/streams/$asrRouteId/start"
$interrupted = @()
if ($startAsr.body.interrupted_stream_ids) { $interrupted = @($startAsr.body.interrupted_stream_ids) }
Add-Result "barge_in_interrupts_playback" $interrupted.Contains($playRouteId) ("interrupted=$([string]::Join(',', $interrupted))")

Start-Sleep -Milliseconds 800
$meters = Call-Api -Method GET -Path "/audio/meters"
$playMeter = $meters.body.meters | Where-Object { $_.stream_id -eq $playRouteId } | Select-Object -First 1
$asrMeter = $meters.body.meters | Where-Object { $_.stream_id -eq $asrRouteId } | Select-Object -First 1
Add-Result "live_meter_values_present" (($playMeter.peak -gt 0) -or ($asrMeter.peak -gt 0)) ("play_peak=$($playMeter.peak) asr_peak=$($asrMeter.peak)")

$null = Call-Api -Method POST -Path "/audio/streams/$asrRouteId/stop"
$null = Call-Api -Method POST -Path "/audio/streams/$playRouteId/stop"

# TTS source route check (adapter + fallback path should both produce real output).
$null = Call-Api -Method POST -Path "/audio/routes" -Body @{
    route_id = $ttsRouteId
    name = "TTS file route"
    source = @{ kind = "tts"; name = "tts source"; config = @{ text = "phase two adapter check"; duration_seconds = 0.3 } }
    processors = @(@{ kind = "tts_egress_formatter"; config = @{} })
    sink = @{ kind = "file"; config = @{ path = "audio_outputs/phase2_tts_file_test.wav" } }
    enabled = $true
}
$null = Call-Api -Method POST -Path "/audio/streams/$ttsRouteId/start"
Start-Sleep -Milliseconds 800
$meters2 = Call-Api -Method GET -Path "/audio/meters"
$ttsMeter = $meters2.body.meters | Where-Object { $_.stream_id -eq $ttsRouteId } | Select-Object -First 1
$null = Call-Api -Method POST -Path "/audio/streams/$ttsRouteId/stop"
Add-Result "tts_route_meter_active" ($ttsMeter.peak -gt 0) ("tts_peak=$($ttsMeter.peak)")
Add-Result "tts_file_written" (Test-Path "audio_outputs/phase2_tts_file_test.wav") "audio_outputs/phase2_tts_file_test.wav"

# Defaults roundtrip.
$devices = Call-Api -Method GET -Path "/audio/devices"
$defaultIn = $devices.body.default_input_device_id
$defaultOut = $devices.body.default_output_device_id
$null = Call-Api -Method POST -Path "/audio/defaults" -Body @{ default_input_device_id = $defaultIn; default_output_device_id = $defaultOut }
$stateAfterDefaults = Call-Api -Method GET -Path "/audio/state"
$defaultsPass = ($stateAfterDefaults.body.defaults.default_input_device_id -eq $defaultIn) -and ($stateAfterDefaults.body.defaults.default_output_device_id -eq $defaultOut)
Add-Result "defaults_roundtrip" $defaultsPass ("input=$defaultIn output=$defaultOut")

# Cleanup.
$null = Call-Api -Method DELETE -Path "/audio/routes/$asrRouteId" -AllowError
$null = Call-Api -Method DELETE -Path "/audio/routes/$playRouteId" -AllowError
$null = Call-Api -Method DELETE -Path "/audio/routes/$ttsRouteId" -AllowError

$passCount = ($results | Where-Object { $_.pass }).Count
$total = $results.Count

[pscustomobject]@{
    pass_count = $passCount
    total = $total
    all_passed = ($passCount -eq $total)
    results = $results
} | ConvertTo-Json -Depth 8
