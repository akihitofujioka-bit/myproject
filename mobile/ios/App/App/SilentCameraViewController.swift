//
//  SilentCameraViewController.swift
//
//  シャッター音の鳴らないカメラ画面。
//
//  ＜なぜ自前で作るのか＞
//  VisionKit の書類カメラ（VNDocumentCameraViewController）は自動で撮る瞬間に
//  シャッター音を鳴らす。日本で販売された iPhone では、写真を撮る仕組み
//  （AVCapturePhotoOutput）を使うかぎり音を消せない。
//  そこで「映像（AVCaptureVideoDataOutput）の1コマを取り出す」方式にしている。
//  これは写真を撮る仕組みを使わないため、音が鳴らない。
//
//  ＜読み取りやすく撮るための工夫（2026-10-01）＞
//  ・近くの紙にピントが合うよう、使える機種では複数レンズのカメラを使う
//    （近づきすぎると自動で超広角のマクロに切り替わる。Pro 機種は広角の最短撮影距離が
//    約20cmあり、手帳やレシートに近づくとぼけていた）
//  ・「撮る」を押したら、ピント合わせが終わるのを待ち、続く数コマから一番くっきりした
//    ものを選ぶ（押した瞬間の手ぶれを避ける）
//  ・撮れたら紙の四隅を探し、見つかれば傾きと台形のゆがみを直して切り出す
//    （書類カメラの自動切り出しに近いことを、音を鳴らさずに行う）
//  ・暗い場所用のライト、画面を触った場所にピントを合わせる操作
//  ・音が鳴らないので、白く光らせて振動させ「撮れた」ことを伝える
//
//  撮った画像はこの画面から呼び出し元へ渡すだけで、外部へは一切送らない。
//
import UIKit
import AVFoundation
import Vision

final class SilentCameraViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {

