param(
    [string]$Sdk = $env:ANDROID_HOME,
    [string]$BuildTools,
    [string]$AndroidJar
)
$ErrorActionPreference = 'Stop'
if (!$BuildTools) {
    if (!$Sdk) { throw 'Set ANDROID_HOME to the Android SDK directory.' }
    $BuildTools = Join-Path $Sdk 'build-tools/34.0.0'
}
if (!$AndroidJar) { $AndroidJar = Join-Path $Sdk 'platforms/android-34/android.jar' }
function Run($File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed (exit $LASTEXITCODE)" }
}
$out = Join-Path $PSScriptRoot 'build'
$classes = Join-Path $out 'classes'
New-Item -ItemType Directory -Force $out,$classes | Out-Null
$resources = Join-Path $out 'resources.zip'
$base = Join-Path $out 'base.apk'
$aligned = Join-Path $out 'aligned.apk'
$apk = Join-Path $out 'Kitchen.apk'
$keystore = Join-Path $out 'debug.keystore'
Run "$BuildTools/aapt2.exe" @('compile','--dir',"$PSScriptRoot/res",'-o',$resources)
Run "$BuildTools/aapt2.exe" @('link','-I',$AndroidJar,'--manifest',"$PSScriptRoot/AndroidManifest.xml",'-A',"$PSScriptRoot/app/src/main/assets",'-o',$base,$resources)
$sources = @(Get-ChildItem -LiteralPath "$PSScriptRoot/app/src/main/java" -Recurse -Filter '*.java' | ForEach-Object FullName)
# Use JDK 17 on PATH with Build Tools 34.0.0. Its D8 fails on some JDK 21 class files.
Run javac (@('-g','-encoding','UTF-8','--release','8','-classpath',$AndroidJar,'-d',$classes) + $sources)
$program = Join-Path $out 'program.jar'
Run jar @('cf',$program,'-C',$classes,'.')
Run java @('-cp',"$BuildTools/lib/d8.jar",'com.android.tools.r8.D8','--lib',$AndroidJar,'--min-api','23','--output',$out,$program)
Push-Location $out
try { Run jar @('uf',$base,'classes.dex') } finally { Pop-Location }
Run "$BuildTools/zipalign.exe" @('-f','4',$base,$aligned)
if (!(Test-Path -LiteralPath $keystore)) {
    Run keytool @('-genkeypair','-keystore',$keystore,'-storepass','android','-keypass','android','-alias','androiddebugkey','-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=Android Debug')
}
Run java @('-jar',"$BuildTools/lib/apksigner.jar",'sign','--ks',$keystore,'--ks-pass','pass:android','--out',$apk,$aligned)
Run java @('-jar',"$BuildTools/lib/apksigner.jar",'verify',$apk)
Write-Output $apk


