$ErrorActionPreference = "Stop"
$OutputDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppFile = Join-Path $OutputDir "Javis.pyw"

if (-not (Test-Path -LiteralPath $AppFile)) {
    throw "Não encontrei a interface do Javis: $AppFile"
}

$Pythonw = "C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if (-not (Test-Path -LiteralPath $Pythonw)) {
    $InstalledPythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($InstalledPythonw -and $InstalledPythonw.Source -notlike "*\WindowsApps\*") {
        $Pythonw = $InstalledPythonw.Source
    } else {
        throw "Não encontrei Python para abrir o Javis. Instale Python 3.11 ou superior e tente novamente."
    }
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Javis — Plano Bismarck.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '"' + $AppFile + '"'
$Shortcut.WorkingDirectory = $OutputDir
$Shortcut.Description = "Abrir o Javis local do Plano Bismarck"
$Shortcut.Save()

Write-Output "Atalho criado: $ShortcutPath"
