//
//  SharedDefaults.swift
//
//  WatchApp 本体とウィジェット（文字盤コンプリケーション）は別プロセスなので、
//  App Group の共有領域を介して同じデータを読む。書き込むのは WatchStore だけ。
//
import Foundation

enum SharedDefaults {
    static let groupID = "group.jp.myproject.dailyapps"
    static let payloadKey = "watch.payload"
    static let receivedKey = "watch.receivedAt"

    static var suite: UserDefaults {
        UserDefaults(suiteName: groupID) ?? .standard
    }

    static func loadSnapshot() -> Snapshot {
        guard let json = suite.string(forKey: payloadKey), let snap = Snapshot.decode(json) else {
            return .empty
        }
        return snap
    }
}

/// コンプリケーション／ウィジェットをタップしたときに開く先。
/// 「書類・回覧・会議の期限トラッカー」がすでに対応している myproject://docs?id=xxx を
/// iPhone 側では使い、Watch 側は Watch アプリ自身の中で該当項目までスクロールする。
enum DeepLink {
    static func watchItemURL(id: String?) -> URL? {
        guard let id = id, !id.isEmpty else { return nil }
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? id
        return URL(string: "watchapp://item?id=" + encoded)
    }

    static func docsURL(id: String?) -> URL? {
        guard let id = id, !id.isEmpty else { return nil }
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? id
        return URL(string: "myproject://docs?id=" + encoded)
    }
}
