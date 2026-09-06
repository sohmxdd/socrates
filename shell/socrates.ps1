# shell/socrates.ps1 — Socrates shell hook for Windows PowerShell
#
# Usage (run once in your PowerShell session, or add to $PROFILE):
#   . .\shell\socrates.ps1
#

$script:SocratesDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:SocratesClient = Join-Path $script:SocratesDir "client.py"
$script:SocratesHome = if ($env:SOCRATES_HOME) { $env:SOCRATES_HOME } else { Join-Path $HOME ".socrates" }
$script:SocratesPendingDir = Join-Path $script:SocratesHome "pending"
$script:SocratesSessionId = [System.Guid]::NewGuid().ToString()

$script:SocratesLastCmd = ""
$script:SocratesLastStart = ""

# ── 1. Deliver Pending Interventions at Prompt ─────────────────────────────────

function Invoke-SocratesDeliverPending {
    if (-not (Test-Path $script:SocratesPendingDir)) { return }

    # Identify git repo root if inside a git directory
    $repoRoot = $null
    try {
        $gitOut = git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitOut) {
            $repoRoot = $gitOut.Trim()
        }
    } catch {}

    $filesToInspect = @()
    if ($repoRoot) {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($repoRoot)
        $hashStr = ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-","").ToLower().Substring(0,16)
        $repoFile = Join-Path $script:SocratesPendingDir "$hashStr.json"
        if (Test-Path $repoFile) {
            $filesToInspect += $repoFile
        }
    }

    $allPending = Get-ChildItem -Path $script:SocratesPendingDir -Filter "*.json" -ErrorAction SilentlyContinue
    foreach ($item in $allPending) {
        if (-not ($filesToInspect -contains $item.FullName)) {
            $filesToInspect += $item.FullName
        }
    }

    foreach ($file in $filesToInspect) {
        if (Test-Path $file) {
            try {
                $raw = Get-Content $file -Raw -Encoding UTF8
                Remove-Item $file -Force -ErrorAction SilentlyContinue
                $content = $raw | ConvertFrom-Json
                if ($content -and $content.formatted_message) {
                    Write-Host ""
                    if ($content.is_commentary -or $content.rule_type -eq "commentary") {
                        Write-Host "Socrates observes: " -ForegroundColor DarkYellow -NoNewline
                    } else {
                        Write-Host "Socrates: " -ForegroundColor Cyan -NoNewline
                    }
                    Write-Host $content.formatted_message
                    Write-Host ""
                }
            } catch {}
        }
    }
}

function Invoke-SocratesFindLocalConfig {
    try {
        $dir = (Get-Location).Path
        while ($dir) {
            $c1 = Join-Path $dir ".socrates.yaml"
            $c2 = Join-Path $dir ".socrates.yml"
            if (Test-Path $c1) {
                $env:SOCRATES_LOCAL_CONFIG = $c1
                return
            }
            if (Test-Path $c2) {
                $env:SOCRATES_LOCAL_CONFIG = $c2
                return
            }
            $parent = Split-Path $dir -Parent
            if ($parent -eq $dir) { break }
            $dir = $parent
        }
        Remove-Item env:SOCRATES_LOCAL_CONFIG -ErrorAction SilentlyContinue
    } catch {}
}

# ── 2. Preexec: Check Secrets & Notify Daemon ──────────────────────────────────

function Invoke-SocratesPreExec {
    param([string]$Cmd)
    if ([string]::IsNullOrWhiteSpace($Cmd)) { return }

    $script:SocratesLastCmd = $Cmd
    $script:SocratesLastStart = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $cwd = (Get-Location).Path

    # Quick local secret pattern detector for immediate feedback before execution
    if ($Cmd -match "(AKIA[0-9A-Z]{16}|ghp_[0-9a-zA-Z]{36}|sk_live_[0-9a-zA-Z]{24}|-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----)") {
        Write-Host ""
        Write-Host "Socrates: " -ForegroundColor Cyan -NoNewline
        Write-Host "An API key or secret token sits plainly in that command line, ready to be preserved in shell history."
        Write-Host "Tell me -- is a secret truly private once you have broadcast it into your console?"
        Write-Host ""
    }

    # Dispatch preexec JSON event to daemon via client.py
    try {
        $payload = @{
            type = "preexec"
            session_id = $script:SocratesSessionId
            command = $Cmd
            cwd = $cwd
            start_ts = $script:SocratesLastStart
            capture_class = "SAFE"
        } | ConvertTo-Json -Compress

        Start-Job -ScriptBlock {
            param($client, $json)
            $json | python $client 2>$null
        } -ArgumentList $script:SocratesClient, $payload | Out-Null
    } catch {}
}

# ── 3. Postcmd: Complete Event & Check Pending ─────────────────────────────────

function Invoke-SocratesPostCmd {
    param([int]$ExitCode)

    if ($script:SocratesLastCmd) {
        $cmd = $script:SocratesLastCmd
        $startTs = $script:SocratesLastStart
        $endTs = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        $cwd = (Get-Location).Path

        $script:SocratesLastCmd = ""
        $script:SocratesLastStart = ""

        try {
            $payload = @{
                type = "postcmd"
                session_id = $script:SocratesSessionId
                command = $cmd
                cwd = $cwd
                start_ts = $startTs
                end_ts = $endTs
                exit_code = $ExitCode
                capture_class = "SAFE"
            } | ConvertTo-Json -Compress

            Start-Job -ScriptBlock {
                param($client, $json)
                $json | python $client 2>$null
            } -ArgumentList $script:SocratesClient, $payload | Out-Null
        } catch {}
    }

    Invoke-SocratesDeliverPending
}

# ── 4. Hook Prompt and PSReadLine ──────────────────────────────────────────────

# Wrap prompt function
if (Test-Path Function:\prompt) {
    $script:OriginalPrompt = $Function:prompt
} else {
    $script:OriginalPrompt = { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
}

function global:prompt {
    $lastExit = $global:LASTEXITCODE
    Invoke-SocratesPostCmd -ExitCode $lastExit
    Invoke-SocratesFindLocalConfig
    & $script:OriginalPrompt
}

# Hook Enter key if PSReadLine is available
if (Get-Module -Name PSReadLine -ErrorAction SilentlyContinue -or (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue)) {
    try {
        Set-PSReadLineKeyHandler -Chord Enter -ScriptBlock {
            $line = ""
            [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$null)
            if ($line) {
                Invoke-SocratesPreExec -Cmd $line
            }
            [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
        }
    } catch {}
}

Write-Host "Socrates observer attached to PowerShell." -ForegroundColor Cyan
Write-Host "Type " -NoNewline
Write-Host "socrates status" -ForegroundColor Yellow -NoNewline
Write-Host " to verify daemon connectivity."
