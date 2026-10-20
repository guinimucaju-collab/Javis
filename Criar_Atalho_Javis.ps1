$ErrorActionPreference = "Stop"
$OutputDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppFile = Join-Path $OutputDir "Javis.pyw"

function Find-Pythonw {
    # Devolve o executável sem console + argumentos extras, ou $null.
    # 1) Caminho escolhido por você (variável de ambiente JAVIS_PYTHONW)
    if ($env:JAVIS_PYTHONW -and (Test-Path -LiteralPath $env:JAVIS_PYTHONW)) {
        return @{ Path = $env:JAVIS_PYTHONW; Args = @() }
    }
    # 2) Python Launcher oficial (pyw.exe), instalado junto com o Python
    $launcher = Get-Command pyw.exe -ErrorAction SilentlyContinue
    if ($launcher -and $launcher.Source -notlike "*\WindowsApps\*") {
        return @{ Path = $launcher.Source; Args = @("-3") }
    }
    # 3) pythonw.exe no PATH (ignora o atalho da Microsoft Store, que não executa scripts)
    $installed = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($installed -and $installed.Source -notlike "*\WindowsApps\*") {
        return @{ Path = $installed.Source; Args = @() }
    }
    # 4) Python embutido no runtime do Codex, se existir neste usuário
    $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
    if (Test-Path -LiteralPath $bundled) {
        return @{ Path = $bundled; Args = @() }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $AppFile)) {
    throw "Não encontrei a interface do Javis: $AppFile"
}

$Python = Find-Pythonw
if (-not $Python) {
    throw "Não encontrei o Python para abrir o Javis. Instale o Python 3.11 ou superior e execute este script de novo."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Javis — Plano Bismarck.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Python.Path
$Shortcut.Arguments = (@($Python.Args) + ('"{0}"' -f $AppFile)) -join " "
$Shortcut.WorkingDirectory = $OutputDir
$Shortcut.Description = "Abrir o Javis local do Plano Bismarck"
$Shortcut.Save()

Write-Output "Atalho criado: $ShortcutPath"
