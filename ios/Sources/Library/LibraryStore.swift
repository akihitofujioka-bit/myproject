import Foundation
import PDFKit

/// 本棚の状態管理。取り込んだファイルはアプリ内 Documents/Books にコピーし、
/// メタデータだけを JSON で保存する。外部への送信は一切行わない。
@MainActor
final class LibraryStore: ObservableObject {
    @Published private(set) var books: [Book] = []

    private let fileManager = FileManager.default

    init() {
        load()
    }

    // MARK: - 場所

    var booksDirectory: URL {
        let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let url = documents.appendingPathComponent("Books", isDirectory: true)
        try? fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private var metadataURL: URL {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? fileManager.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("library.json")
    }

    func fileURL(for book: Book) -> URL {
        booksDirectory.appendingPathComponent(book.fileName)
    }

    // MARK: - 取り込み

    @discardableResult
    func importBook(from sourceURL: URL) throws -> Book {
        let needsScope = sourceURL.startAccessingSecurityScopedResource()
        defer { if needsScope { sourceURL.stopAccessingSecurityScopedResource() } }

        let ext = sourceURL.pathExtension
        guard let format = BookFormat(fileExtension: ext) else {
            throw ParseError.unsupportedFormat(ext.isEmpty ? "不明" : ext)
        }

        let originalName = sourceURL.lastPathComponent
        if let existing = books.first(where: { $0.fileName == originalName }) {
            return existing
        }

        let destinationName = uniqueFileName(for: originalName)
        let destinationURL = booksDirectory.appendingPathComponent(destinationName)
        if fileManager.fileExists(atPath: destinationURL.path) {
            try fileManager.removeItem(at: destinationURL)
        }
        try fileManager.copyItem(at: sourceURL, to: destinationURL)

        let book = Book(
            title: title(for: destinationURL, format: format),
            fileName: destinationName,
            format: format
        )
        books.insert(book, at: 0)
        save()
        return book
    }

    private func uniqueFileName(for name: String) -> String {
        var candidate = name
        var counter = 2
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension

        while books.contains(where: { $0.fileName == candidate })
            || fileManager.fileExists(atPath: booksDirectory.appendingPathComponent(candidate).path) {
            candidate = ext.isEmpty ? "\(base) \(counter)" : "\(base) \(counter).\(ext)"
            counter += 1
        }
        return candidate
    }

    /// メタデータのタイトルを優先し、無ければファイル名を使う。
    private func title(for url: URL, format: BookFormat) -> String {
        let fallback = (url.lastPathComponent as NSString).deletingPathExtension

        switch format {
        case .pdf:
            if let document = PDFDocument(url: url),
               let title = document.documentAttributes?[PDFDocumentAttribute.titleAttribute] as? String {
                let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty { return trimmed }
            }
        case .epub:
            if let title = EPUBParser.metadataTitle(from: url)?
                .trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty {
                return title
            }
        case .text:
            break
        }
        return fallback
    }

    // MARK: - 更新

    func delete(_ book: Book) {
        try? fileManager.removeItem(at: fileURL(for: book))
        DocumentCache.remove(bookID: book.id)
        books.removeAll { $0.id == book.id }
        save()
    }

    func delete(atOffsets offsets: IndexSet) {
        for index in offsets {
            guard books.indices.contains(index) else { continue }
            let book = books[index]
            try? fileManager.removeItem(at: fileURL(for: book))
            DocumentCache.remove(bookID: book.id)
        }
        books.remove(atOffsets: offsets)
        save()
    }

    func markOpened(_ bookID: UUID) {
        guard let index = books.firstIndex(where: { $0.id == bookID }) else { return }
        books[index].lastOpenedAt = Date()
        save()
    }

    func updateProgress(bookID: UUID, index progressIndex: Int, segmentCount: Int) {
        guard let index = books.firstIndex(where: { $0.id == bookID }) else { return }
        guard books[index].progressIndex != progressIndex || books[index].segmentCount != segmentCount
        else { return }
        books[index].progressIndex = max(0, progressIndex)
        books[index].segmentCount = segmentCount
        save()
    }

    func book(with id: UUID) -> Book? {
        books.first { $0.id == id }
    }

    // MARK: - 永続化

    private func load() {
        guard let data = try? Data(contentsOf: metadataURL),
              let stored = try? JSONDecoder().decode([Book].self, from: data) else { return }
        // 端末から実ファイルが消えている本は本棚からも外す。
        books = stored.filter { fileManager.fileExists(atPath: fileURL(for: $0).path) }
        if books.count != stored.count { save() }
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(books) else { return }
        try? data.write(to: metadataURL, options: .atomic)
    }
}
