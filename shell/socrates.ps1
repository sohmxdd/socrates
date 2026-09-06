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

# Initialize history ID tracker so sourcing this script is never processed as a target command
$initH = Get-History -Count 1 -ErrorAction SilentlyContinue
$script:SocratesLastHistoryId = if ($initH) { $initH.Id } else { -1 }

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

# ── Event Dispatch ─────────────────────────────────────────────────────────────

function Invoke-SocratesSendEvent {
    param([string]$Json)
    try {
        $portFile = Join-Path $script:SocratesHome "daemon.port"
        if (Test-Path $portFile) {
            $port = [int](Get-Content $portFile -Raw).Trim()
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.SendTimeout = 400
            $tcp.Connect([System.Net.IPAddress]::Loopback, $port)
            if ($tcp.Connected) {
                $stream = $tcp.GetStream()
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json + "`n")
                $stream.Write($bytes, 0, $bytes.Length)
                $stream.Flush()
                $tcp.Close()
                return
            }
        }
    } catch {}

    # Fallback to client.py if direct loopback TCP fails
    try {
        $Json | python $script:SocratesClient 2>$null
    } catch {}
}

# ── 2. Postcmd: Complete Event & Check Pending ─────────────────────────────────

function Invoke-SocratesPostCmd {
    param([int]$ExitCode)

    $h = Get-History -Count 1 -ErrorAction SilentlyContinue
    if (-not $h -or ($h.Id -eq $script:SocratesLastHistoryId)) {
        Invoke-SocratesDeliverPending
        return
    }

    $script:SocratesLastHistoryId = $h.Id
    $cmd = $h.CommandLine

    if ([string]::IsNullOrWhiteSpace($cmd)) {
        Invoke-SocratesDeliverPending
        return
    }

    # Don't comment on sourcing socrates.ps1, clear, or cls
    if ($cmd -match 'socrates\.ps1' -or $cmd -eq 'clear' -or $cmd -eq 'cls') {
        Invoke-SocratesDeliverPending
        return
    }

    $startTs = $h.StartExecutionTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $endTs = $h.EndExecutionTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $cwd = (Get-Location).Path

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

        Invoke-SocratesSendEvent -Json $payload
    } catch {}

    # Brief check for incoming pending commentary (up to 250ms)
    if (Test-Path $script:SocratesPendingDir) {
        $deadline = (Get-Date).AddMilliseconds(250)
        while ((Get-Date) -lt $deadline) {
            $pending = Get-ChildItem -Path $script:SocratesPendingDir -Filter "*.json" -ErrorAction SilentlyContinue
            if ($pending) { break }
            Start-Sleep -Milliseconds 40
        }
    }

    Invoke-SocratesDeliverPending
}

# ── 3. PSReadLine History / Secret Interception ────────────────────────────────

# Ensure Enter is ALWAYS bound to AcceptLine (never removed or broken)
if ((Get-Module -Name PSReadLine -ErrorAction SilentlyContinue) -or (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue)) {
    try {
        Set-PSReadLineKeyHandler -Chord Enter -Function AcceptLine -ErrorAction SilentlyContinue
    } catch {}

    try {
        Set-PSReadLineOption -AddToHistoryHandler {
            param([string]$line)
            if ([string]::IsNullOrWhiteSpace($line)) { return $true }

            # Quick local secret pattern detector: immediate cyan warning before execution
            if ($line -match '(AKIA[0-9A-Z]{16}|ghp_[0-9a-zA-Z]{36}|sk_live_[0-9a-zA-Z]{24}|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----)') {
                Write-Host ""
                Write-Host "Socrates: " -ForegroundColor Cyan -NoNewline
                Write-Host "An API key or secret token sits plainly in that command line, ready to be preserved in shell history."
                Write-Host "Tell me -- is a secret truly private once you have broadcast it into your console?"
                Write-Host ""
            }

            return $true
        }
    } catch {}
}

# ── 4. Hook Prompt ─────────────────────────────────────────────────────────────

# Wrap prompt function safely without recursive re-wrapping
if (-not $script:OriginalPrompt) {
    if (Test-Path Function:\prompt) {
        $script:OriginalPrompt = $Function:prompt
    } else {
        $script:OriginalPrompt = { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
    }
}

function global:prompt {
    $lastExit = if ($null -ne $global:LASTEXITCODE) { [int]$global:LASTEXITCODE } else { 0 }
    Invoke-SocratesPostCmd -ExitCode $lastExit
    Invoke-SocratesFindLocalConfig
    & $script:OriginalPrompt
}

Write-Host "Socrates observer attached to PowerShell." -ForegroundColor Cyan
Write-Host "Type " -NoNewline
Write-Host "socrates status" -ForegroundColor Yellow -NoNewline
Write-Host " to verify daemon connectivity."
