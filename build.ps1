# Build FlowDictate.exe (PyInstaller onedir).
#   .\build.ps1        -> GPU build (bundles cuBLAS/cuDNN, ~2 GB)
#   .\build.ps1 -Cpu   -> CPU-only build (no CUDA, ~300-400 MB)
param([switch]$Cpu)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$sp = Join-Path $venv "Lib\site-packages"

Set-Location $root
& "$venv\Scripts\pyinstaller.exe" --noconfirm --clean --noconsole `
    --name FlowDictate `
    --icon "$root\assets\app.ico" `
    --add-data "$root\assets;assets" `
    --collect-all faster_whisper `
    --collect-all sounddevice `
    --collect-all customtkinter `
    "$root\flowdictate.py"

$internal = Join-Path $root "dist\FlowDictate\_internal"
if (-not $Cpu) {
    # cuBLAS/cuDNN from pip wheels -> flat into _internal (on the DLL search path)
    foreach ($pkg in @("cublas", "cudnn")) {
        $bin = Join-Path $sp "nvidia\$pkg\bin"
        if (Test-Path $bin) {
            Copy-Item (Join-Path $bin "*.dll") $internal -Force
            Write-Host "Bundled $pkg DLLs"
        }
    }
} else {
    Write-Host "CPU-only build: CUDA DLLs skipped"
}

Copy-Item (Join-Path $root "README.md") (Join-Path $root "dist\FlowDictate\") -Force
Write-Host ("Build done ({0}): dist\FlowDictate\FlowDictate.exe" -f ($(if ($Cpu) {"CPU"} else {"GPU"})))
