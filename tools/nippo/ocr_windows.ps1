# Windows 標準の OCR で画像から文字を取り出す（nippo 用）
#
# Windows 10 / 11 に最初から入っている Windows.Media.Ocr を使う。
# 追加のインストールは要らない（役場のパソコンはネットにつながらないため、
# Tesseract のような外から入れるものは避けている）。
#
# macOS 版の ocr_helper.swift と同じ形の JSON を 1 行で返す:
#   {"text": "...", "confidence": 0.8, "pages": 1, "method": "windows-ocr"}
#
# 使い方:  powershell -NoProfile -ExecutionPolicy Bypass -File ocr_windows.ps1 "C:\path\image.jpg"
#
# 注意: Windows の OCR は 1 文字ごとの確からしさを返さないので、confidence は
#       0.8 の固定値にしている（Vision は実際の値を返す）。

param([Parameter(Mandatory = $true)][string]$ImagePath)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Result($text, $method) {
    $obj = [ordered]@{
        text       = $text
        confidence = 0.8
        pages      = 1
        method     = $method
    }
    Write-Output ($obj | ConvertTo-Json -Compress)
}

try {
    if (-not (Test-Path -LiteralPath $ImagePath)) {
        throw "ファイルが見つかりません: $ImagePath"
    }

    Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

    # WinRT の非同期処理を PowerShell で待つための下ごしらえ
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    function Await($WinRtTask, $ResultType) {
        $asTask  = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }

    # 必要な型を読み込む
    $null = [Windows.Storage.StorageFile,        Windows.Storage,        ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine,        Windows.Media.Ocr,      ContentType = WindowsRuntime]
    $null = [Windows.Globalization.Language,     Windows.Globalization,  ContentType = WindowsRuntime]

    # OCR の言語を決める。日本語を優先し、無ければ利用者の言語設定に従う
    $engine = $null
    try {
        $ja = New-Object Windows.Globalization.Language "ja"
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($ja)
    } catch { }
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    }
    if ($null -eq $engine) {
        throw "この Windows では OCR を使えません。設定 →「時刻と言語」→「言語」で日本語を追加してください"
    }

    # 画像を読み込む
    $full = (Resolve-Path -LiteralPath $ImagePath).Path
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    # 文字を読み取る
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    foreach ($line in $result.Lines) { $lines += $line.Text }
    Write-Result ($lines -join "`n") "windows-ocr"
}
catch {
    # 失敗しても JSON を返さず、標準エラーへ。Python 側が RuntimeError にする
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
