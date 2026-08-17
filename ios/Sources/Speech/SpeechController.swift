import AVFoundation
import Combine
import MediaPlayer
import SwiftUI

/// 読み上げの中心。1 セグメントずつ発話し、終了通知で次へ進む。
/// バックグラウンド再生・ロック画面の操作・スリープタイマーもここで面倒を見る。
@MainActor
final class SpeechController: ObservableObject {
    // MARK: - 公開状態

    @Published private(set) var currentIndex: Int = 0
    @Published private(set) var isPlaying: Bool = false
    @Published private(set) var isFinished: Bool = false
    /// 現在のセグメント内で読み上げ中の文字範囲（ハイライト用）。
    @Published private(set) var spokenRange: NSRange?
    @Published private(set) var sleepTimerEndDate: Date?

    @Published var speechRate: Double {
        didSet { defaults.set(speechRate, forKey: Keys.rate); restartIfSpeaking() }
    }
    @Published var pitch: Double {
        didSet { defaults.set(pitch, forKey: Keys.pitch); restartIfSpeaking() }
    }
    @Published var voiceIdentifier: String? {
        didSet { defaults.set(voiceIdentifier, forKey: Keys.voice); restartIfSpeaking() }
    }

    private(set) var document: BookDocument?
    private(set) var bookID: UUID?
    private(set) var bookTitle: String = ""

    /// 読み上げ位置を本棚へ書き戻すためのコールバック。
    var onProgress: (@MainActor (UUID, Int) -> Void)?

    var segmentCount: Int { document?.segments.count ?? 0 }
    var currentSegment: Segment? {
        guard let document, document.segments.indices.contains(currentIndex) else { return nil }
        return document.segments[currentIndex]
    }

    // MARK: - 内部

    private enum Keys {
        static let rate = "speech.rate"
        static let pitch = "speech.pitch"
        static let voice = "speech.voice"
    }

    private let synthesizer = AVSpeechSynthesizer()
    private let proxy = SpeechSynthesizerProxy()
    private let defaults = UserDefaults.standard

    private var speakingUtterance: AVSpeechUtterance?
    private var settingsRestartTask: Task<Void, Never>?
    private var sleepTimer: Timer?
    private var lastReportedIndex: Int = 0
    private var didConfigureRemoteCommands = false

    init() {
        let storedRate = defaults.object(forKey: Keys.rate) as? Double
        let storedPitch = defaults.object(forKey: Keys.pitch) as? Double
        speechRate = storedRate ?? 1.0
        pitch = storedPitch ?? 1.0
        voiceIdentifier = defaults.string(forKey: Keys.voice)

        synthesizer.delegate = proxy
        configureProxy()
        configureRemoteCommands()
        observeInterruptions()
    }

    // MARK: - 読み込み

    /// 本を読み上げ対象としてセットする。既に同じ本なら位置を保ったままにする。
    func prepare(document: BookDocument, book: Book) {
        if bookID == book.id, self.document == document {
            return
        }
        stop()
        self.document = document
        bookID = book.id
        bookTitle = book.title
        currentIndex = min(max(0, book.progressIndex), max(0, document.segments.count - 1))
        lastReportedIndex = currentIndex
        isFinished = false
        spokenRange = nil

        if voiceIdentifier == nil {
            voiceIdentifier = VoiceCatalog.recommendedVoice(for: document)?.identifier
        }
        updateNowPlaying()
    }

    // MARK: - 再生操作

    func play() {
        guard let document, !document.isEmpty else { return }
        activateAudioSession()

        if synthesizer.isPaused {
            synthesizer.continueSpeaking()
            isPlaying = true
            updateNowPlaying()
            return
        }
        guard !synthesizer.isSpeaking else {
            isPlaying = true
            return
        }
        speakCurrentSegment()
    }

    func pause() {
        guard synthesizer.isSpeaking else {
            isPlaying = false
            return
        }
        synthesizer.pauseSpeaking(at: .word)
        isPlaying = false
        reportProgress(force: true)
        updateNowPlaying()
    }

    func togglePlayPause() {
        isPlaying ? pause() : play()
    }

    func stop() {
        cancelSleepTimer()
        settingsRestartTask?.cancel()
        settingsRestartTask = nil
        speakingUtterance = nil
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        isPlaying = false
        spokenRange = nil
        reportProgress(force: true)
        deactivateAudioSession()
    }

    /// 指定のセグメントへ頭出しする。再生中ならそのまま読み続ける。
    func seek(to index: Int) {
        guard let document, !document.isEmpty else { return }
        let target = min(max(0, index), document.segments.count - 1)
        // 一時停止中に頭出ししたときは、止まったまま位置だけ動かす。
        let wasPlaying = isPlaying

        speakingUtterance = nil
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        currentIndex = target
        isFinished = false
        spokenRange = nil
        reportProgress(force: true)

        if wasPlaying {
            play()
        } else {
            updateNowPlaying()
        }
    }

    func nextSegment() { seek(to: currentIndex + 1) }
    func previousSegment() { seek(to: currentIndex - 1) }

    /// 次の見出しへ飛ぶ。見出しが無ければ末尾へ。
    func nextHeading() {
        guard let document else { return }
        let next = document.segments
            .first { $0.id > currentIndex && $0.isHeading }?.id
        seek(to: next ?? document.segments.count - 1)
    }

    /// 直前の見出しへ戻る（同じ見出しの先頭にいる場合はさらに 1 つ前へ）。
    func previousHeading() {
        guard let document else { return }
        let headings = document.segments.filter { $0.isHeading && $0.id < currentIndex }
        seek(to: headings.last?.id ?? 0)
    }

    // MARK: - 発話

