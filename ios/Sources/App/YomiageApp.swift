import SwiftUI

@main
struct YomiageApp: App {
    @StateObject private var library = LibraryStore()
    @StateObject private var speech = SpeechController()

    var body: some Scene {
        WindowGroup {
            LibraryView()
                .environmentObject(library)
                .environmentObject(speech)
                .onOpenURL { url in
                    // 「他のアプリで開く」から渡ってきたファイルを取り込む。
                    try? library.importBook(from: url)
                }
        }
    }
}
