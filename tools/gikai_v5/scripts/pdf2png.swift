import Foundation
import PDFKit
import AppKit
let args = CommandLine.arguments
let doc = PDFDocument(url: URL(fileURLWithPath: args[1]))!
let scale = CGFloat(Double(args[3]) ?? 2.0)
print("pages:", doc.pageCount)
for i in 0..<doc.pageCount {
  let p = doc.page(at: i)!
  let r = p.bounds(for: .mediaBox)
  let w = Int(r.width*scale), h = Int(r.height*scale)
  let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
  NSGraphicsContext.saveGraphicsState()
  let ctx = NSGraphicsContext(bitmapImageRep: rep)!
  NSGraphicsContext.current = ctx
  ctx.cgContext.setFillColor(NSColor.white.cgColor); ctx.cgContext.fill(CGRect(x:0,y:0,width:w,height:h))
  ctx.cgContext.scaleBy(x: scale, y: scale)
  p.draw(with: .mediaBox, to: ctx.cgContext)
  NSGraphicsContext.restoreGraphicsState()
  try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(args[2])_p\(i+1).png"))
}
