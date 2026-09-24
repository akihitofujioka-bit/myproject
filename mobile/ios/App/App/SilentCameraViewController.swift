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
//  撮った画像はこの画面から呼び出し元へ渡すだけで、外部へは一切送らない。
//
import UIKit
import AVFoundation

final class SilentCameraViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {

    /// 撮れたら画像を、閉じられたら nil を返す
    var onFinish: ((UIImage?) -> Void)?
    /// 画面上部に出す案内（用途ごとに変える）
    var guidanceText: String = "枠に収めて「撮る」を押してください（音は鳴りません）"

    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "jp.myproject.silentcamera")
    private let context = CIContext()

    private var previewLayer: AVCaptureVideoPreviewLayer?
    /// 「撮る」が押されたことを撮影スレッドへ伝える目印
    private var wantsCapture = false
    private var finished = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        buildSession()
        buildControls()
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

    private func buildSession() {
        session.beginConfiguration()
        // 文字を読むため、できるだけ細かい映像にする。使えない機種では自動で落とす
        if session.canSetSessionPreset(.photo) {
            session.sessionPreset = .photo
        } else if session.canSetSessionPreset(.hd1920x1080) {
            session.sessionPreset = .hd1920x1080
        }

        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else {
            session.commitConfiguration()
            return
        }
        session.addInput(input)

        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) {
            session.addOutput(output)
        }
        session.commitConfiguration()

        if let connection = output.connection(with: .video), connection.isVideoOrientationSupported {
            connection.videoOrientation = .portrait
        }

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.insertSublayer(layer, at: 0)
        previewLayer = layer
    }

    private func buildControls() {
        let guidance = UILabel()
        guidance.text = guidanceText
        guidance.textColor = .white
        guidance.font = .systemFont(ofSize: 14, weight: .semibold)
        guidance.numberOfLines = 2
        guidance.textAlignment = .center
        guidance.translatesAutoresizingMaskIntoConstraints = false

        let shutter = UIButton(type: .custom)
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

        view.addSubview(guidance)
        view.addSubview(shutter)
        view.addSubview(close)

        let safe = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            guidance.topAnchor.constraint(equalTo: safe.topAnchor, constant: 16),
            guidance.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 20),
            guidance.trailingAnchor.constraint(equalTo: safe.trailingAnchor, constant: -20),

            shutter.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            shutter.bottomAnchor.constraint(equalTo: safe.bottomAnchor, constant: -28),
            shutter.widthAnchor.constraint(equalToConstant: 72),
            shutter.heightAnchor.constraint(equalToConstant: 72),

            close.leadingAnchor.constraint(equalTo: safe.leadingAnchor, constant: 20),
            close.centerYAnchor.constraint(equalTo: shutter.centerYAnchor)
        ])
    }

    // MARK: - 操作

    @objc private func capture() {
        // 押されたことだけを記録し、次に届いた1コマを画像にする
        queue.async { [weak self] in self?.wantsCapture = true }
    }

    @objc private func cancel() {
        finish(with: nil)
    }

    private func finish(with image: UIImage?) {
        guard !finished else { return }
        finished = true
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            let handler = self.onFinish
            self.onFinish = nil
            self.dismiss(animated: true) { handler?(image) }
        }
    }

    // MARK: - AVCaptureVideoDataOutputSampleBufferDelegate

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard wantsCapture else { return }
        wantsCapture = false

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return }
        finish(with: UIImage(cgImage: cgImage))
    }
}
