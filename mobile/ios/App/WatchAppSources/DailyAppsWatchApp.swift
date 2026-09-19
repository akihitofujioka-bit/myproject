//
//  DailyAppsWatchApp.swift
//
//  Apple Watch 側アプリの入口。
//  iPhone の「日常アプリ」から送られた一覧を表示するだけの、見るためのアプリ。
//
import SwiftUI

@main
struct DailyAppsWatchApp: App {
    @StateObject private var store = WatchStore()

    var body: some Scene {
        WindowGroup {
            ContentView(store: store)
                .onOpenURL { url in
                    // コンプリケーションをタップしたときに、該当の項目までスクロールする
                    guard url.host == "item" else { return }
                    let id = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                        .queryItems?.first(where: { $0.name == "id" })?.value
                    store.focusedId = id
                }
        }
    }
}
