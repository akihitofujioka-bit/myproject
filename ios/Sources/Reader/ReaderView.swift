import SwiftUI

/// 読み上げ画面。本文を文単位で並べ、読み上げ中の文を追いかける。
struct ReaderView: View {
    let book: Book

    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var speech: SpeechController

    @State private var phase: Phase = .loading
    @State private var showSettings = false
    @State private var followsSpeech = true

    private enum Phase {
        case loading
        case ready(BookDocument)
        case failed(String)
    }

    var body: some View {
        Group {
            switch phase {
            case .loading:
                ProgressView("本文を解析しています…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .failed(let message):
                ContentUnavailableView {
                    Label("読み上げできません", systemImage: "exclamationmark.triangle")
                } description: {
                    Text(message)
                }
            case .ready(let document):
                readerBody(document: document)
            }
        }
        .navigationTitle(book.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showSettings = true
                } label: {
                    Label("読み上げ設定", systemImage: "slider.horizontal.3")
                }
                .disabled(isLoading)
            }
        }
        .sheet(isPresented: $showSettings) {
            SpeechSettingsView()
                .environmentObject(speech)
        }
        .task { await load() }
    }

    private var isLoading: Bool {
        if case .loading = phase { return true }
        return false
    }

    @ViewBuilder
    private func readerBody(document: BookDocument) -> some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(document.segments) { segment in
                            SegmentRow(
                                segment: segment,
                                isCurrent: segment.id == speech.currentIndex,
                                spokenRange: segment.id == speech.currentIndex ? speech.spokenRange : nil
                            )
                            .id(segment.id)
                            .onTapGesture {
                                followsSpeech = true
                                speech.seek(to: segment.id)
                            }
                        }
                    }
                    .padding(.horizontal)
                    .padding(.vertical, 12)
                }
                .onChange(of: speech.currentIndex) { _, newValue in
                    guard followsSpeech else { return }
                    withAnimation(.easeInOut(duration: 0.25)) {
                        proxy.scrollTo(newValue, anchor: .center)
                    }
                }
                .onAppear {
                    proxy.scrollTo(speech.currentIndex, anchor: .center)
                }
                .simultaneousGesture(
                    // 手で読み位置を離れたら自動スクロールを止める。
                    DragGesture().onChanged { _ in followsSpeech = false }
                )
            }

            PlayerBar(
                document: document,
                followsSpeech: $followsSpeech
            )
        }
    }

    private func load() async {
        // 同じ本を開き直した場合は解析済みの状態をそのまま使う。
        if speech.bookID == book.id, let document = speech.document {
            phase = .ready(document)
            bindProgress(segmentCount: document.segments.count)
            return
        }

        let fileURL = library.fileURL(for: book)
        let target = book

        do {
            let document = try await Task.detached(priority: .userInitiated) {
                try DocumentParser.loadDocument(for: target, fileURL: fileURL)
            }.value

            speech.prepare(document: document, book: target)
            library.markOpened(target.id)
            bindProgress(segmentCount: document.segments.count)
            phase = .ready(document)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func bindProgress(segmentCount: Int) {
        library.updateProgress(
            bookID: book.id,
            index: speech.currentIndex,
            segmentCount: segmentCount
        )
        speech.onProgress = { bookID, index in
            library.updateProgress(bookID: bookID, index: index, segmentCount: segmentCount)
        }
    }
}

/// 本文 1 文ぶんの表示。読み上げ中は行を強調し、発話位置を色で示す。
private struct SegmentRow: View {
    let segment: Segment
    let isCurrent: Bool
    let spokenRange: NSRange?

    var body: some View {
        Text(attributedText)
            .font(segment.isHeading ? .title3.bold() : .body)
            .lineSpacing(6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, segment.isHeading ? 8 : 4)
            .padding(.horizontal, 8)
            .background {
                RoundedRectangle(cornerRadius: 8)
                    .fill(isCurrent ? Color.accentColor.opacity(0.15) : Color.clear)
            }
            .contentShape(Rectangle())
    }

    private var attributedText: AttributedString {
        var attributed = AttributedString(segment.text)
        guard isCurrent else { return attributed }

        attributed.foregroundColor = .primary
        guard let spokenRange,
              let range = Range(spokenRange, in: segment.text) else { return attributed }

        let start = segment.text.distance(from: segment.text.startIndex, to: range.lowerBound)
        let length = segment.text.distance(from: range.lowerBound, to: range.upperBound)
        guard start >= 0, length > 0, start + length <= segment.text.count else { return attributed }

        let lower = attributed.index(attributed.startIndex, offsetByCharacters: start)
        let upper = attributed.index(lower, offsetByCharacters: length)
        attributed[lower..<upper].foregroundColor = .accentColor
        attributed[lower..<upper].inlinePresentationIntent = .stronglyEmphasized
        return attributed
    }
}
