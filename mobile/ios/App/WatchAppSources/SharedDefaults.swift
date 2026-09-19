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
