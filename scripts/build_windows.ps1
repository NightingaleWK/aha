# Run only with an isolated, task-owned Windows Python environment.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$BuildRoot,
    [ValidateSet('Directory', 'OneFile')][string]$Stage = 'Directory',
    [switch]$DirectoryVerified,
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$BuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
if ($BuildRoot -eq $SourceRoot) {
    throw 'BuildRoot must be a separate task-owned directory.'
}
if ($Stage -eq 'OneFile' -and -not $DirectoryVerified) {
    throw 'Verify the Directory build on Windows first, then pass -DirectoryVerified.'
}
$Probe = @'
import json, platform, struct, sys
print(json.dumps({"windows": sys.platform == "win32", "bits": struct.calcsize("P") * 8,
                  "isolated": sys.prefix != sys.base_prefix,
                  "python": list(sys.version_info[:2]), "machine": platform.machine()}))
'@ | & $PythonExe -
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Python runtime.' }
$Runtime = $Probe | ConvertFrom-Json
if (-not $Runtime.windows -or $Runtime.bits -ne 64 -or -not $Runtime.isolated) {
    throw 'Use a 64-bit Windows Python venv. Linux output is not a Windows application.'
}
if ($Runtime.python[0] -ne 3 -or $Runtime.python[1] -lt 12) {
    throw 'Python 3.12 or newer is required.'
}
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
& $PythonExe -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
$LicenseDir = Join-Path $BuildRoot 'licenses'
& $PythonExe (Join-Path $PSScriptRoot 'collect_licenses.py') $LicenseDir
if ($LASTEXITCODE -ne 0) { throw 'Runtime/license collection failed.' }
$StageName = if ($Stage -eq 'Directory') { 'directory' } else { 'portable' }
$Dist = Join-Path $BuildRoot "release\$StageName"
$Work = Join-Path $BuildRoot "pyinstaller\$StageName"
$Spec = Join-Path $BuildRoot "spec\$StageName"
New-Item -ItemType Directory -Force -Path $Dist, $Work, $Spec | Out-Null
$BundleMode = if ($Stage -eq 'Directory') { '--onedir' } else { '--onefile' }
$BuildArgs = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', $BundleMode,
    '--name', 'aha', '--icon', (Join-Path $SourceRoot 'src\aha\web\mark.ico'),
    '--paths', (Join-Path $SourceRoot 'src'),
    '--collect-all', 'zstandard', '--copy-metadata', 'zstandard',
    '--add-data', ((Join-Path $SourceRoot 'src\aha\web') + ';aha/web'),
    '--add-data', ($LicenseDir + ';aha/licenses'),
    '--distpath', $Dist, '--workpath', $Work, '--specpath', $Spec,
    (Join-Path $SourceRoot 'scripts\launch.py')
)
& $PythonExe @BuildArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; inspect its diagnostics.' }
$Executable = if ($Stage -eq 'Directory') { Join-Path $Dist 'aha\aha.exe' } else { Join-Path $Dist 'aha.exe' }
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Executable was not produced.' }
$Hash = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "AHA_EXECUTABLE=$Executable"
Write-Output "AHA_SHA256=$Hash"
if ($Stage -eq 'Directory') {
    Write-Output 'Next: run this directory build with an isolated --data-dir, verify native behavior, then build OneFile.'
}
