import Foundation
import PDFKit

/// PDF からページ単位で本文を取り出す。
enum PDFTextExtractor {
    static func blocks(from url: URL) throws -> [RawBlock] {
        guard let document = PDFDocument(url: url) else { throw ParseError.unreadableFile }
        if document.isLocked { throw ParseError.encryptedPDF }

        var blocks: [RawBlock] = []
        var totalCharacters = 0

        for pageIndex in 0..<document.pageCount {
            guard let page = document.page(at: pageIndex), let raw = page.string else { continue }
            totalCharacters += raw.count
            let locator = "\(pageIndex + 1) ページ"
            for paragraph in LineJoiner.paragraphs(from: raw) {
                blocks.append(RawBlock(text: paragraph, locator: locator))
            }
        }

        guard totalCharacters >= 40, !blocks.isEmpty else { throw ParseError.noExtractableText }
        return blocks
    }
}

/// PDF やプレーンテキストの「途中で改行された行」を段落へ組み直す。
enum LineJoiner {
    private static let sentenceEnders: Set<Character> = [
        "。", "．", ".", "！", "!", "？", "?", "」", "』", "”", "\"", "）", ")", "…", ":", "："
    ]

    static func paragraphs(from text: String) -> [String] {
        let normalized = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")

        var paragraphs: [String] = []
        var current = ""

        for rawLine in normalized.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)

            if line.isEmpty {
                flush(&current, into: &paragraphs)
                continue
            }

            if current.isEmpty {
                current = line
                continue
            }

            if startsNewParagraph(line) || endsParagraph(current) {
                flush(&current, into: &paragraphs)
                current = line
            } else {
                current = join(current, line)
            }
        }

        flush(&current, into: &paragraphs)
        return paragraphs
    }

    private static func flush(_ current: inout String, into paragraphs: inout [String]) {
        let trimmed = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { paragraphs.append(trimmed) }
        current = ""
    }

    private static func endsParagraph(_ text: String) -> Bool {
        guard let last = text.last else { return false }
        return sentenceEnders.contains(last)
    }

    private static func startsNewParagraph(_ line: String) -> Bool {
        guard let first = line.first else { return false }
        // 全角スペースでの字下げ、箇条書き、章番号らしき行は新しい段落として扱う。
        if first == "　" { return true }
        if "・•‣-–—*■□●○◆".contains(first) { return true }
        if line.hasPrefix("第") && line.count <= 30 { return true }
        return false
    }

    private static func join(_ left: String, _ right: String) -> String {
        var left = left
        // 英文のハイフン折り返しは連結して 1 語に戻す。
        if left.hasSuffix("-"), let firstRight = right.first, firstRight.isLetter {
            left.removeLast()
            return left + right
        }
        if needsSpace(between: left.last, and: right.first) {
            return left + " " + right
        }
        return left + right
    }

    /// 日本語同士は空白なし、英数字同士は空白ありで連結する。
    private static func needsSpace(between left: Character?, and right: Character?) -> Bool {
        guard let left, let right else { return false }
        return isLatin(left) && isLatin(right)
    }

    private static func isLatin(_ character: Character) -> Bool {
        guard let scalar = character.unicodeScalars.first else { return false }
        return scalar.value < 0x3000 && (character.isLetter || character.isNumber)
    }
}
