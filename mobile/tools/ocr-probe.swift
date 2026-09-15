//
//  ocr-probe.swift — レシート画像を、iPhone アプリと同じ方法（Vision）で文字認識して JSON で出す。
//
//  使い方:
//    swiftc -O -o /tmp/ocr-probe mobile/tools/ocr-probe.swift
//    /tmp/ocr-probe レシート.jpg > 認識結果.json
//
//  出力は ReceiptScanner プラグインが JS に渡すものと同じ形:
//    { "lines": [ { "text", "confidence", "x", "y", "width", "height" }, ... ] }
//  実物のレシート写真を通せば、apps/shared/receipt.js の抽出規則をアプリを作り直さずに検証できる。
//  処理はすべてこの Mac の中で完結し、画像を外部へ送ることはない。
//
import Foundation
import AppKit
import Vision

let args = CommandLine.arguments
guard args.count >= 2, let image = NSImage(contentsOfFile: args[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("使い方: ocr-probe <画像ファイル>\n".data(using: .utf8)!)
    exit(1)
}

var lines: [[String: Any]] = []
let request = VNRecognizeTextRequest { req, err in
    if let err = err { FileHandle.standardError.write("認識エラー: \(err)\n".data(using: .utf8)!); exit(2) }
    for obs in (req.results as? [VNRecognizedTextObservation]) ?? [] {
        guard let best = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        lines.append(["text": best.string, "confidence": Double(best.confidence),
                      "x": Double(b.minX), "y": Double(1 - b.maxY), "width": Double(b.width), "height": Double(b.height)])
    }
}
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ja-JP", "en-US"]
request.usesLanguageCorrection = true
try! VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])

let out: [String: Any] = ["width": cg.width, "height": cg.height, "lines": lines]
let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
