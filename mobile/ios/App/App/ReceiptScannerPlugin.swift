//
//  ReceiptScannerPlugin.swift
//
//  レシートや書類を撮影して文字を読み取る Capacitor プラグイン。
//
//  ・撮り方は2種類あり、利用者が選べる（2026-09-24）。JS から camera で指定する
//      "silent"   … 自前の無音カメラ（SilentCameraViewController）。
//                   映像の1コマを取り出す方式のため、シャッター音が鳴らない。
//                   ただし書類の四隅を自動で切り出す機能は無い
//      "document" … VisionKit の書類カメラ。四隅を自動で切り出して歪みも直すが、
//                   撮影時にシャッター音が鳴る（日本向け iPhone では消せない）
//  ・文字認識は Vision（iOS 標準・端末内で完結。画像も文字も外部へ送らない）
//  ・返すのは「行ごとの文字と位置」まで。合計・日付・店名の取り出しは JS 側
//    （apps/shared/receipt.js）で行う。理由: 取り出しの規則はレシートの様式ごとに
//    直す機会が多く、JS ならアプリを作り直さずにテストして直せるため
//
import Foundation
import UIKit
import Capacitor
import Vision
import VisionKit
import AVFoundation
import Photos

@objc(ReceiptScannerPlugin)
public class ReceiptScannerPlugin: CAPPlugin, CAPBridgedPlugin, VNDocumentCameraViewControllerDelegate {
    public let identifier = "ReceiptScannerPlugin"
    public let jsName = "ReceiptScanner"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "scan", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "scanToPhotos", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise)
    ]

    /// 撮ったものの扱い方。"text" = 文字を読み取って返す / "photos" = 写真アプリに保存する
    private var mode: String = "text"
    /// 書類カメラ（VisionKit）を使っているときの呼び出し元。無音カメラでは使わない
    private var pendingCall: CAPPluginCall?
    /// 撮り方。"silent" = 無音カメラ / "document" = VisionKit の書類カメラ
    private var camera: String = "silent"
    /// 何を撮るか。"receipt"（既定）/ "planner"（手帳）/ "document"（書類）/ "any"（振り分け前で不明）。
    /// 案内文と、文字認識で拾う文字の小ささを変える
    private var purpose: String = "receipt"

    @objc func isSupported(_ call: CAPPluginCall) {
        let hasCamera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) != nil
        call.resolve([
            "supported": hasCamera,
            "silent": hasCamera,
            "document": VNDocumentCameraViewController.isSupported
        ])
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
        self.camera = (call.getString("camera") == "document") ? "document" : "silent"
        self.purpose = call.getString("purpose") ?? (mode == "photos" ? "document" : "receipt")
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
            // 書類カメラ（音は鳴るが、四隅を自動で切り出す）
            if self.camera == "document" && VNDocumentCameraViewController.isSupported {
                let scanner = VNDocumentCameraViewController()
                scanner.delegate = self
                scanner.modalPresentationStyle = .fullScreen
                self.pendingCall = call
                host.present(scanner, animated: true)
                return
            }

            // 無音カメラ（音は鳴らない。撮ったあと紙の四隅を探して傾きを直す）
            let silent = SilentCameraViewController()
            silent.modalPresentationStyle = .fullScreen
            switch self.purpose {
            case "planner":
                silent.guidanceText = "手帳のページ全体（上の「◯月」の見出しも）が入るようにし、真上から「撮る」を押してください。暗いときは「ライト」を使ってください（音は鳴りません）"
            case "document":
                silent.guidanceText = "書類全体が入るようにして「撮る」を押してください（音は鳴りません）"
            case "any":
                silent.guidanceText = "レシート・通知・手帳のページの全体が入るようにし、真上から「撮る」を押してください（音は鳴りません）"
            default:
                silent.guidanceText = "レシート全体が入るようにして「撮る」を押してください（音は鳴りません）"
            }
            silent.onFinish = { [weak self] image in
                guard let self = self else { return }
                guard let image = image else {
                    call.resolve(["cancelled": true])
                    return
                }
                if mode == "photos" {
                    self.savePage(image, call: call)
                    return
                }
                self.recognize(image: image, purpose: self.purpose) { result in
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
            host.present(silent, animated: true)
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

    // MARK: - 書類カメラ（VisionKit）の受け口

    public func documentCameraViewController(_ controller: VNDocumentCameraViewController,
                                             didFinishWith scan: VNDocumentCameraScan) {
        controller.dismiss(animated: true)
        guard let call = pendingCall else { return }
        pendingCall = nil
        guard scan.pageCount > 0 else {
            call.resolve(["cancelled": true])
            return
        }
        if mode == "photos" {
            var images: [UIImage] = []
            for index in 0..<scan.pageCount { images.append(scan.imageOfPage(at: index)) }
            savePages(images, call: call)
            return
        }
        // 1枚目だけを使う（レシートは1枚で完結するため）
        let image = scan.imageOfPage(at: 0)
        recognize(image: image, purpose: purpose) { result in
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

    // MARK: - 写真アプリへの保存

    private func savePage(_ image: UIImage, call: CAPPluginCall) {
        savePages([image], call: call)
    }

    /// 撮ったページを写真アプリに追加する。
    /// 追加だけの許可（addOnly）を求めるため、既存の写真を読むことはない。
    private func savePages(_ images: [UIImage], call: CAPPluginCall) {
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            guard status == .authorized || status == .limited else {
                call.reject("写真への追加が許可されていません。設定アプリで許可してください")
                return
            }
            PHPhotoLibrary.shared().performChanges({
                for image in images {
                    _ = PHAssetChangeRequest.creationRequestForAsset(from: image)
                }
            }, completionHandler: { success, error in
                if success {
                    call.resolve(["cancelled": false, "saved": images.count])
                } else {
                    call.reject("写真に保存できませんでした: \(error?.localizedDescription ?? "原因不明")")
                }
            })
        }
    }

    // MARK: - 文字認識

    /// 画像内の文字を行ごとに認識し、文字列と位置（画像の左上を原点とした 0〜1 の割合）を返す。
    private func recognize(image: UIImage, purpose: String, completion: @escaping (Result<[[String: Any]], Error>) -> Void) {
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
        // 手帳の月間ページは、マスの隅の日付の数字や手書きが小さい。
        // 既定のままだと小さな文字を読み飛ばすため、拾う文字の下限を下げる（そのぶん少し時間がかかる）
        if purpose == "planner" || purpose == "any" {
            request.minimumTextHeight = 0.006
        }

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
