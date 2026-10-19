$ErrorActionPreference = "Stop"
$OutputDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppFile = Join-Path $OutputDir "Javis.pyw"
$BundledPythonw = "C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"

if (-not (Test-Path -LiteralPath $AppFile)) {
    throw "Não encontrei o arquivo da interface do Javis: $AppFile"
}

$Pythonw = $null
if (Test-Path -LiteralPath $BundledPythonw) {
    $Pythonw = $BundledPythonw
} else {
    $InstalledPythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($InstalledPythonw -and $InstalledPythonw.Source -notlike "*\WindowsApps\*") {
        $Pythonw = $InstalledPythonw.Source
    }
}

if (-not $Pythonw) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "O Python não foi encontrado. Instale Python 3.11 ou superior uma vez e depois abra o Javis pelo atalho.",
        "Javis — Plano Bismarck",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    exit 1
}

Start-Process -FilePath $Pythonw -ArgumentList ('"{0}"' -f $AppFile) -WorkingDirectory $OutputDir
