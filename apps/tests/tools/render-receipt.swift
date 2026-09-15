//
//  render-receipt.swift — テスト用の模擬レシート画像を作る（macOS）。
//
//  使い方: swiftc -O -o /tmp/render-receipt apps/tests/tools/render-receipt.swift
//          /tmp/render-receipt 本文.txt 出力.png
//  本文の各行はそのまま1行として描く。タブ（\t）があれば、左側を左寄せ・右側を右寄せで描く。
//  「----」だけの行は罫線。実物に近づけるため、少しだけ傾きと粗さを加えている。
//
import Foundation
import AppKit

let args = CommandLine.arguments
guard args.count >= 3, let body = try? String(contentsOfFile: args[1], encoding: .utf8) else {
    FileHandle.standardError.write("使い方: render-receipt <本文.txt> <出力.png>\n".data(using: .utf8)!); exit(1)
}
let lines = body.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
let W: CGFloat = 640, lineH: CGFloat = 40, pad: CGFloat = 36
let H: CGFloat = pad * 2 + lineH * CGFloat(lines.count)
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W), pixelsHigh: Int(H), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSColor(white: 0.97, alpha: 1).setFill(); NSRect(x: 0, y: 0, width: W, height: H).fill()
let font = NSFont(name: "HiraKakuProN-W3", size: 24) ?? NSFont.systemFont(ofSize: 24)
let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor(white: 0.12, alpha: 1)]
// レシートらしく、ごくわずかに傾ける
let t = NSAffineTransform(); t.translateX(by: 6, yBy: 0); t.rotate(byDegrees: 0.4); t.concat()
for (i, raw) in lines.enumerated() {
    let y = H - pad - lineH * CGFloat(i + 1)
    if raw.trimmingCharacters(in: .whitespaces).hasPrefix("----") {
        NSColor(white: 0.5, alpha: 1).setStroke()
        let p = NSBezierPath(); p.move(to: NSPoint(x: pad, y: y + 14)); p.line(to: NSPoint(x: W - pad, y: y + 14)); p.lineWidth = 1; p.stroke()
        continue
    }
    let cols = raw.components(separatedBy: "\t")
    let left = NSAttributedString(string: cols[0], attributes: attrs)
    left.draw(at: NSPoint(x: pad, y: y))
    if cols.count > 1 {
        let right = NSAttributedString(string: cols[1], attributes: attrs)
        right.draw(at: NSPoint(x: W - pad - right.size().width, y: y))
    }
}
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
print("wrote \(args[2]) (\(Int(W))x\(Int(H)))")
