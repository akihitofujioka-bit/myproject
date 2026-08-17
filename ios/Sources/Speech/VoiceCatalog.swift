import AVFoundation
import NaturalLanguage

/// 端末にインストールされている読み上げ音声の一覧と選択ロジック。
enum VoiceCatalog {
    struct VoiceGroup: Identifiable {
        let id: String        // 言語コード（"ja-JP" など）
        let displayName: String
        let voices: [AVSpeechSynthesisVoice]
    }

    static func allGroups() -> [VoiceGroup] {
        let voices = AVSpeechSynthesisVoice.speechVoices()
        let grouped = Dictionary(grouping: voices) { $0.language }

        return grouped
            .map { language, voices in
                VoiceGroup(
                    id: language,
                    displayName: languageDisplayName(language),
                    voices: voices.sorted { lhs, rhs in
                        if lhs.quality.rank != rhs.quality.rank {
                            return lhs.quality.rank > rhs.quality.rank
                        }
                        return lhs.name < rhs.name
                    }
                )
            }
            .sorted { lhs, rhs in
                // 日本語を先頭に、その後は表示名順。
                if lhs.id.hasPrefix("ja") != rhs.id.hasPrefix("ja") { return lhs.id.hasPrefix("ja") }
                return lhs.displayName < rhs.displayName
            }
    }

    static func voice(identifier: String?) -> AVSpeechSynthesisVoice? {
        guard let identifier else { return nil }
        return AVSpeechSynthesisVoice(identifier: identifier)
    }

    /// 言語コードに対して、いちばん品質の高い音声を選ぶ。
    static func bestVoice(forLanguage language: String) -> AVSpeechSynthesisVoice? {
        let candidates = AVSpeechSynthesisVoice.speechVoices().filter {
            $0.language.lowercased().hasPrefix(language.lowercased().prefix(2))
        }
        return candidates.max { $0.quality.rank < $1.quality.rank }
    }

    /// 本文の言語を推定して音声を決める。判定できなければ端末の言語設定に従う。
    static func recommendedVoice(for document: BookDocument) -> AVSpeechSynthesisVoice? {
        let sample = document.segments.prefix(20).map(\.text).joined(separator: "\n")
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(sample)

        if let language = recognizer.dominantLanguage?.rawValue,
           let voice = bestVoice(forLanguage: language) {
            return voice
        }
        let preferred = Locale.preferredLanguages.first ?? "ja-JP"
        return bestVoice(forLanguage: preferred) ?? AVSpeechSynthesisVoice(language: preferred)
    }

    static func languageDisplayName(_ code: String) -> String {
        Locale.current.localizedString(forIdentifier: code) ?? code
    }

    static func qualityLabel(_ quality: AVSpeechSynthesisVoiceQuality) -> String {
        switch quality {
        case .premium: return "プレミアム"
        case .enhanced: return "高品質"
        default: return "標準"
        }
    }
}

private extension AVSpeechSynthesisVoiceQuality {
    /// premium > enhanced > default の順に並べるための重み。
    var rank: Int {
        switch self {
        case .premium: return 3
        case .enhanced: return 2
        default: return 1
        }
    }
}
