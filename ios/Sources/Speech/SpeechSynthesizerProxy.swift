import AVFoundation

/// AVSpeechSynthesizer のデリゲート通知をメインアクターのクロージャへ橋渡しする。
/// SpeechController を @MainActor に保ったままデリゲートを受けるための薄い層。
final class SpeechSynthesizerProxy: NSObject, AVSpeechSynthesizerDelegate {
    var onStart: (@MainActor (AVSpeechUtterance) -> Void)?
    var onFinish: (@MainActor (AVSpeechUtterance) -> Void)?
    var onCancel: (@MainActor (AVSpeechUtterance) -> Void)?
    var onRange: (@MainActor (NSRange, AVSpeechUtterance) -> Void)?

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didStart utterance: AVSpeechUtterance
    ) {
        guard let handler = onStart else { return }
        Task { @MainActor in handler(utterance) }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        guard let handler = onFinish else { return }
        Task { @MainActor in handler(utterance) }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        guard let handler = onCancel else { return }
        Task { @MainActor in handler(utterance) }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        willSpeakRangeOfSpeechString characterRange: NSRange,
        utterance: AVSpeechUtterance
    ) {
        guard let handler = onRange else { return }
        Task { @MainActor in handler(characterRange, utterance) }
    }
}
