import Foundation

/// .txt / .md を読み込む。Markdown は記号を落として読み上げ向きに均す。
enum PlainTextParser {
    static func blocks(from url: URL) throws -> [RawBlock] {
        let text = try loadText(at: url)
        let isMarkdown = ["md", "markdown"].contains(url.pathExtension.lowercased())
        return isMarkdown ? markdownBlocks(from: text) : plainBlocks(from: text)
    }

    /// UTF-8 以外（Shift_JIS など）の日本語テキストも開けるようにする。
    static func loadText(at url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        let candidates: [String.Encoding] = [
            .utf8, .utf16, .shiftJIS, .japaneseEUC, .iso2022JP, .isoLatin1
        ]
        for encoding in candidates {
            if let text = String(data: data, encoding: encoding), !text.isEmpty {
                return text
            }
        }
        throw ParseError.unreadableFile
    }

    private static func plainBlocks(from text: String) -> [RawBlock] {
        LineJoiner.paragraphs(from: text).map { RawBlock(text: $0) }
    }

    private static func markdownBlocks(from text: String) -> [RawBlock] {
        var blocks: [RawBlock] = []
        var paragraph = ""
        var insideCodeFence = false

        func flush() {
            let trimmed = paragraph.trimmingCharacters(in: .whitespacesAndNewlines)
            paragraph = ""
            guard !trimmed.isEmpty else { return }
            blocks.append(RawBlock(text: inlineCleaned(trimmed)))
        }

        let normalized = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")

        for rawLine in normalized.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)

            if line.hasPrefix("```") || line.hasPrefix("~~~") {
                flush()
                insideCodeFence.toggle()
                continue
            }
            // コードブロックは読み上げても意味を成さないので飛ばす。
            if insideCodeFence { continue }

            if line.isEmpty {
                flush()
                continue
            }

            if line.hasPrefix("#") {
                flush()
                let title = inlineCleaned(line.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces))
                if !title.isEmpty { blocks.append(RawBlock(text: title, isHeading: true)) }
                continue
            }

            // 水平線や表の区切りは読み飛ばす。
            if line.allSatisfy({ "-=*_| :".contains($0) }) {
                flush()
                continue
            }

            let listItem = line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("+ ")
            if listItem {
                flush()
                blocks.append(RawBlock(text: inlineCleaned(String(line.dropFirst(2)))))
                continue
            }

            paragraph += paragraph.isEmpty ? line : " " + line
        }

        flush()
        return blocks
    }

    /// 強調・リンク・インラインコードなどの記号を外す。
    private static func inlineCleaned(_ text: String) -> String {
        var result = text
        // [表示テキスト](URL) → 表示テキスト
        if let regex = try? NSRegularExpression(pattern: "!?\\[([^\\]]*)\\]\\([^\\)]*\\)") {
            let range = NSRange(result.startIndex..., in: result)
            result = regex.stringByReplacingMatches(in: result, range: range, withTemplate: "$1")
        }
        for marker in ["**", "__", "*", "_", "`", "~~", ">"] {
            result = result.replacingOccurrences(of: marker, with: "")
        }
        return HTMLTextExtractor.normalize(result)
    }
}
