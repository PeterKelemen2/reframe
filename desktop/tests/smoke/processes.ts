/**
 * The processes of this machine as the smoke test needs them: who started whom, which program
 * each one runs, and ways to close a process's window and to answer its file dialog as a user
 * does.
 */
import { execFile } from 'node:child_process'
import { readdir, readFile, readlink } from 'node:fs/promises'
import { join, relative, resolve, sep } from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)

export const WINDOWS = process.platform === 'win32'

export interface Proc {
  pid: number
  ppid: number
  /** With the pid, tells a process from a later one that got the same pid. */
  start: string
  name: string
  /** `null` when the system does not say (another user's process, a kernel thread). */
  exe: string | null
  commandLine: string
}

async function linuxProcesses(): Promise<Proc[]> {
  const pids = (await readdir('/proc')).filter((entry) => /^\d+$/.test(entry))
  const all = await Promise.all(
    pids.map(async (pid): Promise<Proc | null> => {
      try {
        const stat = await readFile(`/proc/${pid}/stat`, 'utf8')
        // The name is in parentheses and may itself hold spaces and parentheses.
        const close = stat.lastIndexOf(')')
        const fields = stat.slice(close + 2).split(' ')
        const exe = await readlink(`/proc/${pid}/exe`).catch(() => null)
        const cmdline = await readFile(`/proc/${pid}/cmdline`, 'utf8').catch(() => '')
        return {
          pid: Number(pid),
          ppid: Number(fields[1]),
          start: fields[19] ?? '',
          name: stat.slice(stat.indexOf('(') + 1, close),
          // A program replaced while it runs reads as "… (deleted)".
          exe: exe?.replace(/ \(deleted\)$/, '') ?? null,
          commandLine: cmdline.split('\0').join(' ').trim(),
        }
      } catch {
        return null // ended while it was read
      }
    }),
  )
  return all.filter((proc) => proc !== null)
}

const LIST_WINDOWS_PROCESSES = `
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Get-CimInstance Win32_Process | ForEach-Object {
  [pscustomobject]@{
    pid = [int]$_.ProcessId; ppid = [int]$_.ParentProcessId; name = $_.Name
    start = if ($_.CreationDate) { [string]$_.CreationDate.ToFileTimeUtc() } else { '' }
    exe = $_.ExecutablePath; commandLine = [string]$_.CommandLine
  }
} | ConvertTo-Json -Compress`

/** Runs a PowerShell script; encoded, so that no quote in it meets the command line's rules. */
async function powershell(script: string): Promise<string> {
  const encoded = Buffer.from(script, 'utf16le').toString('base64')
  const { stdout } = await run(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
    { maxBuffer: 64 * 1024 * 1024, windowsHide: true },
  )
  return stdout
}

async function windowsProcesses(): Promise<Proc[]> {
  return JSON.parse(await powershell(LIST_WINDOWS_PROCESSES)) as Proc[]
}

export function listProcesses(): Promise<Proc[]> {
  return WINDOWS ? windowsProcesses() : linuxProcesses()
}

/** Every process below `root` (not `root` itself), found through the parent pids. */
export function descendants(all: Proc[], root: number): Proc[] {
  const found: Proc[] = []
  const parents = new Set([root])
  let grew = true
  while (grew) {
    grew = false
    for (const proc of all) {
      if (!parents.has(proc.pid) && parents.has(proc.ppid)) {
        parents.add(proc.pid)
        found.push(proc)
        grew = true
      }
    }
  }
  return found
}

export function sameProcess(a: Proc, b: Proc): boolean {
  return a.pid === b.pid && a.start === b.start
}

function samePath(a: string, b: string): boolean {
  return WINDOWS ? a.toLowerCase() === b.toLowerCase() : a === b
}

export function isInside(path: string, folder: string): boolean {
  const rel = relative(resolve(folder), resolve(path))
  const inside = rel !== '' && !rel.startsWith(`..${sep}`) && rel !== '..'
  return inside || samePath(resolve(path), resolve(folder))
}

/** A program's file name without `.exe`, in lower case on Windows. */
export function programName(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? ''
  return WINDOWS ? base.toLowerCase().replace(/\.exe$/, '') : base
}

export function procName(proc: Proc): string {
  return programName(proc.exe ?? proc.name)
}

