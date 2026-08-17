import Foundation

/// 形式ごとの抽出器を束ねる入口。解析結果はキャッシュへ保存し、2 回目以降の起動を速くする。
enum DocumentParser {
    /// バックグラウンドで解析する。重い処理なので必ず非メインスレッドから呼ぶこと。
    static func parse(fileURL: URL, format: BookFormat) throws -> BookDocument {
        let blocks: [RawBlock]
        switch format {
        case .pdf:
            blocks = try PDFTextExtractor.blocks(from: fileURL)
        case .epub:
            blocks = try EPUBParser.blocks(from: fileURL)
        case .text:
            blocks = try PlainTextParser.blocks(from: fileURL)
        }

        let document = TextSegmenter.makeDocument(from: blocks)
        guard !document.isEmpty else { throw ParseError.noExtractableText }
        return document
    }

    /// キャッシュがあればそれを返し、無ければ解析して保存する。
    static func loadDocument(for book: Book, fileURL: URL) throws -> BookDocument {
        if let cached = DocumentCache.load(bookID: book.id) { return cached }
        let document = try parse(fileURL: fileURL, format: book.format)
        DocumentCache.save(document, bookID: book.id)
        return document
    }
}

/// 解析済みテキストの保存場所（Caches 配下なので容量が逼迫すれば OS が削除する）。
enum DocumentCache {
    private static var directory: URL? {
        guard let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else {
            return nil
        }
        let url = base.appendingPathComponent("ParsedBooks", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private static func fileURL(bookID: UUID) -> URL? {
        directory?.appendingPathComponent("\(bookID.uuidString).json")
    }

    static func load(bookID: UUID) -> BookDocument? {
        guard let url = fileURL(bookID: bookID),
              let data = try? Data(contentsOf: url),
              let document = try? JSONDecoder().decode(BookDocument.self, from: data),
              !document.isEmpty
        else { return nil }
        return document
    }

    static func save(_ document: BookDocument, bookID: UUID) {
        guard let url = fileURL(bookID: bookID),
              let data = try? JSONEncoder().encode(document) else { return }
        try? data.write(to: url, options: .atomic)
    }

    static func remove(bookID: UUID) {
        guard let url = fileURL(bookID: bookID) else { return }
        try? FileManager.default.removeItem(at: url)
    }
}