    /// 撮れたら画像を、閉じられたら nil を返す
    var onFinish: ((UIImage?) -> Void)?
    /// 画面上部に出す案内（用途ごとに変える）
    var guidanceText: String = "枠に収めて「撮る」を押してください（音は鳴りません）"
    /// 撮ったあと紙の四隅を探して、傾きとゆがみを直すか
    var autoCrop: Bool = true

    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "jp.myproject.silentcamera")
    private let context = CIContext()

    private var device: AVCaptureDevice?
    private var previewLayer: AVCaptureVideoPreviewLayer?

    // 以下の撮影中の状態は、撮影スレッド（queue）の上でだけ読み書きする
    private var capturing = false
    private var framesWaited = 0
    private var framesCompared = 0
    private var bestScore: Double = -1
    private var bestImage: CGImage?

    private var finished = false

    private let shutter = UIButton(type: .custom)
    private let torchButton = UIButton(type: .system)
    private let statusLabel = UILabel()
    private let flashView = UIView()
    private let spinner = UIActivityIndicatorView(style: .large)

    /// ピント合わせを待つ上限（コマ数。毎秒30コマなので約1秒）
    private let maxFocusWaitFrames = 30
    /// くっきり度を比べるコマ数
    private let framesToCompare = 4

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        buildSession()
        buildControls()
        let tap = UITapGestureRecognizer(target: self, action: #selector(focusAtTap(_:)))
        view.addGestureRecognizer(tap)
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        queue.async { [weak self] in
            guard let self = self, !self.session.isRunning else { return }
            self.session.startRunning()
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        setTorch(on: false)
        queue.async { [weak self] in
            guard let self = self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    override var prefersStatusBarHidden: Bool { true }

    // MARK: - 組み立て

    /// 近くの紙を撮りやすいカメラを選ぶ。
    /// 複数レンズの機種では、近づくと自動で超広角（マクロ）に切り替わるカメラを使う。
    private static func pickCamera() -> AVCaptureDevice? {
        let types: [AVCaptureDevice.DeviceType] = [.builtInTripleCamera, .builtInDualWideCamera, .builtInWideAngleCamera]
        for type in types {
            if let found = AVCaptureDevice.default(type, for: .video, position: .back) {
                return found
            }
        }
        return nil
    }

    private func buildSession() {
        session.beginConfiguration()
        // 文字を読むため、できるだけ細かい映像にする。使えない機種では自動で落とす
        if session.canSetSessionPreset(.photo) {
            session.sessionPreset = .photo
        } else if session.canSetSessionPreset(.hd1920x1080) {
            session.sessionPreset = .hd1920x1080
        }

        guard let device = Self.pickCamera(),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else {
            session.commitConfiguration()
            return
        }
        session.addInput(input)
        self.device = device

        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) {
            session.addOutput(output)
        }
        session.commitConfiguration()

        if let connection = output.connection(with: .video) {
            if #available(iOS 17.0, *) {
                if connection.isVideoRotationAngleSupported(90) { connection.videoRotationAngle = 90 }
            } else if connection.isVideoOrientationSupported {
                connection.videoOrientation = .portrait
            }
        }

        configure(device)

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspect   // 映っている範囲がそのまま撮れる範囲になるよう、切り落とさない
        layer.frame = view.bounds
        view.layer.insertSublayer(layer, at: 0)
        previewLayer = layer
    }

    /// ピント・明るさを紙を撮る向きに設定する
    private func configure(_ device: AVCaptureDevice) {
        do {
            try device.lockForConfiguration()
            defer { device.unlockForConfiguration() }
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            // 紙は近くにあるので、近い距離を優先してピントを探す
            if device.isAutoFocusRangeRestrictionSupported {
                device.autoFocusRangeRestriction = .near
            }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            // 複数レンズのカメラは、広角（いわゆる 1x）に当たる倍率で始める。
            // 近づいたときに超広角のマクロへ切り替わるのは、カメラ側が自動で行う
            if device.isVirtualDevice, let first = device.virtualDeviceSwitchOverVideoZoomFactors.first {
                let zoom = CGFloat(truncating: first)
                if zoom >= device.minAvailableVideoZoomFactor && zoom <= device.maxAvailableVideoZoomFactor {
                    device.videoZoomFactor = zoom
                }
                if #available(iOS 15.0, *) {
                    device.setPrimaryConstituentDeviceSwitchingBehavior(.auto, restrictedSwitchingBehaviorConditions: [])
                }
            }
        } catch {
            // 設定できなくても撮影はできるので、既定のまま続ける
        }
    }

    private func buildControls() {
        let guidance = PaddedLabel()
        guidance.text = guidanceText
        guidance.textColor = .white
        guidance.font = .systemFont(ofSize: 14, weight: .semibold)
        guidance.numberOfLines = 3
        guidance.textAlignment = .center
        guidance.backgroundColor = UIColor(white: 0, alpha: 0.45)
        guidance.layer.cornerRadius = 10
        guidance.clipsToBounds = true
        guidance.translatesAutoresizingMaskIntoConstraints = false

        shutter.backgroundColor = .white
        shutter.layer.cornerRadius = 36
        shutter.layer.borderWidth = 4
        shutter.layer.borderColor = UIColor(white: 1, alpha: 0.5).cgColor
        shutter.accessibilityLabel = "撮る"
        shutter.addTarget(self, action: #selector(capture), for: .touchUpInside)
        shutter.translatesAutoresizingMaskIntoConstraints = false

        let close = UIButton(type: .system)
        close.setTitle("閉じる", for: .normal)
        close.setTitleColor(.white, for: .normal)
        close.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        close.addTarget(self, action: #selector(cancel), for: .touchUpInside)
        close.translatesAutoresizingMaskIntoConstraints = false

        torchButton.setTitle("ライト", for: .normal)
        torchButton.setTitleColor(.white, for: .normal)
        torchButton.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        torchButton.addTarget(self, action: #selector(toggleTorch), for: .touchUpInside)
        torchButton.isHidden = !(device?.hasTorch ?? false)
        torchButton.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.textColor = .white
        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.textAlignment = .center
        statusLabel.text = "画面を触ると、その場所にピントを合わせます"
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        flashView.backgroundColor = .white
        flashView.alpha = 0
        flashView.isUserInteractionEnabled = false
        flashView.translatesAutoresizingMaskIntoConstraints = false

        spinner.color = .white
        spinner.hidesWhenStopped = true
        spinner.translatesAutoresizingMaskIntoConstraints = false

        [flashView, guidance, statusLabel, shutter, close, torchButton, spinner].forEach { view.addSubview($0) }

        let safe = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            flashView.topAnchor.constraint(equalTo: view.topAnchor),
            flashView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            flashView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            flashView.trailingAnchor.constraint(equalTo: view.trailingAnchor),

            guidance.topAnchor.constraint(equalTo: safe.topAnchor, constant: 12),
            guidance.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 16),
            guidance.trailingAnchor.constraint(equalTo: safe.trailingAnchor, constant: -16),

            shutter.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            shutter.bottomAnchor.constraint(equalTo: safe.bottomAnchor, constant: -28),
            shutter.widthAnchor.constraint(equalToConstant: 72),
            shutter.heightAnchor.constraint(equalToConstant: 72),

            statusLabel.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: safe.trailingAnchor, constant: -16),
            statusLabel.bottomAnchor.constraint(equalTo: shutter.topAnchor, constant: -14),

            close.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 20),
            close.centerYAnchor.constraint(equalTo: shutter.centerYAnchor),

            torchButton.trailingAnchor.constraint(equalTo: safe.trailingAnchor, constant: -20),
            torchButton.centerYAnchor.constraint(equalTo: shutter.centerYAnchor),

            spinner.centerXAnchor.constraint(equalTo: shutter.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: shutter.centerYAnchor)
        ])
    }

    // MARK: - 操作

    @objc private func capture() {
        shutter.isEnabled = false
        shutter.alpha = 0.3
        spinner.startAnimating()
        statusLabel.text = "ピントを合わせています…動かさないでください"
        // 押されたことだけを撮影スレッドに伝え、届いたコマの中から選ぶ
        queue.async { [weak self] in
            guard let self = self else { return }
            self.framesWaited = 0
            self.framesCompared = 0
            self.bestScore = -1
            self.bestImage = nil
            self.capturing = true
        }
    }

    @objc private func cancel() {
        finish(with: nil)
    }

    @objc private func toggleTorch() {
        guard let device = device, device.hasTorch else { return }
        setTorch(on: device.torchMode != .on)
    }

    private func setTorch(on: Bool) {
        guard let device = device, device.hasTorch else { return }
        do {
            try device.lockForConfiguration()
            device.torchMode = on ? .on : .off
            device.unlockForConfiguration()
            DispatchQueue.main.async { self.torchButton.setTitle(on ? "ライト消" : "ライト", for: .normal) }
        } catch {
            // ライトが使えなくても撮影は続けられる
        }
    }

    /// 触った場所にピントと明るさを合わせる。合わせたあとも、紙が動けば追いかける
    @objc private func focusAtTap(_ gesture: UITapGestureRecognizer) {
        guard let device = device, let layer = previewLayer else { return }
        let point = layer.captureDevicePointConverted(fromLayerPoint: gesture.location(in: view))
        do {
            try device.lockForConfiguration()
            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = point
                if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
            }
            if device.isExposurePointOfInterestSupported {
                device.exposurePointOfInterest = point
                if device.isExposureModeSupported(.continuousAutoExposure) { device.exposureMode = .continuousAutoExposure }
            }
            device.unlockForConfiguration()
            statusLabel.text = "ここにピントを合わせます"
        } catch {
            // 合わせられなくても撮影は続けられる
        }
    }

    /// 撮れたことを知らせる（音の代わりに、白く光らせて軽く振動させる）
    private func signalCaptured() {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        flashView.alpha = 0.85
        UIView.animate(withDuration: 0.35) { self.flashView.alpha = 0 }
        statusLabel.text = "撮れました。紙の範囲を整えています…"
    }

    private func finish(with image: UIImage?) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, !self.finished else { return }
            self.finished = true
            let handler = self.onFinish
            self.onFinish = nil
            self.dismiss(animated: true) { handler?(image) }
        }
    }

    // MARK: - AVCaptureVideoDataOutputSampleBufferDelegate

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard capturing else { return }

        // ピント・明るさを合わせている途中のコマはぼけているので、終わるまで待つ（上限あり）
        if let device = device, device.isAdjustingFocus || device.isAdjustingExposure, framesWaited < maxFocusWaitFrames {
            framesWaited += 1
            return
        }

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let score = sharpness(of: ciImage)
        if score > bestScore, let cgImage = context.createCGImage(ciImage, from: ciImage.extent) {
            bestScore = score
            bestImage = cgImage
        }
        framesCompared += 1
        guard framesCompared >= framesToCompare, let picked = bestImage else { return }

        capturing = false
        bestImage = nil
        DispatchQueue.main.async { self.signalCaptured() }
        let result = autoCrop ? Self.cropToPaper(picked, context: context) : picked
        finish(with: UIImage(cgImage: result))
    }

    /// くっきり度。縮小した画像の輪郭の強さの平均（ぶれやぼけがあると小さくなる）
    private func sharpness(of image: CIImage) -> Double {
        let scale = 480.0 / max(image.extent.width, 1)
        let small = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let edges = CIFilter(name: "CIEdges", parameters: [kCIInputImageKey: small, kCIInputIntensityKey: 1.0])?.outputImage,
              let average = CIFilter(name: "CIAreaAverage", parameters: [
                kCIInputImageKey: edges,
                kCIInputExtentKey: CIVector(cgRect: small.extent)
              ])?.outputImage else { return 0 }
        var pixel = [Float](repeating: 0, count: 4)
        context.render(average, toBitmap: &pixel, rowBytes: 16,
                       bounds: CGRect(x: average.extent.minX, y: average.extent.minY, width: 1, height: 1),
                       format: .RGBAf, colorSpace: nil)
        return Double(pixel[0] + pixel[1] + pixel[2])
    }

    // MARK: - 紙の切り出し

    /// 紙（または手帳のページ）の四隅を探し、見つかれば傾きとゆがみを直して切り出す。
    /// 見つからない・小さすぎるときは、撮ったままの画像を返す。
    ///
    /// 四隅は少し外側に広げてから切り出す。月間のマス目の外枠を紙の端と取り違えた場合でも、
    /// 枠のすぐ上にある「10月」などの見出しが切り落とされないようにするため。
    static func cropToPaper(_ image: CGImage, context: CIContext) -> CGImage {
        let request = VNDetectRectanglesRequest()
        request.maximumObservations = 4
        request.minimumConfidence = 0.6
        request.minimumAspectRatio = 0.3
        request.maximumAspectRatio = 1.0
        request.minimumSize = 0.4
        request.quadratureTolerance = 25

        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        do {
            try handler.perform([request])
        } catch {
            return image
        }
        let found = request.results ?? []
        guard let best = found.max(by: { area(of: $0) < area(of: $1) }), area(of: best) >= 0.3 else {
            return image
        }

        let width = CGFloat(image.width)
        let height = CGFloat(image.height)
        let corners = [best.topLeft, best.topRight, best.bottomRight, best.bottomLeft]
        let center = CGPoint(x: corners.map { $0.x }.reduce(0, +) / 4, y: corners.map { $0.y }.reduce(0, +) / 4)
        // Vision と CIImage はどちらも左下が原点なので、そのまま画素の位置に直せる
        func pixel(_ p: CGPoint) -> CIVector {
            let margin: CGFloat = 0.06
            let x = min(max(p.x + (p.x - center.x) * margin, 0), 1) * width
            let y = min(max(p.y + (p.y - center.y) * margin, 0), 1) * height
            return CIVector(x: x, y: y)
        }
        let corrected = CIImage(cgImage: image).applyingFilter("CIPerspectiveCorrection", parameters: [
            "inputTopLeft": pixel(best.topLeft),
            "inputTopRight": pixel(best.topRight),
            "inputBottomRight": pixel(best.bottomRight),
            "inputBottomLeft": pixel(best.bottomLeft)
        ])
        guard corrected.extent.width > 100, corrected.extent.height > 100,
              let output = context.createCGImage(corrected, from: corrected.extent) else {
            return image
        }
        return output
    }

    /// 四角形の面積（画像全体を1とした割合）
    private static func area(of r: VNRectangleObservation) -> CGFloat {
        let p = [r.topLeft, r.topRight, r.bottomRight, r.bottomLeft]
        var sum: CGFloat = 0
        for i in 0..<4 {
            let a = p[i], b = p[(i + 1) % 4]
            sum += a.x * b.y - b.x * a.y
        }
        return abs(sum) / 2
    }
}

/// 案内文の周りに余白を付けるためのラベル
private final class PaddedLabel: UILabel {
    override func drawText(in rect: CGRect) {
        super.drawText(in: rect.insetBy(dx: 10, dy: 6))
    }
    override var intrinsicContentSize: CGSize {
        let size = super.intrinsicContentSize
        return CGSize(width: size.width + 20, height: size.height + 12)
    }
    override func textRect(forBounds bounds: CGRect, limitedToNumberOfLines numberOfLines: Int) -> CGRect {
        let inner = super.textRect(forBounds: bounds.insetBy(dx: 10, dy: 6), limitedToNumberOfLines: numberOfLines)
        return inner.insetBy(dx: -10, dy: -6)
    }
}
