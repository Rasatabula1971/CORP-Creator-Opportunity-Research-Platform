<#
.SYNOPSIS
  Kick off one autonomous discovery pass against a running CORP API and
  follow it to the end, printing what each stage did.

.DESCRIPTION
  Called by start_corp.bat once the API and dashboard are up, so a launch
  does the whole frozen flow on its own: the LLM picks the topics, drills
  them into niches, and the chain runs through to dossiers waiting at the
  human gate. Nothing here is CORP-specific logic; it only talks to the
  same endpoints a person could call by hand (GET /discovery/status,
  POST /discovery/run, GET /jobs/{id}).

  Exit codes: 0 pass completed, 1 pass failed, 2 could not start (no API,
  no LLM provider), 3 gave up waiting.
#>
param(
    [int]$Port = 8010,
    [string]$ApiKey = "",
    [int]$TimeoutMinutes = 180,
    [int]$PollSeconds = 15
)

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:$Port"
$headers = @{}
if ($ApiKey) { $headers["X-API-Key"] = $ApiKey }

function Say($text) { Write-Host "[corp] $text" }

function Get-Json($path) {
    return Invoke-RestMethod -Uri "$base$path" -Headers $headers -TimeoutSec 30
}

# -- 1. Wait for the API ---------------------------------------------------
$status = $null
$deadline = (Get-Date).AddSeconds(90)
while ($null -eq $status) {
    try {
        $status = Get-Json "/discovery/status"
    } catch {
        if ((Get-Date) -gt $deadline) {
            Say "The API on port $Port did not come up within 90s. Check the 'CORP API' window."
            exit 2
        }
        Start-Sleep -Seconds 3
    }
}

# -- 2. Pre-flight ---------------------------------------------------------
if (-not $status.can_run) {
    Say "Discovery cannot run: $($status.provider_detail)"
    Say "Add GEMINI_API_KEY or GROQ_API_KEY to .env and relaunch."
    exit 2
}
# The LLM router's own view: which keyed providers it refuses (and why),
# and the governor's status of the ones it accepted. One real solve call.
try {
    $health = Get-Json "/providers/health"
    if ($health.kind -eq "FairProvider") {
        if ($health.fair.ok) {
            Say "LLM router: FAIR, probe answered by $($health.fair.solve_provider)/$($health.fair.solve_model)."
        } else {
            Say "LLM router: FAIR probe failed: $($health.fair.detail)"
        }
        foreach ($p in $health.providers) {
            Say ("  {0,-24} {1,-16} {2} model(s)" -f $p.provider_id, $p.status, $p.models)
        }
        $skipped = $health.skipped
        if ($skipped) {
            foreach ($name in ($skipped | Get-Member -MemberType NoteProperty | ForEach-Object Name)) {
                Say ("  {0,-24} SKIPPED: {1}" -f $name, $skipped.$name)
            }
            $unconfirmed = @($skipped | Get-Member -MemberType NoteProperty | ForEach-Object Name | Where-Object { $skipped.$_ -match "confirm" })
            if ($unconfirmed) {
                Say ("  Add FAIR_CONFIRMED_FREE_PROVIDERS=" + ($unconfirmed -join ",") + " to .env once you have checked those accounts are free-only.")
            }
        }
    } else {
        Say "LLM provider: $($health.provider) ($($health.kind))."
    }
} catch {
    Say "Provider health check failed: $($_.Exception.Message)"
}

if ($status.momentum_available) {
    Say "Topics ranked by $($status.momentum_source) momentum."
} else {
    Say "Topics ranked by rotation ($($status.momentum_detail))."
}
if ($status.next_topics) {
    Say ("Next topics: " + ($status.next_topics -join ", "))
}

# -- 3. Start the pass (or follow one already running) ---------------------
$jobId = $status.active_job
if ($jobId) {
    Say "A discovery pass is already running ($jobId); following it."
} else {
    try {
        $job = Invoke-RestMethod -Method Post -Uri "$base/discovery/run" -Headers $headers `
            -ContentType "application/json" -Body "{}" -TimeoutSec 30
        $jobId = $job.id
        Say "Started autonomous discovery pass $jobId."
    } catch {
        $resp = $_.Exception.Response
        if ($resp -and [int]$resp.StatusCode -eq 409) {
            Say "Another job is already running; not starting a second pass."
            exit 0
        }
        Say "Could not start the pass: $($_.Exception.Message)"
        exit 2
    }
}
Say "Progress: this window, the 'CORP API' window (stage-by-stage log), and the dashboard's Jobs page."

# -- 4. Follow it ----------------------------------------------------------
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$lastStatus = ""
$started = Get-Date
while ($true) {
    try {
        $job = Get-Json "/jobs/$jobId"
    } catch {
        Say "Lost the API while waiting: $($_.Exception.Message)"
        exit 1
    }
    if ($job.status -ne $lastStatus) {
        Say "Job $jobId is $($job.status)."
        $lastStatus = $job.status
    }
    if ($job.status -eq "completed" -or $job.status -eq "failed") { break }
    if ((Get-Date) -gt $deadline) {
        Say "Still running after $TimeoutMinutes minutes; leaving it to finish. Watch the Jobs page."
        exit 3
    }
    $elapsed = [int]((Get-Date) - $started).TotalMinutes
    Write-Host -NoNewline "`r[corp] running... ${elapsed}m elapsed   "
    Start-Sleep -Seconds $PollSeconds
}
Write-Host ""

# -- 5. Report -------------------------------------------------------------
if ($job.status -eq "failed") {
    Say "The pass failed ($($job.error)). The 'CORP API' window has the full traceback."
    exit 1
}

$r = $job.result
Say ("Topics: {0} selected, {1} drilled, {2} failed." -f $r.topics_selected, $r.topics_drilled, $r.topics_failed)
foreach ($t in $r.topics) {
    $why = if ($t.error) { " - $($t.error)" } else { "" }
    Say ("  {0,-32} {1}{2}" -f $t.topic, $t.status, $why)
}
if ($r.pipeline) {
    Say "Pipeline after drilling:"
    foreach ($stage in @("canonicalize", "verify", "estimate_ecosystem", "qualify", "select", "onboard", "research_campaign")) {
        $entry = $r.pipeline.$stage
        if ($null -eq $entry) { Say ("  {0,-20} not reached" -f $stage); continue }
        $why = if ($entry.error) { " - $($entry.error)" } else { "" }
        Say ("  {0,-20} {1}{2}" -f $stage, $entry.status, $why)
    }
} elseif ($r.topics_drilled -eq 0) {
    Say "Nothing was drilled, so the rest of the chain did not run."
}
if ($r.campaign_id) {
    Say "Campaign: http://localhost:5173/campaigns/$($r.campaign_id)"
}
Say "Dossiers waiting for your decision: dashboard -> Creators (status human_review)."
exit 0
