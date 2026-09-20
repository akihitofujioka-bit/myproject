// 画像・PDF から文字を読み取る補助プログラム（macOS 標準の Vision を使う。端末内で完結し、外部送信はしない）
//
// 使い方:  nippo_ocr <ファイル>   → 標準出力に JSON {"text": "...", "confidence": 0.0〜1.0, "pages": n, "method": "ocr|pdftext"}
// ビルド:  nippo.py が初回に自動で swiftc を呼ぶ（手動なら build_ocr_helper.sh を参照）

import AppKit
import Foundation
import PDFKit
import Vision

struct RecognizedLine {
    let text: String
    let confidence: Float
    let box: CGRect
}

// Vision の認識結果を「上から下、左から右」の読み順に並べ直す
func sortedByReadingOrder(_ lines: [RecognizedLine]) -> [RecognizedLine] {
    let byTop = lines.sorted { $0.box.maxY > $1.box.maxY }
    var rows: [[RecognizedLine]] = []
    for line in byTop {
        if var last = rows.last, let ref = last.first {
            let tolerance = max(ref.box.height, line.box.height) * 0.5
            if abs(ref.box.midY - line.box.midY) < tolerance {
                last.append(line)
                rows[rows.count - 1] = last
                continue
            }
        }
        rows.append([line])
    }
    return rows.flatMap { $0.sorted { $0.box.minX < $1.box.minX } }
}

func recognize(cgImage: CGImage, orientation: CGImagePropertyOrientation) -> [RecognizedLine] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ja-JP", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cgImage, orientation: orientation, options: [:])
    do {
        try handler.perform([request])
    } catch {
        FileHandle.standardError.write("Vision の実行に失敗: \(error)\n".data(using: .utf8)!)
        return []
    }
    let lines = (request.results ?? []).compactMap { obs -> RecognizedLine? in
        guard let top = obs.topCandidates(1).first else { return nil }
        return RecognizedLine(text: top.string, confidence: top.confidence, box: obs.boundingBox)
    }
    return sortedByReadingOrder(lines)
}

func loadImage(url: URL) -> (CGImage, CGImagePropertyOrientation)? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
    var orientation = CGImagePropertyOrientation.up
    if let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
       let raw = props[kCGImagePropertyOrientation] as? UInt32,
       let o = CGImagePropertyOrientation(rawValue: raw) {
        orientation = o
    }
    return (image, orientation)
}

// PDF の1ページを画像にする（文字層がないスキャン PDF や手書き PDF 用）
func render(page: PDFPage) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let scale: CGFloat = min(3.0, 3000.0 / max(bounds.width, bounds.height))
    let size = NSSize(width: bounds.width * scale, height: bounds.height * scale)
    let image = page.thumbnail(of: size, for: .mediaBox)
    var rect = NSRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func emit(text: String, confidence: Float, pages: Int, method: String) {
    let payload: [String: Any] = ["text": text, "confidence": confidence, "pages": pages, "method": method]
    let data = try! JSONSerialization.data(withJSONObject: payload, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("使い方: nippo_ocr <画像または PDF>\n".data(using: .utf8)!)
    exit(2)
}
let url = URL(fileURLWithPath: args[1])

if url.pathExtension.lowercased() == "pdf" {
    guard let doc = PDFDocument(url: url) else {
        FileHandle.standardError.write("PDF を開けません: \(url.path)\n".data(using: .utf8)!)
        exit(1)
    }
    var texts: [String] = []
    var confidences: [Float] = []
    var usedOCR = false
    for i in 0..<doc.pageCount {
        guard let page = doc.page(at: i) else { continue }
        let embedded = (page.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if embedded.count >= 20 {
            texts.append(embedded)
            confidences.append(1.0)
        } else if let cg = render(page: page) {
            usedOCR = true
            let lines = recognize(cgImage: cg, orientation: .up)
            texts.append(lines.map { $0.text }.joined(separator: "\n"))
            confidences.append(contentsOf: lines.map { $0.confidence })
        }
    }
    let avg = confidences.isEmpty ? 0 : confidences.reduce(0, +) / Float(confidences.count)
    emit(text: texts.joined(separator: "\n\n"), confidence: avg, pages: doc.pageCount, method: usedOCR ? "ocr" : "pdftext")
} else {
    guard let (cg, orientation) = loadImage(url: url) else {
        FileHandle.standardError.write("画像を開けません: \(url.path)\n".data(using: .utf8)!)
        exit(1)
    }
    let lines = recognize(cgImage: cg, orientation: orientation)
    let avg = lines.isEmpty ? 0 : lines.map { $0.confidence }.reduce(0, +) / Float(lines.count)
    emit(text: lines.map { $0.text }.joined(separator: "\n"), confidence: avg, pages: 1, method: "ocr")
}
