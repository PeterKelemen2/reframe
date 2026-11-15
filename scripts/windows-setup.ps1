<#
.SYNOPSIS
    Sets up a Windows 10/11 machine to build and test Reframe: the CI toolchain, MKVToolNix
    (the header writer's tests compare with it) and, with -AuthorizedKey, an OpenSSH server for
    remote work.

.DESCRIPTION
    Run it in an elevated Windows PowerShell 5.1 (or pwsh). Every part checks what is installed
    first, so it can be run again after a failure or to add a part. Downloads are checked
    against the SHA-256 their publisher lists, or against their Authenticode signature where
    no checksum is published. See scripts/README.md.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File windows-setup.ps1 -AuthorizedKey 'ssh-ed25519 AAAA... me@host' -NoSleep
#>
[CmdletBinding()]
param(
    # A public key line: installs and enables sshd, and sets Git Bash as its shell (as CI's `shell: bash`).
    [string]$AuthorizedKey,
    # Skips the Visual Studio Build Tools and Rust (only needed for the desktop shell).
    [switch]$SkipDesktop,
    # Turns off sleep, hibernation and the display timeout on mains power: long test runs are
    # not suspended, and the desktop that GUI tests drive stays on.
    [switch]$NoSleep,
    # With -RepoDir: clones this URL there when the folder does not exist yet.
    [string]$RepoUrl,
    [string]$Branch,
    # A checkout here gets `uv sync`, the pinned FFmpeg (`reframe tools fetch`) and `npm ci`.
    [string]$RepoDir,
    [string]$ToolsDir = 'C:\Tools'
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell's progress bar makes Invoke-WebRequest many times slower.
$ProgressPreference = 'SilentlyContinue'
# Windows PowerShell 5.1 does not offer TLS 1.2 by default, and GitHub and nodejs.org require it.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in an elevated PowerShell.'
}

$work = Join-Path $env:TEMP 'reframe-setup'
New-Item -ItemType Directory -Force -Path $work, $ToolsDir | Out-Null

function Step([string]$text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Add-PathEntry([string]$dir, [switch]$User) {
    $keyPath = if ($User) { 'HKCU:\Environment' } else { 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' }
    $key = Get-Item $keyPath
    # Read and write the raw value: [Environment]::SetEnvironmentVariable would turn the
    # REG_EXPAND_SZ into REG_SZ and expand every %SystemRoot% in it.
    $raw = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    if (($raw -split ';') -notcontains $dir) {
        $value = if ($raw.Trim(';')) { $raw.TrimEnd(';') + ';' + $dir } else { $dir }
        Set-ItemProperty -Path $keyPath -Name Path -Value $value -Type ExpandString
    }
    Update-SessionPath
}

function Get-File([string]$url, [string]$name) {
    $out = Join-Path $work $name
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -UserAgent 'reframe-windows-setup'
    $out
}

function Get-Text([string]$url) {
    # .Content is a byte array, not a string, when the server sends no text content type.
    $content = (Invoke-WebRequest -Uri $url -UseBasicParsing -UserAgent 'reframe-windows-setup').Content
    if ($content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($content) } else { $content }
}

function Assert-Sha256([string]$file, [string]$expected) {
    $actual = (Get-FileHash -Algorithm SHA256 -Path $file).Hash
    if ($actual -ne $expected.Trim().ToUpperInvariant()) {
        throw "SHA-256 mismatch for $file`: expected $expected, got $actual"
    }
}

function Assert-Signed([string]$file) {
    $sig = Get-AuthenticodeSignature -FilePath $file
    if ($sig.Status -ne 'Valid') { throw "Bad Authenticode signature on $file`: $($sig.Status)" }
}

# A release asset and its SHA-256 from GitHub's API (the `digest` field).
function Get-GitHubAsset([string]$repo, [string]$pattern) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -UserAgent 'reframe-windows-setup'
    $asset = $release.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $asset) { throw "No asset matching '$pattern' in the latest release of $repo" }
    if ($asset.digest -notmatch '^sha256:') { throw "The release asset $($asset.name) of $repo has no SHA-256" }
    $file = Get-File $asset.browser_download_url $asset.name
    Assert-Sha256 $file ($asset.digest -replace '^sha256:', '')
    [pscustomobject]@{ Tag = $release.tag_name; File = $file }
}

function Invoke-Native([string]$exe, [string[]]$arguments, [int[]]$okCodes = @(0), [string]$log) {
    $redirect = @{}
    if ($log) { $redirect = @{ RedirectStandardOutput = $log } }
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -Wait -PassThru -NoNewWindow @redirect
    if ($okCodes -notcontains $p.ExitCode) { throw "$exe exited with code $($p.ExitCode)" }
    $p.ExitCode
}

function Expand-Into([string]$zip, [string]$dest) {
    $tmp = Join-Path $work ([IO.Path]::GetFileNameWithoutExtension($zip))
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp
    $items = @(Get-ChildItem $tmp)
    $src = if ($items.Count -eq 1 -and $items[0].PSIsContainer) { $items[0].FullName } else { $tmp }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Move-Item -Path $src -Destination $dest
}

function Read-Pin([string]$relative, [string]$fallback) {
    $file = Join-Path $PSScriptRoot "..\$relative"
    if (Test-Path $file) { (Get-Content $file -TotalCount 1).Trim() } else { $fallback }
}

$pythonVersion = Read-Pin '.python-version' '3.14'
$nodeMajor = Read-Pin 'frontend\.node-version' '24'
Update-SessionPath

Step 'Long paths and Developer Mode (symbolic links without elevation)'
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1 -Type DWord
$appModel = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
New-Item -Force -Path $appModel | Out-Null
Set-ItemProperty $appModel -Name AllowDevelopmentWithoutDevLicense -Value 1 -Type DWord

Step 'Git for Windows'
$gitExe = Join-Path $env:ProgramFiles 'Git\cmd\git.exe'
if (Test-Path $gitExe) {
    Write-Host "present: $(& $gitExe --version)"
} else {
    $git = Get-GitHubAsset 'git-for-windows/git' '^Git-[\d.]+-64-bit\.exe$'
    Invoke-Native $git.File @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES') | Out-Null
    Update-SessionPath
}
& $gitExe config --system core.longpaths true

Step "uv and Python $pythonVersion"
$uvDir = Join-Path $HOME '.local\bin'
if (-not (Test-Path (Join-Path $uvDir 'uv.exe'))) {
    $uv = Get-GitHubAsset 'astral-sh/uv' '^uv-x86_64-pc-windows-msvc\.zip$'
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    Expand-Archive -Path $uv.File -DestinationPath $uvDir -Force
}
Add-PathEntry $uvDir -User
& uv --version
& uv python install $pythonVersion
if ($LASTEXITCODE -ne 0) { throw "uv python install $pythonVersion failed" }

Step "Node.js $nodeMajor"
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node -and ((& node --version) -like "v$nodeMajor.*")) {
    Write-Host "present: node $(& node --version)"
} else {
    $index = Invoke-RestMethod 'https://nodejs.org/dist/index.json'
    $version = ($index | Where-Object { $_.version -like "v$nodeMajor.*" } | Select-Object -First 1).version
    $msiName = "node-$version-x64.msi"
    $msi = Get-File "https://nodejs.org/dist/$version/$msiName" $msiName
    $sums = (Get-Text "https://nodejs.org/dist/$version/SHASUMS256.txt")
    Assert-Sha256 $msi (($sums -split "`n" | Where-Object { $_ -match "\s$([regex]::Escape($msiName))$" }) -split '\s+')[0]
    Invoke-Native 'msiexec.exe' @('/i', "`"$msi`"", '/qn', '/norestart') | Out-Null
    Update-SessionPath
}

Step 'MKVToolNix (mkvmerge, mkvinfo and mkvpropedit for the tests)'
$mkvDir = Join-Path $ToolsDir 'mkvtoolnix'
[xml]$mkvRelease = (Get-Text 'https://mkvtoolnix.download/latest-release.xml')
$mkvVersion = $mkvRelease.'mkvtoolnix-releases'.'latest-source'.version
$mkvprop = Join-Path $mkvDir 'mkvpropedit.exe'
if ((Test-Path $mkvprop) -and ((& $mkvprop --version) -match "v$([regex]::Escape($mkvVersion))\b")) {
    Write-Host "present: $(& $mkvprop --version)"
} else {
    $base = "https://mkvtoolnix.download/windows/releases/$mkvVersion"
    $zipName = "mkvtoolnix-64-bit-$mkvVersion.zip"
    $zip = Get-File "$base/$zipName" $zipName
    $sums = (Get-Text "$base/sha256sums.txt")
    Assert-Sha256 $zip (($sums -split "`n" | Where-Object { $_ -match "\s$([regex]::Escape($zipName))$" }) -split '\s+')[0]
    Expand-Into $zip $mkvDir
}
Add-PathEntry $mkvDir

if (-not $SkipDesktop) {
    Step 'Visual Studio Build Tools (MSVC and the Windows SDK, for Rust)'
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $vs = if (Test-Path $vswhere) {
        & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    }
    if ($vs) {
        Write-Host "present: $vs"
    } else {
        $bootstrapper = Get-File 'https://aka.ms/vs/17/release/vs_buildtools.exe' 'vs_buildtools.exe'
        Assert-Signed $bootstrapper
        Write-Host 'Installing (several GB; 10 to 30 minutes)...'
        $code = Invoke-Native $bootstrapper @('--quiet', '--wait', '--norestart', '--nocache',
            '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended') @(0, 3010) (Join-Path $work 'vs_buildtools.log')
        if ($code -eq 3010) { Write-Warning 'The Build Tools ask for a restart.' }
    }

    Step 'Rust (rustup, stable, MSVC)'
    $cargoBin = Join-Path $HOME '.cargo\bin'
    if (-not (Test-Path (Join-Path $cargoBin 'rustup.exe'))) {
        $base = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc'
        $init = Get-File "$base/rustup-init.exe" 'rustup-init.exe'
        Assert-Sha256 $init ((Get-Text "$base/rustup-init.exe.sha256") -split '\s+')[0]
        Invoke-Native $init @('-y', '--default-toolchain', 'stable', '--profile', 'minimal') | Out-Null
    }
    Update-SessionPath
    & rustup component add rustfmt clippy
    if ($LASTEXITCODE -ne 0) { throw 'rustup component add failed' }

    Step 'WebView2 runtime'
    $wv2 = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $wv2Version = (Get-ItemProperty "HKLM:\$wv2" -ErrorAction SilentlyContinue).pv
    if ($wv2Version) {
        Write-Host "present: $wv2Version"
    } else {
        $setup = Get-File 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' 'MicrosoftEdgeWebview2Setup.exe'
        Assert-Signed $setup
        Invoke-Native $setup @('/silent', '/install') | Out-Null
    }
}

if ($AuthorizedKey) {
    Step 'OpenSSH server'
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        try {
            $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
            Add-WindowsCapability -Online -Name $cap.Name | Out-Null
        } catch {
            # The Windows capability comes from Windows Update, which fails on an unpatched
            # install (0x800f0950). Microsoft's MSI works without it.
            Write-Host "The Windows capability failed ($($_.Exception.Message)); using the Win32-OpenSSH MSI."
            $msi = Get-GitHubAsset 'PowerShell/Win32-OpenSSH' '^OpenSSH-Win64-v[\d.]+\.msi$'
            Invoke-Native 'msiexec.exe' @('/i', "`"$($msi.File)`"", '/qn') | Out-Null
        }
    }
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd

    Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Profile Any | Out-Null
    Get-NetFirewallRule -Name 'ICMPv4-In-Reframe' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -Name 'ICMPv4-In-Reframe' -DisplayName 'ICMPv4 echo (Reframe testing)' `
        -Protocol ICMPv4 -IcmpType 8 -Direction Inbound -Action Allow -Profile Any | Out-Null

    # sshd reads an administrator's keys from ProgramData only, and only when the ACL allows
    # nobody but SYSTEM and Administrators.
    $adminKeys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    $existing = if (Test-Path $adminKeys) { @(Get-Content $adminKeys) } else { @() }
    if ($existing -notcontains $AuthorizedKey) { Add-Content -Path $adminKeys -Value $AuthorizedKey -Encoding ascii }
    icacls.exe $adminKeys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    $userKeys = Join-Path $HOME '.ssh\authorized_keys'
    New-Item -ItemType Directory -Force -Path (Split-Path $userKeys) | Out-Null
    $existing = if (Test-Path $userKeys) { @(Get-Content $userKeys) } else { @() }
    if ($existing -notcontains $AuthorizedKey) { Add-Content -Path $userKeys -Value $AuthorizedKey -Encoding ascii }

    New-Item -Force -Path 'HKLM:\SOFTWARE\OpenSSH' | Out-Null
    Set-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value (Join-Path $env:ProgramFiles 'Git\bin\bash.exe')

    # sshd builds a session's PATH from the machine value only, so uv, cargo and npm's global
    # folder are added by a file that non-interactive Git Bash reads through BASH_ENV.
    $userDirs = @($uvDir, (Join-Path $HOME '.cargo\bin'), (Join-Path $env:APPDATA 'npm')) |
        ForEach-Object { '/' + $_.Substring(0, 1).ToLowerInvariant() + ($_.Substring(2) -replace '\\', '/') }
    $envFile = Join-Path $HOME '.reframe-ssh-env.sh'
    $joined = $userDirs -join ':'
    $body = "case `":`$PATH:`" in *`":$($userDirs[0]):`"*) ;; *) PATH=`"$joined`:`$PATH`" ;; esac`n"
    [IO.File]::WriteAllText($envFile, $body, (New-Object Text.UTF8Encoding $false))
    Set-ItemProperty 'HKCU:\Environment' -Name BASH_ENV -Value ($envFile -replace '\\', '/')
    $bashrc = Join-Path $HOME '.bashrc'
    $source = '. ~/.reframe-ssh-env.sh'
    if (-not ((Test-Path $bashrc) -and (@(Get-Content $bashrc) -contains $source))) {
        [IO.File]::AppendAllText($bashrc, "$source`n", (New-Object Text.UTF8Encoding $false))
    }
}

if ($NoSleep) {
    Step 'Sleep, hibernation and the display timeout off on mains power'
    powercfg.exe /change standby-timeout-ac 0
    powercfg.exe /change hibernate-timeout-ac 0
    powercfg.exe /change monitor-timeout-ac 0
}

if ($RepoDir) {
    Step "Repository in $RepoDir"
    if (-not (Test-Path $RepoDir)) {
        if (-not $RepoUrl) { throw "$RepoDir does not exist; pass -RepoUrl to clone it" }
        $cloneArgs = @('clone', $RepoUrl, $RepoDir)
        if ($Branch) { $cloneArgs += @('--branch', $Branch) }
        & $gitExe @cloneArgs
        if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }
    }
    Push-Location $RepoDir
    try {
        & uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
        & uv run reframe tools fetch
        if ($LASTEXITCODE -ne 0) { throw 'reframe tools fetch failed' }
        Push-Location frontend
        try {
            & npm ci
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        } finally { Pop-Location }
    } finally { Pop-Location }
}

Step 'Installed'
Update-SessionPath
# Windows PowerShell turns a native tool's stderr into errors when it is redirected.
$ErrorActionPreference = 'Continue'
foreach ($cmd in @('git --version', 'uv --version', "uv python find $pythonVersion", 'node --version',
        'npm --version', 'rustc --version', 'cargo --version', 'mkvpropedit --version')) {
    $parts = $cmd -split ' '
    $exe = $parts[0]
    $rest = @($parts | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $out = (& $exe @rest 2>&1 | Out-String).Trim() -replace '\s*\r?\n\s*', ' | '
        Write-Host ("{0,-28} {1}" -f $cmd, $out)
    } else {
        Write-Host ("{0,-28} (not installed)" -f $cmd)
    }
}
$build = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$release = if ($build.DisplayVersion) { $build.DisplayVersion } else { $build.ReleaseId }
Write-Host ("Windows {0} {1} build {2}.{3}" -f $build.ProductName, $release, $build.CurrentBuild, $build.UBR)
if ($AuthorizedKey) { Write-Host 'New SSH sessions use Git Bash; restart sshd if PATH changes do not show up.' }
