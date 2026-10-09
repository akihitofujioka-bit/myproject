//
//  WatchStore.swift
//
//  iPhone から届いた一覧を保持する。
//
//  ・受け取りは WatchConnectivity の applicationContext（最新の状態が上書きで届く）
//  ・受け取った内容は端末内（UserDefaults）に控え、通信できないときも前回の内容を出す
//  ・外部のサーバーとは通信しない。iPhone との直接通信だけ
//
import Foundation
import WatchKit
import WatchConnectivity
import WidgetKit

final class WatchStore: NSObject, ObservableObject, WCSessionDelegate {
    @Published var snapshot: Snapshot = .empty
    @Published var receivedAt: Date?
    @Published var isRequesting = false
    @Published var background: UIImage?
    /// コンプリケーションをタップして開いたときに、その項目までスクロールするための印
    @Published var focusedId: String?

    private var store: UserDefaults { SharedDefaults.suite }
    private let payloadKey = SharedDefaults.payloadKey
    private let receivedKey = SharedDefaults.receivedKey

    override init() {
        super.init()
        loadCached()
        loadBackground()
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    private func loadCached() {
        if let json = store.string(forKey: payloadKey),
           let snap = Snapshot.decode(json) {
            snapshot = snap
        }
        let t = store.double(forKey: receivedKey)
        if t > 0 { receivedAt = Date(timeIntervalSince1970: t) }
    }

    private func backgroundURL(createDirectory: Bool) -> URL? {
        let manager = FileManager.default
        guard let directory = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return nil
        }
        if createDirectory {
            do {
                try manager.createDirectory(at: directory, withIntermediateDirectories: true)
            } catch {
                return nil
            }
        }
        return directory.appendingPathComponent("background.jpg")
    }

    private func loadBackground() {
        guard let url = backgroundURL(createDirectory: false) else { return }
        background = UIImage(contentsOfFile: url.path)
    }

    private func receiveBackground(_ file: WCSessionFile) {
        guard file.metadata?["kind"] as? String == "background",
              let destination = backgroundURL(createDirectory: true) else { return }
        do {
            let manager = FileManager.default
            if manager.fileExists(atPath: destination.path) {
                _ = try manager.replaceItemAt(destination, withItemAt: file.fileURL)
            } else {
                try manager.moveItem(at: file.fileURL, to: destination)
            }
            let image = UIImage(contentsOfFile: destination.path)
            DispatchQueue.main.async {
                self.background = image
            }
        } catch {
            // 一覧の表示は止めず、次の背景送信を待つ
        }
    }

    private func clearBackground() {
        if let url = backgroundURL(createDirectory: false) {
            try? FileManager.default.removeItem(at: url)
        }
        DispatchQueue.main.async {
            self.background = nil
        }
    }

    private func apply(_ json: String) {
        guard let snap = Snapshot.decode(json) else { return }
        store.set(json, forKey: payloadKey)
        store.set(Date().timeIntervalSince1970, forKey: receivedKey)
        DispatchQueue.main.async {
            self.snapshot = snap
            self.receivedAt = Date()
            self.isRequesting = false
        }
        // 文字盤のコンプリケーション（次の予定）にも新しい内容を反映する
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// 手動の更新。iPhone 側が起動していれば最新を返してくれる
    func requestLatest() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { return }
        isRequesting = true
        session.sendMessage(["request": "latest"], replyHandler: { reply in
            if let json = reply["payload"] as? String, !json.isEmpty {
                self.apply(json)
            } else {
                DispatchQueue.main.async { self.isRequesting = false }
            }
        }, errorHandler: { _ in
            DispatchQueue.main.async { self.isRequesting = false }
        })
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        // 起動時にすでに届いている内容があれば取り込む
        if let json = session.receivedApplicationContext["payload"] as? String, !json.isEmpty {
            apply(json)
        }
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        if let json = applicationContext["payload"] as? String, !json.isEmpty {
            apply(json)
        }
    }

    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        receiveBackground(file)
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        if userInfo["kind"] as? String == "background-clear" {
            clearBackground()
        }
    }
}