const CLOSE_WINDOWS_WINDOWS = `
$ErrorActionPreference = 'Stop'
Add-Type -Namespace Smoke -Name User32 -MemberDefinition @'
public delegate bool EnumProc(System.IntPtr hwnd, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool EnumWindows(EnumProc callback, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern uint GetWindowThreadProcessId(System.IntPtr hwnd, out uint pid);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool IsWindowVisible(System.IntPtr hwnd);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool PostMessage(System.IntPtr hwnd, uint msg, System.IntPtr w, System.IntPtr l);
'@
$state = @{ target = [uint32]$args[0]; sent = 0 }
[Smoke.User32]::EnumWindows({
  param($hwnd, $l)
  $owner = [uint32]0
  [void][Smoke.User32]::GetWindowThreadProcessId($hwnd, [ref]$owner)
  if ($owner -eq $state.target -and [Smoke.User32]::IsWindowVisible($hwnd)) {
    # WM_CLOSE: what the title bar's close button sends.
    if ([Smoke.User32]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) { $state.sent++ }
  }
  return $true
}, [IntPtr]::Zero) | Out-Null
if ($state.sent -eq 0) { Write-Error "no visible window of process $($state.target)" }`

/**
 * Asks the visible windows of `pid` to close, as their close button does: `WM_CLOSE` on
 * Windows, `WM_DELETE_WINDOW` on X11. Rejects when the process has no such window.
 */
export async function closeWindows(pid: number): Promise<void> {
  if (WINDOWS) {
    await powershell(`& { ${CLOSE_WINDOWS_WINDOWS} } ${pid}`)
  } else {
    await run('python3', [join(import.meta.dirname, 'close-window.py'), String(pid)])
  }
}

// The common file dialog's controls: the file name box (1148) and the Open button (1). The
// box is a combo box whose edit has the same id; on some Windows versions only the edit takes
// a value, so the first control with the id and the pattern is used.
const CHOOSE_FILE_WINDOWS = `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$target = [int]$args[0]
$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[1]))
$deadline = (Get-Date).AddSeconds(30)
$root = [Windows.Automation.AutomationElement]::RootElement
$dialog = $null
while (-not $dialog) {
  if ((Get-Date) -gt $deadline) { Write-Error "no file dialog of process $target" }
  $owned = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::ProcessIdProperty, $target)
  $class = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::ClassNameProperty, '#32770')
  $both = New-Object Windows.Automation.AndCondition($owned, $class)
  $dialog = $root.FindFirst([Windows.Automation.TreeScope]::Descendants, $both)
  if (-not $dialog) { Start-Sleep -Milliseconds 250 }
}
function Pattern($id, $pattern) {
  $condition = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
  while ($true) {
    foreach ($element in $dialog.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)) {
      $found = $null
      if ($element.TryGetCurrentPattern($pattern, [ref]$found)) { return $found }
    }
    if ((Get-Date) -gt $deadline) { Write-Error "no control $id of the file dialog takes the input" }
    Start-Sleep -Milliseconds 250
  }
}
(Pattern '1148' ([Windows.Automation.ValuePattern]::Pattern)).SetValue($path)
(Pattern '1' ([Windows.Automation.InvokePattern]::Pattern)).Invoke()`

/**
 * Chooses `path` in the file dialog that `pid` opens, as a user who types the path: GTK's
 * location entry on X11, the file name box on Windows. Rejects when no dialog opens.
 */
export async function chooseFile(pid: number, path: string): Promise<void> {
  if (WINDOWS) {
    const encoded = Buffer.from(path, 'utf8').toString('base64')
    await powershell(`& { ${CHOOSE_FILE_WINDOWS} } ${pid} ${encoded}`)
  } else {
    await run('python3', [join(import.meta.dirname, 'choose-file.py'), String(pid), path])
  }
}

/** Ends `procs` at once (the test's own clean-up, never one of its checks). */
export async function kill(procs: Proc[]): Promise<void> {
  const all = await listProcesses()
  const alive = procs.filter((proc) => all.some((other) => sameProcess(proc, other)))
  if (WINDOWS) {
    if (alive.length === 0) return
    const pids = alive.flatMap((proc) => ['/PID', String(proc.pid)])
    await run('taskkill.exe', ['/F', ...pids], { windowsHide: true }).catch(() => undefined)
    return
  }
  for (const proc of alive) {
    try {
      process.kill(proc.pid, 'SIGKILL')
    } catch {
      // already gone
    }
  }
}
