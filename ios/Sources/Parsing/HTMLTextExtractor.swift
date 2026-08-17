import Foundation

/// EPUB 内の XHTML から本文だけを取り出す軽量な抽出器。
/// NSAttributedString の HTML 読み込みはメインスレッド専用で重いため、自前で走査する。
enum HTMLTextExtractor {
    /// 中身ごと読み飛ばす要素。rt / rp はルビ用で、読み上げると同じ語を二重に読むことになる。
    private static let skippedElements: Set<String> = ["script", "style", "head", "rt", "rp", "svg"]
    /// ここで段落を区切る要素。
    private static let blockElements: Set<String> = [
        "p", "div", "br", "li", "tr", "td", "th", "section", "article", "blockquote",
        "pre", "hr", "table", "ul", "ol", "dd", "dt", "figcaption", "aside", "header", "footer"
    ]
    private static let headingElements: Set<String> = ["h1", "h2", "h3", "h4", "h5", "h6"]

    static func blocks(from html: String, locator: String? = nil) -> [RawBlock] {
        var blocks: [RawBlock] = []
        var buffer = ""
        var skipStack: [String] = []
        var headingDepth = 0

        func flush(asHeading: Bool = false) {
            let text = normalize(decodeEntities(buffer))
            buffer = ""
            guard !text.isEmpty else { return }
            blocks.append(RawBlock(text: text, isHeading: asHeading, locator: locator))
        }

        var index = html.startIndex
        while index < html.endIndex {
            let character = html[index]

            guard character == "<" else {
                if skipStack.isEmpty { buffer.append(character) }
                index = html.index(after: index)
                continue
            }

            if html[index...].hasPrefix("<!--") {
                if let end = html.range(of: "-->", range: index..<html.endIndex) {
                    index = end.upperBound
                } else {
                    index = html.endIndex
                }
                continue
            }

            guard let closeIndex = html[index...].firstIndex(of: ">") else { break }
            let inner = String(html[html.index(after: index)..<closeIndex])
            index = html.index(after: closeIndex)

            let isClosing = inner.hasPrefix("/")
            let isSelfClosing = inner.hasSuffix("/")
            let name = tagName(from: inner)
            guard !name.isEmpty else { continue }

            if skippedElements.contains(name) {
                if isClosing {
                    if skipStack.last == name { skipStack.removeLast() }
                } else if !isSelfClosing {
                    // ここで段落を区切らないのが要点。<ruby>猫<rt>ねこ</rt></ruby> のように
                    // 文の途中に現れるため、区切ると 1 文が分断されてしまう。
                    skipStack.append(name)
                }
                continue
            }

            guard skipStack.isEmpty else { continue }

            if headingElements.contains(name) {
                if isClosing {
                    flush(asHeading: true)
                    headingDepth = max(0, headingDepth - 1)
                } else if !isSelfClosing {
                    flush()
                    headingDepth += 1
                }
                continue
            }

            if blockElements.contains(name) {
                flush(asHeading: headingDepth > 0)
            }
        }

        flush(asHeading: headingDepth > 0)
        return blocks
    }

    /// <title> の中身。章タイトルの候補に使う。
    static func title(from html: String) -> String? {
        guard let open = html.range(of: "<title", options: .caseInsensitive),
              let openEnd = html[open.lowerBound...].firstIndex(of: ">"),
              let close = html.range(of: "</title>", options: .caseInsensitive, range: openEnd..<html.endIndex)
        else { return nil }
        let raw = String(html[html.index(after: openEnd)..<close.lowerBound])
        let title = normalize(decodeEntities(raw))
        return title.isEmpty ? nil : title
    }

    private static func tagName(from inner: String) -> String {
        var name = ""
        for character in inner {
            if character == "/" && name.isEmpty { continue }
            if character.isWhitespace || character == "/" || character == ">" { break }
            name.append(character)
        }
        return name.lowercased()
    }

    /// 連続する空白を 1 つに畳み、日本語の間に入った余分な空白を取り除く。
    static func normalize(_ text: String) -> String {
        var collapsed = ""
        var lastWasSpace = false
        for character in text {
            if character.isWhitespace {
                if !lastWasSpace { collapsed.append(" ") }
                lastWasSpace = true
            } else {
                collapsed.append(character)
                lastWasSpace = false
            }
        }

        // 改行由来で日本語の文中に混ざった空白は削る。
        var result = ""
        var pending: Character?
        for character in collapsed {
            if character == " " {
                pending = character
                continue
            }
            if let space = pending {
                if let previous = result.last, isLatinLike(previous) || isLatinLike(character) {
                    result.append(space)
                }
                pending = nil
            }
            result.append(character)
        }
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isLatinLike(_ character: Character) -> Bool {
        guard let scalar = character.unicodeScalars.first else { return false }
        return scalar.value < 0x2000
    }

    static func decodeEntities(_ text: String) -> String {
        guard text.contains("&") else { return text }

        let named: [String: String] = [
            "amp": "&", "lt": "<", "gt": ">", "quot": "\"", "apos": "'", "nbsp": " ",
            "mdash": "—", "ndash": "–", "hellip": "…", "ldquo": "“", "rdquo": "”",
            "lsquo": "‘", "rsquo": "’", "times": "×", "middot": "・", "laquo": "«", "raquo": "»"
        ]

        var result = ""
        var index = text.startIndex
        while index < text.endIndex {
            let character = text[index]
            guard character == "&",
                  let semicolon = text[index...].firstIndex(of: ";"),
                  text.distance(from: index, to: semicolon) <= 10
            else {
                result.append(character)
                index = text.index(after: index)
                continue
            }

            let body = String(text[text.index(after: index)..<semicolon])
            if let replacement = named[body.lowercased()] {
                result.append(replacement)
            } else if body.hasPrefix("#") {
                let digits = body.dropFirst()
                let value: UInt32?
                if digits.hasPrefix("x") || digits.hasPrefix("X") {
                    value = UInt32(digits.dropFirst(), radix: 16)
                } else {
                    value = UInt32(digits)
                }
                if let value, let scalar = Unicode.Scalar(value) {
                    result.append(Character(scalar))
                } else {
                    result.append("&" + body + ";")
                }
            } else {
                result.append("&" + body + ";")
            }
            index = text.index(after: semicolon)
        }
        return result
    }
}
