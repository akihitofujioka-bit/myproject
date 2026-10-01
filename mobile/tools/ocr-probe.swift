//
//  ocr-probe.swift — レシート・手帳の画像を、iPhone アプリと同じ方法（Vision）で文字認識して JSON で出す。
//
//  使い方:
//    swiftc -O -o /tmp/ocr-probe mobile/tools/ocr-probe.swift
//    /tmp/ocr-probe 画像.jpg > 認識結果.json
//    MIN_H=0.006 /tmp/ocr-probe 手帳.jpg > 認識結果.json   # 手帳を撮ったときと同じ（小さな文字も拾う）
//
//  出力は ReceiptScanner プラグインが JS に渡すものと同じ形:
//    { "lines": [ { "text", "confidence", "x", "y", "width", "height" }, ... ], "orientation": ... }
//  実物の写真を通せば、apps/shared/ の読み取り規則を、アプリを作り直さずに検証できる。
//  処理はすべてこの Mac の中で完結し、画像を外部へ送ることはない。
//
//  文字の向きはアプリ（ReceiptScannerPlugin.pickOrientation）と同じ方法で自動で見分ける。
//  画像の読み込みは NSImage ではなく CGImageSource を使う（iCloud Drive 上の HEIC を
//  NSImage で開くと、応答が返らず止まることがあった。2026-10-01）。
//
import Foundation
import Vision
import ImageIO
import CoreGraphics

let args = CommandLine.arguments
guard args.count >= 2,
      let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[1]) as CFURL, nil),
      let cg = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    FileHandle.standardError.write("使い方: ocr-probe <画像ファイル>\n".data(using: .utf8)!)
    exit(1)
}
// 写真に記録された向き（EXIF）。アプリでは撮った画像がすでに正しい向きなので .up にあたる
let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
let exif = (props?[kCGImagePropertyOrientation] as? UInt32).flatMap { CGImagePropertyOrientation(rawValue: $0) } ?? .up
let minHeight = ProcessInfo.processInfo.environment["MIN_H"].flatMap { Float($0) }

// ---- ここから ReceiptScannerPlugin.swift と同じ処理 ----

func makeRequest(minimumTextHeight: Float?, correction: Bool) -> VNRecognizeTextRequest {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ja-JP", "en-US"]
    request.usesLanguageCorrection = correction
    if let h = minimumTextHeight { request.minimumTextHeight = h }
    return request
}

func shrink(_ image: CGImage, maxSide: Int) -> CGImage {
    let scale = Double(maxSide) / Double(max(image.width, image.height))
    if scale >= 1 { return image }
    let w = Int(Double(image.width) * scale), h = Int(Double(image.height) * scale)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return image }
    ctx.interpolationQuality = .medium
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage() ?? image
}

/// 読む向きの候補を決める。
/// 縮小画像を軽く読み、文字のかたまりの多くが横長なら、文字はまっすぐ写っているので撮ったままの向きだけ。
/// 縦長が多ければ横倒しに写っているので、右に回した向きと左に回した向きの両方を候補にする。
/// （どちらが正しい向きかは文字の量では見分けられない。日本語は縦書きも読めるため、
///   横倒し・逆さでも同じくらい文字が取れてしまう。正しい向きは JS 側が中身の意味で選ぶ）
func candidateOrientations(_ image: CGImage, base: CGImagePropertyOrientation) -> [CGImagePropertyOrientation] {
    let small = shrink(image, maxSide: 1600)
    let req = makeRequest(minimumTextHeight: 0.01, correction: false)
    try? VNImageRequestHandler(cgImage: small, orientation: base, options: [:]).perform([req])
    var wide = 0, tall = 0
    for obs in req.results ?? [] {
        guard let best = obs.topCandidates(1).first, best.string.count >= 2 else { continue }
        if obs.boundingBox.width > obs.boundingBox.height { wide += 1 } else { tall += 1 }
    }
    // 縦長が横長の1.5倍を超えるときだけ横倒しとみなす（縦書きの書類を誤って回さないよう慎重に）
    if tall > 3 && Double(tall) > Double(wide) * 1.5 { return rotations(of: base) }
    return [base]
}

/// 画像を右に90度・左に90度回したときの向き
func rotations(of o: CGImagePropertyOrientation) -> [CGImagePropertyOrientation] {
    switch o {
    case .up: return [.right, .left]
    case .right: return [.down, .up]
    case .left: return [.up, .down]
    case .down: return [.left, .right]
    default: return [.right, .left]
    }
}

// ---- ここまで ----

func recognizeLines(_ image: CGImage, orientation: CGImagePropertyOrientation) -> [[String: Any]] {
    let request = makeRequest(minimumTextHeight: minHeight, correction: true)
    try? VNImageRequestHandler(cgImage: image, orientation: orientation, options: [:]).perform([request])
    var lines: [[String: Any]] = []
    for obs in request.results ?? [] {
        guard let best = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        lines.append(["text": best.string, "confidence": Double(best.confidence),
                      "x": Double(b.minX), "y": Double(1 - b.maxY), "width": Double(b.width), "height": Double(b.height)])
    }
    return lines
}

let orientations = candidateOrientations(cg, base: exif)
let results = orientations.map { recognizeLines(cg, orientation: $0) }
let out: [String: Any] = ["width": cg.width, "height": cg.height,
                          "orientations": orientations.map { Int($0.rawValue) },
                          "lines": results[0], "alternates": Array(results.dropFirst())]
let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
