<#
  Build FRIDAY into a single hidden exe, drop it on the Desktop, and register it
  to auto-start on login (invisible until you clap + say the wake phrase).

  Run from the FINESSE project root, in the 3.12 venv:
      .\.venv\Scripts\Activate.ps1
      pip install -r voice\requirements-voice.txt
      .\voice\build_exe.ps1

  Flags:
      -NoAutostart     build + copy to Desktop, but don't register login startup
      -Registry        use HKCU\...\Run instead of a Startup-folder shortcut
#>
param(
    [switch]$NoAutostart,
    [switch]$Registry
)

$ErrorActionPreference = "Stop"
$root      = Split-Path -Parent $PSScriptRoot          # ...\FINESSE
$voiceDir  = $PSScriptRoot
$entry     = Join-Path $voiceDir "friday.py"
$distDir   = Join-Path $root "dist"
$exeOut    = Join-Path $distDir "FRIDAY.exe"
$desktop   = [Environment]::GetFolderPath("Desktop")
$desktopExe = Join-Path $desktop "FRIDAY.exe"

Write-Host "== Building FRIDAY ==" -ForegroundColor Cyan
Write-Host "  python : $((Get-Command python).Source)"

# 1) config next to the exe (edit friday.json on the Desktop later to change voice/creds)
$cfgSrc = Join-Path $voiceDir "config.example.json"
$cfgDst = Join-Path $voiceDir "friday.json"
if (-not (Test-Path $cfgDst)) { Copy-Item $cfgSrc $cfgDst; Write-Host "  wrote voice\friday.json (edit me)" }

# 2) PyInstaller: onefile + noconsole (hidden). Pull in the tricky native/data deps.
python -m PyInstaller `
    --onefile --noconsole --clean --noconfirm `
    --name FRIDAY `
    --distpath $distDir `
    --workpath (Join-Path $root "build") `
    --specpath (Join-Path $root "build") `
    --collect-all faster_whisper `
    --collect-all edge_tts `
    --collect-all sounddevice `
    --collect-submodules comtypes `
    --hidden-import pyttsx3.drivers `
    --hidden-import pyttsx3.drivers.sapi5 `
    --hidden-import win32com.client `
    $entry
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

# 3) place exe + its config on the Desktop
Copy-Item $exeOut $desktopExe -Force
Copy-Item $cfgDst (Join-Path $desktop "friday.json") -Force
Write-Host "  placed FRIDAY.exe + friday.json on the Desktop" -ForegroundColor Green

# 4) auto-start on login
if (-not $NoAutostart) {
    if ($Registry) {
        $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        Set-ItemProperty -Path $runKey -Name "SASTRAVA_FRIDAY" -Value "`"$desktopExe`""
        Write-Host "  registered HKCU\...\Run\SASTRAVA_FRIDAY" -ForegroundColor Green
    } else {
        $startup = [Environment]::GetFolderPath("Startup")
        $lnk = Join-Path $startup "FRIDAY.lnk"
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($lnk)
        $sc.TargetPath = $desktopExe
        $sc.WorkingDirectory = $desktop
        $sc.WindowStyle = 7            # minimized/hidden
        $sc.Description = "SASTRAVA FRIDAY voice assistant"
        $sc.Save()
        Write-Host "  created Startup shortcut: $lnk" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Done. FRIDAY will boot on next login and sit silent." -ForegroundColor Cyan
Write-Host "Wake it any time:  clap, clap  ->  `"fire up baby daddy's home`"" -ForegroundColor Yellow
Write-Host "Logs: %APPDATA%\SASTRAVA_FRIDAY\friday.log"
Write-Host "To remove autostart: delete the Startup shortcut (shell:startup) or the Run key."
