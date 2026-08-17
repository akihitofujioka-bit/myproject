import Foundation
import NaturalLanguage

/// 段落の並びを、読み上げ 1 回分ずつのセグメントへ分割する。
enum TextSegmenter {
    /// 1 セグメントの上限文字数。長すぎると一時停止や頭出しの粒度が粗くなるため区切る。
    private static let maxSegmentLength = 160
    /// 区切り直しに使う中間の句読点。
    private static let softBreaks: Set<Character> = ["、", "，", ",", "；", ";", "：", ":", "）", ")"]

    static func makeDocument(from blocks: [RawBlock]) -> BookDocument {
        var segments: [Segment] = []

        for block in blocks {
            let text = block.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }

            if block.isHeading {
                appendSegment(text, isHeading: true, locator: block.locator, to: &segments)
                continue
            }

            for sentence in sentences(in: text) {
                for piece in split(sentence, limit: maxSegmentLength) {
                    appendSegment(piece, isHeading: false, locator: block.locator, to: &segments)
                }
            }
        }

        return BookDocument(segments: segments)
    }

    private static func appendSegment(
        _ text: String,
        isHeading: Bool,
        locator: String?,
        to segments: inout [Segment]
    ) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isSpeakable(trimmed) else { return }
        segments.append(
            Segment(id: segments.count, text: trimmed, isHeading: isHeading, locator: locator)
        )
    }

    /// 記号だけ・ページ番号だけの断片は読み上げても意味がないので落とす。
    private static func isSpeakable(_ text: String) -> Bool {
        guard !text.isEmpty else { return false }
        let hasLetterOrDigit = text.unicodeScalars.contains {
            CharacterSet.alphanumerics.contains($0)
        }
        guard hasLetterOrDigit else { return false }
        // 「12」「- 12 -」のような、数字と記号だけの行はページ番号とみなす。
        let stripped = text.trimmingCharacters(in: CharacterSet(charactersIn: "-–—0123456789 　.·|/"))
        return !stripped.isEmpty
    }

    private static func sentences(in text: String) -> [String] {
        let tokenizer = NLTokenizer(unit: .sentence)
        tokenizer.string = text
        var results: [String] = []
        tokenizer.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
            let sentence = String(text[range]).trimmingCharacters(in: .whitespacesAndNewlines)
            if !sentence.isEmpty { results.append(sentence) }
            return true
        }
        return results.isEmpty ? [text] : results
    }

    /// 上限を超える文を、句読点優先で分割する。
    private static func split(_ sentence: String, limit: Int) -> [String] {
        guard sentence.count > limit else { return [sentence] }

        var pieces: [String] = []
        var current = ""

        for character in sentence {
            current.append(character)
            if current.count >= limit, softBreaks.contains(character) {
                pieces.append(current)
                current = ""
            } else if current.count >= limit * 2 {
                // 句読点が来ないまま伸び続けた場合の保険。
                pieces.append(current)
                current = ""
            }
        }

        if !current.isEmpty {
            if let last = pieces.indices.last, current.count < limit / 4 {
                // 末尾の極端に短い端数は前のかたまりに寄せる。
                pieces[last] += current
            } else {
                pieces.append(current)
            }
        }
        return pieces
    }
}
