//
//  DocumentCorrector.swift
//
//  写真の中から紙の四隅を探し、傾きと台形のゆがみを直す。
//  Vision と Core Image だけを使い、画像を外部へ送らない。
//

import CoreImage
import UIKit
import Vision

enum DocumentCorrector {
    /// 書類らしい領域を探して台形補正する。見つからない場合は元の画像を返す。
    static func correct(_ image: CGImage, context: CIContext, minimumArea: CGFloat) -> CGImage {
        if let document = documentRectangle(in: image), area(of: document) >= minimumArea {
            return correct(image, rectangle: document, context: context)
        }

        if let rectangle = fallbackRectangle(in: image), area(of: rectangle) >= 0.3 {
            return correct(image, rectangle: rectangle, context: context)
        }

        return image
    }

    /// 短い辺が最大 shortSide になるよう縮小し、JPEG の Base64 文字列へ変換する。
    static func jpegBase64(
        _ image: CGImage,
        shortSide: CGFloat = 800,
        quality: CGFloat = 0.7
    ) -> String? {
        let sourceWidth = CGFloat(image.width)
        let sourceHeight = CGFloat(image.height)
        guard sourceWidth > 0, sourceHeight > 0, shortSide > 0 else { return nil }

        let scale = min(1, shortSide / min(sourceWidth, sourceHeight))
        let output: CGImage
        if scale < 1 {
            let width = max(1, Int((sourceWidth * scale).rounded()))
            let height = max(1, Int((sourceHeight * scale).rounded()))
            guard let bitmap = CGContext(
                data: nil,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { return nil }
            bitmap.interpolationQuality = .high
            bitmap.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            guard let resized = bitmap.makeImage() else { return nil }
            output = resized
        } else {
            output = image
        }

        return UIImage(cgImage: output)
            .jpegData(compressionQuality: min(max(quality, 0), 1))?
            .base64EncodedString()
    }

    /// iOS 標準の書類領域検出。四隅は画像全体を 1 とする左下原点の座標で返る。
    private static func documentRectangle(in image: CGImage) -> VNRectangleObservation? {
        let request = VNDetectDocumentSegmentationRequest()
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            return nil
        }
        return request.results?.first
    }

    /// 書類領域を見つけられない場合は、従来の四角形検出を同じ設定で試す。
    private static func fallbackRectangle(in image: CGImage) -> VNRectangleObservation? {
        let request = VNDetectRectanglesRequest()
        request.maximumObservations = 4
        request.minimumConfidence = 0.6
        request.minimumAspectRatio = 0.3
        request.maximumAspectRatio = 1.0
        request.minimumSize = 0.4
        request.quadratureTolerance = 25

        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            return nil
        }
        return (request.results ?? []).max { area(of: $0) < area(of: $1) }
    }

    private static func correct(
        _ image: CGImage,
        rectangle: VNRectangleObservation,
        context: CIContext
    ) -> CGImage {
        let width = CGFloat(image.width)
        let height = CGFloat(image.height)
        let corners = [rectangle.topLeft, rectangle.topRight, rectangle.bottomRight, rectangle.bottomLeft]
        let center = CGPoint(
            x: corners.map(\.x).reduce(0, +) / 4,
            y: corners.map(\.y).reduce(0, +) / 4
        )

        // 見出しなどを紙の端と一緒に切らないよう、四隅を中心から 6% 外へ広げる。
        func pixel(_ point: CGPoint) -> CIVector {
            let margin: CGFloat = 0.06
            let x = min(max(point.x + (point.x - center.x) * margin, 0), 1) * width
            let y = min(max(point.y + (point.y - center.y) * margin, 0), 1) * height
            return CIVector(x: x, y: y)
        }

        let corrected = CIImage(cgImage: image).applyingFilter("CIPerspectiveCorrection", parameters: [
            "inputTopLeft": pixel(rectangle.topLeft),
            "inputTopRight": pixel(rectangle.topRight),
            "inputBottomRight": pixel(rectangle.bottomRight),
            "inputBottomLeft": pixel(rectangle.bottomLeft)
        ])
        guard corrected.extent.width > 100, corrected.extent.height > 100,
              let output = context.createCGImage(corrected, from: corrected.extent) else {
            return image
        }
        return output
    }

    /// 四角形の面積（画像全体を 1 とした割合）。
    private static func area(of rectangle: VNRectangleObservation) -> CGFloat {
        let points = [rectangle.topLeft, rectangle.topRight, rectangle.bottomRight, rectangle.bottomLeft]
        var sum: CGFloat = 0
        for index in 0..<points.count {
            let first = points[index]
            let second = points[(index + 1) % points.count]
            sum += first.x * second.y - second.x * first.y
        }
        return abs(sum) / 2
    }
}
