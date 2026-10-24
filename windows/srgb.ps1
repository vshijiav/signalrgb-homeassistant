<#
.SYNOPSIS
    Turn SignalRGB lights on/off and switch effects from the command line, no Pro needed.

.DESCRIPTION
    SignalRGB's own UI talks to its core over a local QWebChannel WebSocket
    (ws://127.0.0.1:16036, "SignalRGB WebPipe"). lighting.setAlwaysEffect(name)
    on that channel applies an effect without the Pro check the REST API (16038)
    and MCP (16037) enforce. "off" applies a lights-off effect and remembers the
    previous one; "on" restores it.

    The current effect is read through MCP read_status (free), so SignalRGB's
    MCP must stay enabled (Settings > Application > AI Integration).

.EXAMPLE
    srgb off
    srgb on
    srgb toggle
    srgb status
    srgb effect "Aurora"
#>
param(
    [Parameter(Position = 0)][ValidateSet('on', 'off', 'toggle', 'status', 'effect')][string]$Command = 'status',
    [Parameter(Position = 1)][string]$Name,
    # Installed effect used for "off". Default is "AA" + U+5173 U+706F, built from code points
    # because PowerShell 5.1 reads BOM-less files as the ANSI code page.
    [string]$OffEffect = 'AA' + [char]0x5173 + [char]0x706F
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$WebPipe = 'ws://127.0.0.1:16036/'
$McpUrl = 'http://127.0.0.1:16037/mcp'
$AppUrl = 'http://127.0.0.1:16034/api/v1/app'
# Kept beside the script: sandboxed shells can virtualize %LOCALAPPDATA%, which
# hid the state from scheduled tasks.
$StateDir = $PSScriptRoot
$StateFile = Join-Path $StateDir 'state.json'
$Utf8 = New-Object Text.UTF8Encoding($false)

function Read-State {
    if (Test-Path $StateFile) { return Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    return [pscustomobject]@{ lastEffect = $null; version = $null; methodIndex = $null }
}

function Write-State($state) {
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    [IO.File]::WriteAllText($StateFile, ($state | ConvertTo-Json), $Utf8)
}

function Invoke-Http([string]$url, [string]$body) {
    $wc = New-Object Net.WebClient
    $wc.Encoding = [Text.Encoding]::UTF8
    if ([string]::IsNullOrEmpty($body)) { return $wc.DownloadString($url) }
    $wc.Headers['Content-Type'] = 'application/json'
    return $wc.UploadString($url, $body)
}

function Get-CurrentEffect {
    $req = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"read_status","arguments":{}}}'
    $res = Invoke-Http $McpUrl $req | ConvertFrom-Json
    if ($res.result.isError) { throw "MCP read_status failed: $($res.result.content[0].text)" }
    # "Current effect: <name>, <description>"
    $text = $res.result.content[0].text
    if ($text -match '^Current effect: (.*?), ') { return $Matches[1] }
    return $text -replace '^Current effect: ', ''
}

function Open-WebPipe {
    $ws = New-Object Net.WebSockets.ClientWebSocket
    $ws.ConnectAsync([Uri]$WebPipe, [Threading.CancellationToken]::None).Wait()
    return $ws
}

function Send-Message($ws, [string]$json) {
    $bytes = $Utf8.GetBytes($json)
    $seg = New-Object 'ArraySegment[byte]' -ArgumentList (, $bytes)
    $ws.SendAsync($seg, [Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).Wait()
}

function Receive-Message($ws, [int]$timeoutMs) {
    $buffer = New-Object byte[] 65536
    $stream = New-Object IO.MemoryStream
    $cts = New-Object Threading.CancellationTokenSource($timeoutMs)
    try {
        do {
            $seg = New-Object 'ArraySegment[byte]' -ArgumentList (, $buffer)
            $task = $ws.ReceiveAsync($seg, $cts.Token)
            try { $task.Wait() } catch { return $null }
            $stream.Write($buffer, 0, $task.Result.Count)
        } while (-not $task.Result.EndOfMessage)
        return $Utf8.GetString($stream.ToArray())
    } finally { $cts.Dispose() }
}

# setAlwaysEffect's method index is fixed per SignalRGB build; resolve it from the
# channel's init message (~25 MB) only when the installed version changes.
function Get-MethodIndex($state) {
    $version = (Invoke-Http $AppUrl $null | ConvertFrom-Json).data.version
    if ($state.version -eq $version -and $state.methodIndex) { return [int]$state.methodIndex }

    $ws = Open-WebPipe
    try {
        Send-Message $ws '{"type":3,"id":0}'
        $init = Receive-Message $ws 30000
    } finally { $ws.Dispose() }
    if ($init -notmatch '\["setAlwaysEffect\(QString\)",(\d+)\]') {
        throw "setAlwaysEffect(QString) not found on the WebPipe channel (SignalRGB $version)"
    }
    $state.version = $version
    $state.methodIndex = [int]$Matches[1]
    Write-State $state
    return $state.methodIndex
}

function Set-Effect($state, [string]$effect) {
    $index = Get-MethodIndex $state
    $call = @{ type = 6; object = 'lighting'; method = $index; args = @($effect); id = 1 } | ConvertTo-Json -Compress
    $ws = Open-WebPipe
    try {
        Send-Message $ws $call
        $deadline = [DateTime]::Now.AddSeconds(5)
        while ([DateTime]::Now -lt $deadline) {
            $msg = Receive-Message $ws 5000
            if ($null -eq $msg) { break }
            if ($msg -match '"type":10' -and $msg -match '"id":1\b') { break }
        }
    } finally { $ws.Dispose() }

    Start-Sleep -Milliseconds 300
    $now = Get-CurrentEffect
    if ($now -ne $effect) { throw "Asked for '$effect' but SignalRGB is running '$now' (is the effect installed? names are as shown in the app)" }
}

$state = Read-State
$current = Get-CurrentEffect

if ($Command -eq 'toggle') { $Command = if ($current -eq $OffEffect) { 'on' } else { 'off' } }

switch ($Command) {
    'status' {
        $power = if ($current -eq $OffEffect) { 'off' } else { 'on' }
        Write-Output "$power ($current)"
    }
    'off' {
        if ($current -eq $OffEffect) { Write-Output "already off"; break }
        $state.lastEffect = $current
        Write-State $state
        Set-Effect $state $OffEffect
        Write-Output "off (was $current)"
    }
    'on' {
        if ($current -ne $OffEffect) { Write-Output "already on ($current)"; break }
        if (-not $state.lastEffect) { throw "No previous effect recorded; use: srgb effect <name>" }
        Set-Effect $state $state.lastEffect
        Write-Output "on ($($state.lastEffect))"
    }
    'effect' {
        if (-not $Name) { throw "Usage: srgb effect <name>" }
        Set-Effect $state $Name
        Write-Output "effect: $Name"
    }
}
