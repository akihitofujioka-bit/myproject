//
//  DocumentReaderPlugin.swift
//
//  Word・Excel・PDF から文字と表を取り出す Capacitor プラグイン。
//  ファイルは端末内だけで読み、選択・共有で作られたコピーは読み終えたら消す。
//
import Foundation
import UIKit
import ImageIO
import UniformTypeIdentifiers
import PDFKit
import Vision
import PhotosUI
import Capacitor

@objc(DocumentReaderPlugin)
public class DocumentReaderPlugin: CAPPlugin, CAPBridgedPlugin, UIDocumentPickerDelegate, PHPickerViewControllerDelegate, UIAdaptivePresentationControllerDelegate {
    public let identifier = "DocumentReaderPlugin"
    public let jsName = "DocumentReader"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "pick", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "pickImage", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "hasShared", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "takeShared", returnType: CAPPluginReturnPromise)
    ]

    private struct SharedFile {
        let url: URL
        let name: String
    }

    private static let sharedLock = NSLock()
    private static var sharedFile: SharedFile?
    private var pendingPick: CAPPluginCall?
    private var pendingImagePick: CAPPluginCall?

    /// SceneDelegate から共有ファイルを受け取り、アプリ専用の一時コピーとして覚える。
    static func receive(url: URL) {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }

        let suffix = url.pathExtension.isEmpty ? "" : "." + url.pathExtension
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent("shared-" + UUID().uuidString + suffix)
        do {
            try FileManager.default.moveItem(at: url, to: destination)
        } catch {
            // ファイル提供元が移動を許さない場合も、アプリ専用の一時コピーなら安全に読める。
            do {
                try FileManager.default.copyItem(at: url, to: destination)
            } catch {
                return
            }
        }

        sharedLock.lock()
        let previous = sharedFile
        sharedFile = SharedFile(url: destination, name: url.lastPathComponent)
        sharedLock.unlock()
        if let previous = previous {
            try? FileManager.default.removeItem(at: previous.url)
        }
    }

    @objc func pick(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard self.pendingPick == nil else {
                call.reject("すでにファイル選択画面を開いています")
                return
            }
            guard let docx = UTType("org.openxmlformats.wordprocessingml.document"),
                  let xlsx = UTType("org.openxmlformats.spreadsheetml.sheet") else {
                call.reject("ファイル選択画面を開けませんでした")
                return
            }
            let picker = UIDocumentPickerViewController(
                forOpeningContentTypes: [.pdf, docx, xlsx],
                asCopy: true
            )
            picker.delegate = self
            picker.allowsMultipleSelection = false
            guard let host = self.hostViewController(), host.presentedViewController == nil else {
                call.reject("ほかの画面が開いています。閉じてからもう一度お試しください")
                return
            }
            self.pendingPick = call
            host.present(picker, animated: true)
        }
    }

    @objc func hasShared(_ call: CAPPluginCall) {
        Self.sharedLock.lock()
        let shared = Self.sharedFile
        Self.sharedLock.unlock()
        call.resolve(["has": shared != nil, "name": shared?.name ?? ""])
    }

    @objc func pickImage(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard self.pendingImagePick == nil else {
                call.reject("すでに写真選択画面を開いています")
                return
            }
            guard let host = self.hostViewController(), host.presentedViewController == nil else {
                call.reject("ほかの画面が開いています。閉じてからもう一度お試しください")
                return
            }
            var configuration = PHPickerConfiguration(photoLibrary: .shared())
            configuration.selectionLimit = 1
            configuration.filter = .images
            let picker = PHPickerViewController(configuration: configuration)
            picker.delegate = self
            picker.presentationController?.delegate = self
            self.pendingImagePick = call
            host.present(picker, animated: true)
        }
    }

    public func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        guard let call = pendingImagePick else {
            picker.dismiss(animated: true)
            return
        }
        let withPhoto = call.getBool("withPhoto") == true
        pendingImagePick = nil
        picker.dismiss(animated: true)

        guard let result = results.first else {
            call.resolve(["cancelled": true])
            return
        }
        let provider = result.itemProvider
        let suggestedName = provider.suggestedName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let name = suggestedName?.isEmpty == false ? suggestedName! : "写真"
        guard provider.canLoadObject(ofClass: UIImage.self) else {
            call.reject("選んだ写真を読み込めませんでした")
            return
        }
        provider.loadObject(ofClass: UIImage.self) { object, error in
            guard error == nil, let image = object as? UIImage, let cgImage = image.cgImage else {
                call.reject("選んだ写真を読み込めませんでした")
                return
            }
            let orientation = Self.cgImageOrientation(from: image.imageOrientation)
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    if withPhoto {
                        let context = CIContext()
                        let upright = Self.uprightCGImage(cgImage, orientation: orientation, context: context)
                        let corrected = DocumentCorrector.correct(upright, context: context, minimumArea: 0.05)
                        let boxes = try Self.recognizeImageBoxes(corrected)
                        call.resolve([
                            "cancelled": false,
                            "name": name,
                            "boxes": boxes,
                            "photo": DocumentCorrector.jpegBase64(corrected) ?? ""
                        ])
                        return
                    }
                    let lines = try Self.recognizeImage(cgImage, orientation: orientation)
                    call.resolve([
                        "cancelled": false,
                        "name": name,
                        "text": lines.joined(separator: "\n"),
                        "ocr": true
                    ])
                } catch {
                    call.reject(error.localizedDescription)
                }
            }
        }
    }

    public func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        guard presentationController.presentedViewController is PHPickerViewController,
              let call = pendingImagePick else { return }
        pendingImagePick = nil
        call.resolve(["cancelled": true])
    }

    @objc func takeShared(_ call: CAPPluginCall) {
        Self.sharedLock.lock()
        let shared = Self.sharedFile
        Self.sharedFile = nil
        Self.sharedLock.unlock()
        guard let shared = shared else {
            call.resolve([:])
            return
        }
        read(url: shared.url, name: shared.name, call: call, removeAfterReading: true)
    }

    public func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        pendingPick?.resolve(["cancelled": true])
        pendingPick = nil
    }

    public func documentPicker(
        _ controller: UIDocumentPickerViewController,
        didPickDocumentsAt urls: [URL]
    ) {
        guard let call = pendingPick else { return }
        pendingPick = nil
        guard let url = urls.first else {
            call.resolve(["cancelled": true])
            return
        }
        read(url: url, name: url.lastPathComponent, call: call, removeAfterReading: true)
    }

    private func read(url: URL, name: String, call: CAPPluginCall, removeAfterReading: Bool) {
        DispatchQueue.global(qos: .userInitiated).async {
            let accessed = url.startAccessingSecurityScopedResource()
            defer {
                if accessed { url.stopAccessingSecurityScopedResource() }
                if removeAfterReading { try? FileManager.default.removeItem(at: url) }
            }
            do {
                let content = try DocumentText.read(url: url)
                var lines = content.lines
                var didOCR = false
                if content.needsOCR {
                    lines = try Self.recognizePDF(url: url)
                    didOCR = true
                }
                call.resolve([
                    "name": name,
                    "kind": content.kind,
                    "lines": lines,
                    "tables": content.tables,
                    "ocr": didOCR
                ])
            } catch {
                call.reject(error.localizedDescription)
            }
        }
    }

    /// 文字層の無い PDF をページごとに2倍の画像へ変換し、端末内の Vision で読む。
    private static func recognizePDF(url: URL) throws -> [String] {
        guard let document = PDFDocument(url: url) else { throw DocumentTextError.broken }
        guard !document.isLocked else { throw DocumentTextError.locked }

        var lines: [String] = []
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            let bounds = page.bounds(for: .mediaBox)
            let image = page.thumbnail(
                of: CGSize(width: max(1, bounds.width * 2), height: max(1, bounds.height * 2)),
                for: .mediaBox
            )
            guard let cgImage = image.cgImage else { continue }
            let request = VNRecognizeTextRequest()
            request.recognitionLanguages = ["ja-JP"]
            request.recognitionLevel = .accurate
            do {
                try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
            } catch {
                throw NSError(
                    domain: "DocumentReader",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "スキャンした PDF の文字を読み取れませんでした"]
                )
            }
            lines.append(contentsOf: recognizedLines(from: request.results ?? []))
        }
        return lines
    }

    /// 写真 1 枚を端末内の Vision で読み、上から順に文字列を返す。
    private static func recognizeImage(
        _ cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> [String] {
        let request = VNRecognizeTextRequest()
        request.recognitionLanguages = ["ja-JP"]
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(
                cgImage: cgImage,
                orientation: orientation,
                options: [:]
            ).perform([request])
        } catch {
            throw imageRecognitionError()
        }
        let lines = recognizedLines(from: request.results ?? [])
        guard !lines.isEmpty else { throw imageRecognitionError() }
        return lines
    }

    /// 名刺用に、文字と画像内の位置を左上原点の割合で返す。文字が無くても空配列を返す。
    private static func recognizeImageBoxes(_ cgImage: CGImage) throws -> [[String: Any]] {
        let request = VNRecognizeTextRequest()
        request.recognitionLanguages = ["ja-JP", "en-US"]
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.minimumTextHeight = 0.006
        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
        } catch {
            throw imageRecognitionError()
        }

        return (request.results ?? [])
            .sorted {
                if abs($0.boundingBox.maxY - $1.boundingBox.maxY) > 0.01 {
                    return $0.boundingBox.maxY > $1.boundingBox.maxY
                }
                return $0.boundingBox.minX < $1.boundingBox.minX
            }
            .compactMap { observation -> [String: Any]? in
                guard let candidate = observation.topCandidates(1).first else { return nil }
                let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return nil }
                let box = observation.boundingBox
                return [
                    "text": text,
                    "x": Double(box.minX),
                    "y": Double(1 - box.maxY),
                    "width": Double(box.width),
                    "height": Double(box.height)
                ]
            }
    }

    /// UIImage の向き情報を画素へ反映し、台形補正と OCR を同じ上向き画像に対して行えるようにする。
    private static func uprightCGImage(
        _ cgImage: CGImage,
        orientation: CGImagePropertyOrientation,
        context: CIContext
    ) -> CGImage {
        guard orientation != .up else { return cgImage }
        let upright = CIImage(cgImage: cgImage).oriented(orientation)
        return context.createCGImage(upright, from: upright.extent) ?? cgImage
    }

    private static func recognizedLines(
        from observations: [VNRecognizedTextObservation]
    ) -> [String] {
        observations
            .sorted {
                if abs($0.boundingBox.maxY - $1.boundingBox.maxY) > 0.01 {
                    return $0.boundingBox.maxY > $1.boundingBox.maxY
                }
                return $0.boundingBox.minX < $1.boundingBox.minX
            }
            .compactMap {
                $0.topCandidates(1).first?.string.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty }
    }

    private static func cgImageOrientation(
        from orientation: UIImage.Orientation
    ) -> CGImagePropertyOrientation {
        switch orientation {
        case .up: return .up
        case .upMirrored: return .upMirrored
        case .down: return .down
        case .downMirrored: return .downMirrored
        case .left: return .left
        case .leftMirrored: return .leftMirrored
        case .right: return .right
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }

    private static func imageRecognitionError() -> NSError {
        NSError(
            domain: "DocumentReader",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: "写真の文字を読み取れませんでした"]
        )
    }

    private func hostViewController() -> UIViewController? {
        var top: UIViewController? = bridge?.viewController
        if top == nil {
            let scene = UIApplication.shared.connectedScenes
                .first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene
            top = scene?.windows.first(where: { $0.isKeyWindow })?.rootViewController
        }
        while let presented = top?.presentedViewController {
            top = presented
        }
        return top
    }
}
