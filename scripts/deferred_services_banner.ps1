param(
    [string]$DelaySeconds = "35"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Decode-Utf8Base64([string]$Value) {
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($Value))
}

function Write-Line([string]$Text) {
    [Console]::WriteLine($Text)
}

function Write-DecodedLine([string]$Base64Value) {
    Write-Line (Decode-Utf8Base64 $Base64Value)
}

function Write-DecodedFormattedLine([string]$Base64Value, [string]$Arg0) {
    $template = Decode-Utf8Base64 $Base64Value
    Write-Line ($template -f $Arg0)
}

Write-Line ""
Write-Line "=============================================================================="
Write-DecodedLine "0J7RgtC70L7QttC10L3QvdGL0Lkg0LfQsNC/0YPRgdC6INGC0Y/QttGR0LvRi9GFINGB0LXRgNCy0LjRgdC+0LIgTmlja2VsZnJvbnQ="
Write-Line "=============================================================================="
Write-DecodedFormattedLine "V29ya2Vycy9GbG93ZXIg0LHRg9C00YPRgiDQt9Cw0L/Rg9GJ0LXQvdGLINGH0LXRgNC10LcgezB9INGB0LXQui4=" $DelaySeconds
Write-DecodedLine "QmFja2VuZCDQuCBmcm9udGVuZCDRg9C20LUg0LzQvtCz0YPRgiDRgdGC0LDRgNGC0L7QstCw0YLRjCDRgNCw0L3RjNGI0LUu"
Write-Line "=============================================================================="
Write-Line ""