    private func speakCurrentSegment() {
        guard let document, document.segments.indices.contains(currentIndex) else {
            isPlaying = false
            return
        }
        let segment = document.segments[currentIndex]
        let utterance = AVSpeechUtterance(string: segment.text)
        utterance.voice = VoiceCatalog.voice(identifier: voiceIdentifier)
            ?? VoiceCatalog.recommendedVoice(for: document)
        utterance.rate = Self.utteranceRate(for: speechRate)
        utterance.pitchMultiplier = Float(min(max(pitch, 0.5), 2.0))
        // 見出しの前後は少し間を空けて、章の切れ目を耳で分かるようにする。
        utterance.preUtteranceDelay = segment.isHeading ? 0.35 : 0
        utterance.postUtteranceDelay = segment.isHeading ? 0.35 : 0.05

        speakingUtterance = utterance
        spokenRange = nil
        isPlaying = true
        isFinished = false
        synthesizer.speak(utterance)
        updateNowPlaying()
    }

    /// 設定変更を今の発話へ反映する（現在のセグメントを先頭から読み直す）。
    /// スライダーを動かしている間は何度も呼ばれるので、少し待ってからまとめて反映する。
    private func restartIfSpeaking() {
        guard isPlaying else { return }
        settingsRestartTask?.cancel()
        settingsRestartTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled, let self, self.isPlaying else { return }
            let index = self.currentIndex
            self.speakingUtterance = nil
            self.synthesizer.stopSpeaking(at: .immediate)
            self.currentIndex = index
            self.speakCurrentSegment()
        }
    }

    /// 1.0 を標準速として AVSpeechUtterance の rate（0.0〜1.0）へ写す。
    private static func utteranceRate(for multiplier: Double) -> Float {
        let base = Double(AVSpeechUtteranceDefaultSpeechRate)
        let value = base * min(max(multiplier, 0.5), 2.0)
        return Float(min(max(value, Double(AVSpeechUtteranceMinimumSpeechRate)),
                         Double(AVSpeechUtteranceMaximumSpeechRate)))
    }

    private func configureProxy() {
        proxy.onFinish = { [weak self] utterance in
            guard let self, self.speakingUtterance === utterance else { return }
            self.advanceAfterFinish()
        }
        proxy.onRange = { [weak self] range, utterance in
            guard let self, self.speakingUtterance === utterance else { return }
            self.spokenRange = range
        }
        proxy.onCancel = { [weak self] utterance in
            guard let self, self.speakingUtterance === utterance else { return }
            self.spokenRange = nil
        }
    }

    private func advanceAfterFinish() {
        guard let document else { return }
        spokenRange = nil

        let next = currentIndex + 1
        guard next < document.segments.count else {
            // 最後まで読み終わった。
            isPlaying = false
            isFinished = true
            speakingUtterance = nil
            reportProgress(force: true)
            updateNowPlaying()
            deactivateAudioSession()
            return
        }
        currentIndex = next
        reportProgress(force: false)
        speakCurrentSegment()
    }

    // MARK: - 進捗の保存

    private func reportProgress(force: Bool) {
        guard let bookID else { return }
        if !force, abs(currentIndex - lastReportedIndex) < 5 { return }
        lastReportedIndex = currentIndex
        onProgress?(bookID, currentIndex)
    }

    // MARK: - スリープタイマー

    func startSleepTimer(minutes: Int) {
        cancelSleepTimer()
        guard minutes > 0 else { return }
        let end = Date().addingTimeInterval(TimeInterval(minutes * 60))
        sleepTimerEndDate = end
        sleepTimer = Timer.scheduledTimer(withTimeInterval: TimeInterval(minutes * 60), repeats: false) { _ in
            Task { @MainActor [weak self] in
                self?.pause()
                self?.sleepTimerEndDate = nil
                self?.sleepTimer = nil
            }
        }
    }

    func cancelSleepTimer() {
        sleepTimer?.invalidate()
        sleepTimer = nil
        sleepTimerEndDate = nil
    }

    // MARK: - オーディオセッション

    private func activateAudioSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [])
        try? session.setActive(true)
    }

    private func deactivateAudioSession() {
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    private func observeInterruptions() {
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            Task { @MainActor in
                guard let self else { return }
                switch type {
                case .began:
                    // 電話や他アプリの再生が始まったら止める。
                    if self.isPlaying { self.pause() }
                default:
                    break
                }
            }
        }
    }

    // MARK: - ロック画面 / コントロールセンター

    private func configureRemoteCommands() {
        guard !didConfigureRemoteCommands else { return }
        didConfigureRemoteCommands = true

        let center = MPRemoteCommandCenter.shared()

        center.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.play() }
            return .success
        }
        center.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.pause() }
            return .success
        }
        center.togglePlayPauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.togglePlayPause() }
            return .success
        }
        center.nextTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.nextSegment() }
            return .success
        }
        center.previousTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.previousSegment() }
            return .success
        }
        center.changePlaybackPositionCommand.isEnabled = false
    }

    private func updateNowPlaying() {
        guard let document, !document.isEmpty else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            return
        }

        var info: [String: Any] = [:]
        info[MPMediaItemPropertyTitle] = document.sectionTitle(at: currentIndex) ?? bookTitle
        info[MPMediaItemPropertyArtist] = bookTitle
        info[MPMediaItemPropertyAlbumTitle] = bookTitle
        // セグメント番号を秒に見立てて、ロック画面に進捗バーを出す。
        info[MPMediaItemPropertyPlaybackDuration] = Double(document.segments.count)
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = Double(currentIndex)
        info[MPNowPlayingInfoPropertyPlaybackRate] = isPlaying ? 1.0 : 0.0

        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }
}
