[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Decode-Utf8Base64([string]$Value) {
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($Value))
}

[Console]::WriteLine("")
[Console]::WriteLine((Decode-Utf8Base64 "0KLRj9C20ZHQu9GL0LUg0YHQtdGA0LLQuNGB0Ysg0LfQsNC/0YPRidC10L3Riy4g0K3RgtC+INCy0YHQv9C+0LzQvtCz0LDRgtC10LvRjNC90L7QtSDQvtC60L3QviDQt9Cw0LrRgNC+0LXRgtGB0Y8g0LDQstGC0L7QvNCw0YLQuNGH0LXRgdC60Lgu"))
[Console]::WriteLine("")
