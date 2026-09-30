$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$testAudioPath = Join-Path $PSScriptRoot 'inputs\codex-test.wav'
$testSynthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $testSynthesizer.SelectVoice('Microsoft Zira Desktop')
    $testSynthesizer.Rate = 0
    $testSynthesizer.SetOutputToWaveFile($testAudioPath)
    $testSynthesizer.Speak('The test number is seven.')
} finally {
    $testSynthesizer.Dispose()
}
Get-Item -LiteralPath $testAudioPath | Select-Object FullName,Length
