import SwiftUI
import UniformTypeIdentifiers

/// 本棚。ファイルの取り込みと、読み上げ画面への入口。
struct LibraryView: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var speech: SpeechController

    @State private var isImporting = false
    @State private var errorMessage: String?

    private static let importableTypes: [UTType] = {
        var types: [UTType] = [.pdf, .epub, .plainText]
        if let markdown = UTType("net.daringfireball.markdown") { types.append(markdown) }
        return types
    }()

    var body: some View {
        NavigationStack {
            Group {
                if library.books.isEmpty {
                    emptyState
                } else {
                    bookList
                }
            }
            .navigationTitle("本棚")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        isImporting = true
                    } label: {
                        Label("本を追加", systemImage: "plus")
                    }
                }
            }
            .fileImporter(
                isPresented: $isImporting,
                allowedContentTypes: Self.importableTypes,
                allowsMultipleSelection: true
            ) { result in
                handleImport(result)
            }
            .alert("読み込めませんでした", isPresented: errorBinding) {
                Button("OK", role: .cancel) { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
            .navigationDestination(for: Book.self) { book in
                ReaderView(book: book)
            }
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )
    }

    private var bookList: some View {
        List {
            ForEach(library.books) { book in
                NavigationLink(value: book) {
                    BookRow(book: book, isCurrent: speech.bookID == book.id && speech.isPlaying)
                }
            }
            .onDelete { offsets in
                // 再生中の本を消したら読み上げも止める。
                if let current = speech.bookID,
                   offsets.contains(where: { library.books[$0].id == current }) {
                    speech.stop()
                }
                library.delete(atOffsets: offsets)
            }
        }
        .listStyle(.plain)
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("本がありません", systemImage: "books.vertical")
        } description: {
            Text("右上の ＋ から PDF・EPUB・テキスト（.txt / .md）を追加してください。\niCloud Drive や「ファイル」アプリの共有メニューからこのアプリを選んでも取り込めます。")
        } actions: {
            Button("本を追加") { isImporting = true }
                .buttonStyle(.borderedProminent)
        }
    }

    private func handleImport(_ result: Result<[URL], Error>) {
        switch result {
        case .failure(let error):
            errorMessage = error.localizedDescription
        case .success(let urls):
            var failures: [String] = []
            for url in urls {
                do {
                    try library.importBook(from: url)
                } catch {
                    failures.append("\(url.lastPathComponent): \(error.localizedDescription)")
                }
            }
            if !failures.isEmpty { errorMessage = failures.joined(separator: "\n") }
        }
    }
}

private struct BookRow: View {
    let book: Book
    let isCurrent: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: book.format.systemImage)
                .font(.title2)
                .foregroundStyle(.secondary)
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 4) {
                Text(book.title)
                    .font(.body)
                    .lineLimit(2)

                HStack(spacing: 6) {
                    Text(book.format.displayName)
                    if book.segmentCount > 0 {
                        Text("・")
                        Text("\(Int(book.progress * 100))% 読了")
                    }
                    if isCurrent {
                        Text("・")
                        Label("再生中", systemImage: "speaker.wave.2.fill")
                            .labelStyle(.titleAndIcon)
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                if book.segmentCount > 0, book.progress > 0 {
                    ProgressView(value: book.progress)
                        .progressViewStyle(.linear)
                }
            }
        }
        .padding(.vertical, 4)
    }
}
