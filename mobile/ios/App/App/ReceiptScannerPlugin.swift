//
//  ReceiptScannerPlugin.swift
//
//  レシートや書類を撮影して文字を読み取る Capacitor プラグイン。
//
//  ・撮影は自前の無音カメラ（SilentCameraViewController）。
//    VisionKit の書類カメラはシャッター音が鳴るため使うのをやめた（2026-09-24）。
//    映像の1コマを取り出す方式にしており、写真を撮る仕組みを使わないので音が鳴らない
//  ・文字認識は Vision（iOS 標準・端末内で完結。画像も文字も外部へ送らない）
//  ・返すのは「行ごとの文字と位置」まで。合計・日付・店名の取り出しは JS 側
//    （apps/shared/receipt.js）で行う。理由: 取り出しの規則はレシートの様式ごとに
//    直す機会が多く、JS ならアプリを作り直さずにテストして直せるため
//
import Foundation
import UIKit
import Capacitor
import Vision
import AVFoundation
import Photos

@objc(ReceiptScannerPlugin)
public class ReceiptScannerPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ReceiptScannerPlugin"
    public let jsName = "ReceiptScanner"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "scan", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "scanToPhotos", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise)
    ]

    /// 撮ったものの扱い方。"text" = 文字を読み取って返す / "photos" = 写真アプリに保存する
    private var mode: String = "text"

    @objc func isSupported(_ call: CAPPluginCall) {
        // 背面カメラがあれば使える（VisionKit の対応可否には依存しなくなった）
        let hasCamera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) != nil
        call.resolve(["supported": hasCamera])
    }

    /// 無音カメラを開いて撮り、写した文字を行ごとに返す。
    /// 利用者が閉じた場合は { cancelled: true } を返す（失敗ではない）。
    @objc func scan(_ call: CAPPluginCall) {
        startCamera(call, mode: "text")
    }

    /// 無音カメラを開いて撮り、そのまま写真アプリに保存する。
    @objc func scanToPhotos(_ call: CAPPluginCall) {
        startCamera(call, mode: "photos")
    }

    private func startCamera(_ call: CAPPluginCall, mode: String) {
        self.mode = mode
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        if status == .denied || status == .restricted {
            call.reject("カメラの使用が許可されていません。設定アプリで許可してください")
            return
        }
        if status == .notDetermined {
            AVCaptureDevice.requestAccess(for: .video) { granted in
                if granted {
                    self.present(call, mode: mode)
                } else {
                    call.reject("カメラの使用が許可されていません。設定アプリで許可してください")
                }
            }
            return
        }
        present(call, mode: mode)
    }

    private func present(_ call: CAPPluginCall, mode: String) {
        DispatchQueue.main.async {
            // 表示先が見つからない・ふさがっている場合に黙って終わらないようにする。
            // 以前は present の結果を確かめておらず、失敗しても画面に何も出なかった。
            guard let host = self.hostViewController() else {
                call.reject("カメラ画面を開けませんでした（表示先の画面が見つかりません）")
                return
            }
            if host.presentedViewController != nil {
                call.reject("ほかの画面が開いています。閉じてからもう一度お試しください")
                return
            }
            let camera = SilentCameraViewController()
            camera.modalPresentationStyle = .fullScreen
            camera.guidanceText = mode == "photos"
                ? "書類全体が入るようにして「撮る」を押してください（音は鳴りません）"
                : "レシート全体が入るようにして「撮る」を押してください（音は鳴りません）"
            camera.onFinish = { [weak self] image in
                guard let self = self else { return }
                guard let image = image else {
                    call.resolve(["cancelled": true])
                    return
                }
                if mode == "photos" {
                    self.savePage(image, call: call)
                    return
                }
                self.recognize(image: image) { result in
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

    // MARK: - 写真アプリへの保存

    /// 撮った1枚を写真アプリに追加する。
    /// 追加だけの許可（addOnly）を求めるため、既存の写真を読むことはない。
    private func savePage(_ image: UIImage, call: CAPPluginCall) {
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            guard status == .authorized || status == .limited else {
                call.reject("写真への追加が許可されていません。設定アプリで許可してください")
                return
            }
            PHPhotoLibrary.shared().performChanges({
                _ = PHAssetChangeRequest.creationRequestForAsset(from: image)
            }, completionHandler: { success, error in
                if success {
                    call.resolve(["cancelled": false, "saved": 1])
                } else {
                    call.reject("写真に保存できませんでした: \(error?.localizedDescription ?? "原因不明")")
                }
            })
        }
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
