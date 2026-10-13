//
//  SpeechMemoPlugin.swift
//
//  話した内容を端末内だけで文字にし、メモ欄へ渡す Capacitor プラグイン。
//  音声バッファは認識中だけ扱い、ファイルには保存しない。
//
import Foundation
import AVFoundation
import Speech
import Capacitor

@objc(SpeechMemoPlugin)
public class SpeechMemoPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "SpeechMemoPlugin"
    public let jsName = "SpeechMemo"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise)
    ]

    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var latestText = ""
    private var isListening = false
    private var tapInstalled = false

    private func onDeviceRecognizer() -> SFSpeechRecognizer? {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ja-JP")),
              recognizer.supportsOnDeviceRecognition else {
            return nil
        }
        return recognizer
    }

    @objc func isSupported(_ call: CAPPluginCall) {
        call.resolve(["supported": onDeviceRecognizer() != nil])
    }

    @objc func start(_ call: CAPPluginCall) {
        guard onDeviceRecognizer() != nil else {
            call.reject("この端末では使えません")
            return
        }

        SFSpeechRecognizer.requestAuthorization { [weak self] speechStatus in
            guard let self = self else { return }
            AVAudioSession.sharedInstance().requestRecordPermission { microphoneGranted in
                DispatchQueue.main.async {
                    guard speechStatus == .authorized, microphoneGranted else {
                        call.reject("マイクか音声認識が許可されていません（設定 → 壱師）")
                        return
                    }
                    self.beginRecognition(call)
                }
            }
        }
    }

    private func beginRecognition(_ call: CAPPluginCall) {
        guard !isListening else {
            call.resolve()
            return
        }
        guard let recognizer = onDeviceRecognizer() else {
            call.reject("この端末では使えません")
            return
        }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true)

            let request = SFSpeechAudioBufferRecognitionRequest()
            request.requiresOnDeviceRecognition = true
            request.shouldReportPartialResults = true
            recognitionRequest = request
            latestText = ""

            let inputNode = audioEngine.inputNode
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                request.append(buffer)
            }
            tapInstalled = true

            recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                guard let self = self else { return }
                DispatchQueue.main.async {
                    if let result = result {
                        self.latestText = result.bestTranscription.formattedString
                        self.notifyListeners("partial", data: ["text": self.latestText])
                    }
                    if error != nil {
                        self.stopAudioInput()
                    }
                }
            }

            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
            call.resolve()
        } catch {
            stopAudioInput()
            call.reject("音声認識を始められませんでした")
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        stopAudioInput()
        call.resolve(["text": latestText])
    }

    private func stopAudioInput() {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        if tapInstalled {
            audioEngine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        isListening = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
