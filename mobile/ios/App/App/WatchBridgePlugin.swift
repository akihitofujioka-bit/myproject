//
//  WatchBridgePlugin.swift
//
//  Apple Watch へ「今日の会議・期限・買い物リスト」を渡す Capacitor プラグイン。
//
//  ・JS 側（apps/shared/watch.js）が作った JSON を受け取る
//  ・WatchConnectivity の applicationContext で Apple Watch に渡す
//    （applicationContext は「最新の状態だけを上書きで渡す」仕組みで、
//     何度呼んでも溜まらない。回数制限も無いため、保存のたびに呼んでよい）
//  ・Apple Watch が無い／未装着でも失敗にはしない。次に繋がったときに届く
//  ・受け取った内容は UserDefaults にも残す。Watch 側が「前回の内容」を
//    出せるようにするためで、外部へは一切送らない
//
import Foundation
import Capacitor
import WatchConnectivity
import WidgetKit

@objc(WatchBridgePlugin)
public class WatchBridgePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "WatchBridgePlugin"
    public let jsName = "WatchBridge"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "sync", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setBackground", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise)
    ]

    private let session = WatchSessionHolder.shared

    override public func load() {
        session.activate()
    }

    /// Apple Watch と繋げられる端末かどうか（iPad などでは false）
    @objc func isSupported(_ call: CAPPluginCall) {
        call.resolve([
            "supported": WCSession.isSupported(),
            "paired": session.isPaired,
            "appInstalled": session.isWatchAppInstalled
        ])
    }

    /// JS から受け取った JSON を Apple Watch へ渡す。
    /// 渡せなかった場合も reject せず { ok: false, reason: ... } を返す
    /// （Apple Watch を持っていない利用者の画面にエラーを出さないため）。
    @objc func sync(_ call: CAPPluginCall) {
        guard let payload = call.getString("payload"), !payload.isEmpty else {
            call.resolve(["ok": false, "reason": "empty-payload"])
            return
        }
        let result = session.send(payload: payload)
        call.resolve(["ok": result.ok, "reason": result.reason])
    }

    /// キャラクター写真を Apple Watch の背景として渡す。
    /// 写真が無いときは clear を受け取り、Watch 側の保存済み背景を消す。
    @objc func setBackground(_ call: CAPPluginCall) {
        if call.getBool("clear") == true {
            let result = session.clearBackground()
            call.resolve(["ok": result.ok, "reason": result.reason])
            return
        }

        guard let encoded = call.getString("data"),
              let data = Data(base64Encoded: encoded),
              !data.isEmpty else {
            call.reject("invalid-background")
            return
        }
        let result = session.sendBackground(data: data)
        call.resolve(["ok": result.ok, "reason": result.reason])
    }
}

/// WCSession はアプリに1つだけ。プラグインの生成タイミングに左右されないよう分けている
final class WatchSessionHolder: NSObject, WCSessionDelegate {
    static let shared = WatchSessionHolder()

    /// Watch 側が「前回の内容」を出せるよう、最後に渡した内容を残す鍵
    static let payloadKey = "watch.payload"
    static let updatedKey = "watch.updatedAt"

    private var activated = false

    func activate() {
        guard WCSession.isSupported() else { return }
        guard !activated else { return }
        activated = true
        let s = WCSession.default
        s.delegate = self
        s.activate()
    }

    var isPaired: Bool {
        guard WCSession.isSupported() else { return false }
        return WCSession.default.isPaired
    }

    var isWatchAppInstalled: Bool {
        guard WCSession.isSupported() else { return false }
        return WCSession.default.isWatchAppInstalled
    }

    /// Watch へ送れる状態かを、一覧と背景で同じ基準で確かめる
    private func readySession() -> (session: WCSession?, reason: String) {
        guard WCSession.isSupported() else { return (nil, "not-supported") }
        activate()
        let session = WCSession.default
        guard session.activationState == .activated else { return (nil, "not-activated") }
        guard session.isPaired else { return (nil, "no-watch") }
        guard session.isWatchAppInstalled else { return (nil, "app-not-installed") }
        return (session, "")
    }

    private func cancelPendingBackgroundTransfers(_ session: WCSession) {
        session.outstandingFileTransfers
            .filter { $0.file.metadata?["kind"] as? String == "background" }
            .forEach { $0.cancel() }
    }

    func sendBackground(data: Data) -> (ok: Bool, reason: String) {
        let ready = readySession()
        guard let session = ready.session else { return (false, ready.reason) }

        // 送信待ちの前の写真と同じファイルを上書きしないよう、送るたびに別の名前にする
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("watch-background-\(UUID().uuidString).jpg")
        do {
            try data.write(to: url, options: .atomic)
        } catch {
            return (false, error.localizedDescription)
        }

        cancelPendingBackgroundTransfers(session)
        session.transferFile(url, metadata: ["kind": "background"])
        return (true, "")
    }

    func clearBackground() -> (ok: Bool, reason: String) {
        let ready = readySession()
        guard let session = ready.session else { return (false, ready.reason) }
        // 消去後に古い背景が届かないよう、送信待ちの写真も取り消す
        cancelPendingBackgroundTransfers(session)
        session.transferUserInfo(["kind": "background-clear"])
        return (true, "")
    }

    func send(payload: String) -> (ok: Bool, reason: String) {
        UserDefaults.standard.set(payload, forKey: WatchSessionHolder.payloadKey)
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: WatchSessionHolder.updatedKey)

        // iPhoneのロック画面ウィジェット（次の予定）にも同じ内容を渡す
        SharedDefaults.suite.set(payload, forKey: SharedDefaults.payloadKey)
        SharedDefaults.suite.set(Date().timeIntervalSince1970, forKey: SharedDefaults.receivedKey)
        WidgetCenter.shared.reloadAllTimelines()

        let ready = readySession()
        guard let s = ready.session else { return (false, ready.reason) }
        do {
            // 同じ内容を続けて渡すと無視されることがあるため、時刻を添えて必ず変化させる
            try s.updateApplicationContext([
                "payload": payload,
                "sentAt": Date().timeIntervalSince1970
            ])
            return (true, "")
        } catch {
            return (false, error.localizedDescription)
        }
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        if let error = error {
            CAPLog.print("⚡️  WatchBridge: 接続の開始に失敗しました（\(error.localizedDescription)）")
        }
    }

    /// Watch 側から「最新をください」と頼まれたときに、控えをそのまま返す
    func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        let payload = UserDefaults.standard.string(forKey: WatchSessionHolder.payloadKey) ?? ""
        replyHandler(["payload": payload])
    }

    // iPhone 側では必須。Watch を付け替えたときに再度使えるようにする
    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        WCSession.default.activate()
    }
}
