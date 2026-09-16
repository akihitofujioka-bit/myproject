//
//  ReceiptScannerPlugin.swift
//
//  レシートを撮影して文字を読み取る Capacitor プラグイン。
//
//  ・撮影は VisionKit の書類カメラ（レシートの四隅を自動で見つけて切り出す）
//  ・文字認識は Vision（iOS 標準・端末内で完結。画像も文字も外部へ送らない）
//  ・返すのは「行ごとの文字と位置」まで。合計・日付・店名の取り出しは JS 側
//    （apps/shared/receipt.js）で行う。理由: 取り出しの規則はレシートの様式ごとに
//    直す機会が多く、JS ならアプリを作り直さずにテストして直せるため。
//
import Foundation
import UIKit
import Capacitor
import Vision
import VisionKit
import AVFoundation

@objc(ReceiptScannerPlugin)
public class ReceiptScannerPlugin: CAPPlugin, CAPBridgedPlugin, VNDocumentCameraViewControllerDelegate {
    public let identifier = "ReceiptScannerPlugin"
    public let jsName = "ReceiptScanner"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "scan", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise)
    ]

    private var pendingCall: CAPPluginCall?

    @objc func isSupported(_ call: CAPPluginCall) {
        call.resolve(["supported": VNDocumentCameraViewController.isSupported])
    }

    /// 書類カメラを開き、撮影された最初のページを文字認識して返す。
    /// 利用者が閉じた場合は { cancelled: true } を返す（失敗ではない）。
    @objc func scan(_ call: CAPPluginCall) {
        guard VNDocumentCameraViewController.isSupported else {
            call.reject("この端末では書類カメラを使えません")
            return
        }
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        if status == .denied || status == .restricted {
            call.reject("カメラの使用が許可されていません。設定アプリで許可してください")
            return
        }
        pendingCall = call
        DispatchQueue.main.async {
            // 表示先が見つからない・ふさがっている場合に黙って終わらないようにする。
            // 以前は present の結果を確かめておらず、失敗しても画面に何も出なかった。
            guard let host = self.hostViewController() else {
                self.pendingCall = nil
                call.reject("カメラ画面を開けませんでした（表示先の画面が見つかりません）")
                return
            }
            if host.presentedViewController != nil {
                self.pendingCall = nil
                call.reject("ほかの画面が開いています。閉じてからもう一度お試しください")
                return
            }
            let camera = VNDocumentCameraViewController()
            camera.delegate = self
            camera.modalPresentationStyle = .fullScreen
            host.present(camera, animated: true)
        }
    }

    /// カメラ画面を載せる画面を探す。
    /// bridge の画面が取れないことがあるため、そのときは前面のウインドウからたどる。
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

    // MARK: - VNDocumentCameraViewControllerDelegate

    public func documentCameraViewController(_ controller: VNDocumentCameraViewController,
                                             didFinishWith scan: VNDocumentCameraScan) {
        controller.dismiss(animated: true)
        guard let call = pendingCall else { return }
        pendingCall = nil
        guard scan.pageCount > 0 else {
            call.resolve(["cancelled": true])
            return
        }
        // 1枚目だけを使う（レシートは1枚で完結するため）
        let image = scan.imageOfPage(at: 0)
        recognize(image: image) { result in
            switch result {
            case .success(let lines):
                call.resolve([
                    "cancelled": false,
                    "width": image.size.width,
                    "height": image.size.height,
                    "lines": lines
                ])
            case .failure(let error):
                call.reject("文字を読み取れませんでした: \(error.localizedDescription)")
            }
        }
    }

    public func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
        controller.dismiss(animated: true)
        pendingCall?.resolve(["cancelled": true])
        pendingCall = nil
    }

    public func documentCameraViewController(_ controller: VNDocumentCameraViewController,
                                             didFailWithError error: Error) {
        controller.dismiss(animated: true)
        pendingCall?.reject("カメラでエラーが起きました: \(error.localizedDescription)")
        pendingCall = nil
    }

    // MARK: - 文字認識

    /// 画像内の文字を行ごとに認識し、文字列と位置（画像の左上を原点とした 0〜1 の割合）を返す。
    private func recognize(image: UIImage, completion: @escaping (Result<[[String: Any]], Error>) -> Void) {
        guard let cgImage = image.cgImage else {
            completion(.failure(NSError(domain: "ReceiptScanner", code: 1,
                                        userInfo: [NSLocalizedDescriptionKey: "画像を扱えません"])))
            return
        }
        let request = VNRecognizeTextRequest { request, error in
            if let error = error {
                completion(.failure(error))
                return
            }
            let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
            var lines: [[String: Any]] = []
            for obs in observations {
                guard let best = obs.topCandidates(1).first else { continue }
                let box = obs.boundingBox  // Vision は左下が原点なので、上下を反転して左上原点に直す
                lines.append([
                    "text": best.string,
                    "confidence": Double(best.confidence),
                    "x": Double(box.minX),
                    "y": Double(1 - box.maxY),
                    "width": Double(box.width),
                    "height": Double(box.height)
                ])
            }
            completion(.success(lines))
        }
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ja-JP", "en-US"]
        request.usesLanguageCorrection = true

        let handler = VNImageRequestHandler(cgImage: cgImage, orientation: cgOrientation(from: image.imageOrientation), options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try handler.perform([request])
            } catch {
                completion(.failure(error))
            }
        }
    }

    private func cgOrientation(from ui: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch ui {
        case .up: return .up
        case .down: return .down
        case .left: return .left
        case .right: return .right
        case .upMirrored: return .upMirrored
        case .downMirrored: return .downMirrored
        case .leftMirrored: return .leftMirrored
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }
}
