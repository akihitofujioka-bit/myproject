import Foundation

/// 本棚に登録された 1 冊分のメタデータ。本文そのものは持たず、
/// アプリ内 Documents/Books に取り込んだファイルを指す。
struct Book: Identifiable, Codable, Hashable {
    let id: UUID
    var title: String
    /// Books ディレクトリからの相対ファイル名。
    var fileName: String
    var format: BookFormat
    var addedAt: Date
    var lastOpenedAt: Date?
    /// 最後に読み上げていたセグメントの位置。
    var progressIndex: Int
    /// 解析済みの総セグメント数（未解析なら 0）。
    var segmentCount: Int

    init(
        id: UUID = UUID(),
        title: String,
        fileName: String,
        format: BookFormat,
        addedAt: Date = Date(),
        lastOpenedAt: Date? = nil,
        progressIndex: Int = 0,
        segmentCount: Int = 0
    ) {
        self.id = id
        self.title = title
        self.fileName = fileName
        self.format = format
        self.addedAt = addedAt
        self.lastOpenedAt = lastOpenedAt
        self.progressIndex = progressIndex
        self.segmentCount = segmentCount
    }

    /// 0.0 〜 1.0 の読み上げ進捗。
    var progress: Double {
        guard segmentCount > 1 else { return 0 }
        return min(1.0, Double(progressIndex) / Double(segmentCount - 1))
    }
}

enum BookFormat: String, Codable, Hashable {
    case pdf
    case epub
    case text

    init?(fileExtension: String) {
        switch fileExtension.lowercased() {
        case "pdf": self = .pdf
        case "epub": self = .epub
        case "txt", "text", "md", "markdown": self = .text
        default: return nil
        }
    }

    var displayName: String {
        switch self {
        case .pdf: return "PDF"
        case .epub: return "EPUB"
        case .text: return "テキスト"
        }
    }

    var systemImage: String {
        switch self {
        case .pdf: return "doc.richtext"
        case .epub: return "book.closed"
        case .text: return "doc.plaintext"
        }
    }
}
