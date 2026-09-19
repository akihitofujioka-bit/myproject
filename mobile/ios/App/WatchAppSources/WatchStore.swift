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
import WatchConnectivity

final class WatchStore: NSObject, ObservableObject, WCSessionDelegate {
    @Published var snapshot: Snapshot = .empty
    @Published var receivedAt: Date?
    @Published var isRequesting = false

    private let payloadKey = "watch.payload"
    private let receivedKey = "watch.receivedAt"

    override init() {
        super.init()
        loadCached()
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    private func loadCached() {
        if let json = UserDefaults.standard.string(forKey: payloadKey),
           let snap = Snapshot.decode(json) {
            snapshot = snap
        }
        let t = UserDefaults.standard.double(forKey: receivedKey)
        if t > 0 { receivedAt = Date(timeIntervalSince1970: t) }
    }

    private func apply(_ json: String) {
        guard let snap = Snapshot.decode(json) else { return }
        UserDefaults.standard.set(json, forKey: payloadKey)
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: receivedKey)
        DispatchQueue.main.async {
            self.snapshot = snap
            self.receivedAt = Date()
            self.isRequesting = false
        }
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
}
