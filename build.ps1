# Build FlowDictate.exe (PyInstaller onedir) and bundle CUDA DLLs.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$sp = Join-Path $venv "Lib\site-packages"

Set-Location $root
& "$venv\Scripts\pyinstaller.exe" --noconfirm --clean --noconsole `
    --name FlowDictate `
    --collect-all faster_whisper `
    --collect-all sounddevice `
    "$root\flowdictate.py"

# cuBLAS/cuDNN from pip wheels -> flat into _internal (on the DLL search path)
$internal = Join-Path $root "dist\FlowDictate\_internal"
foreach ($pkg in @("cublas", "cudnn")) {
    $bin = Join-Path $sp "nvidia\$pkg\bin"
    if (Test-Path $bin) {
        Copy-Item (Join-Path $bin "*.dll") $internal -Force
        Write-Host "Bundled $pkg DLLs"
    }
}

Copy-Item (Join-Path $root "README.md") (Join-Path $root "dist\FlowDictate\") -Force
Write-Host "Build done: dist\FlowDictate\FlowDictate.exe"
