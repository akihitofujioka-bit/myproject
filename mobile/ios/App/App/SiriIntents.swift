//
//  SiriIntents.swift
//
//  Siri・ショートカットから呼べる操作（App Intents）。
//
//  ・撮影・追加の操作は、アプリを開いて myproject://… の URL を Web 画面へ渡す
//    （受け取るのは apps/shared/deeplink.js。保存は利用者が画面で押す）
//  ・予定・期限・買い物リストを読み上げる操作は、Apple Watch 用に App Group へ
//    残している一覧（SharedDefaults）を読むだけで、外部へは一切送らない
//  ・読み上げる操作は、ロック中は答えない（requiresAuthentication）
//
import Foundation
import AppIntents
import UIKit
import Capacitor

// MARK: - Web 画面へ URL を渡す

/// Siri から開いた直後は Web 画面の読み込みが終わっていないことがあるため、
/// 読み込みが終わるまで少し待ってから、Capacitor の appUrlOpen として渡す。
enum IntentRouter {
    @MainActor
    static func open(_ url: URL, attempt: Int = 0) {
        let ready = bridgeViewController()?.webView.map { !$0.isLoading && $0.url != nil } ?? false
        if ready || attempt >= 20 {
            // 画面の読み込み直後は JS の受け口（addListener）がまだ無いことがあるので、少し間を置く
            let delay: TimeInterval = attempt == 0 ? 0 : 0.8
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                _ = ApplicationDelegateProxy.shared.application(UIApplication.shared, open: url, options: [:])
            }
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            open(url, attempt: attempt + 1)
        }
    }

    @MainActor
    private static func bridgeViewController() -> CAPBridgeViewController? {
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows {
                if let controller = window.rootViewController as? CAPBridgeViewController {
                    return controller
                }
            }
        }
        return nil
    }

    static func url(_ host: String, _ name: String, _ value: String) -> URL? {
        var components = URLComponents()
        components.scheme = "myproject"
        components.host = host
        components.queryItems = [URLQueryItem(name: name, value: value)]
        return components.url
    }
}

// MARK: - 撮影を始める（B）

@available(iOS 16.0, *)
struct ScanCardIntent: AppIntent {
    static var title: LocalizedStringResource = "名刺を撮る"
    static var description = IntentDescription("名刺アプリを開いて撮影を始めます。")
    static var openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        if let url = IntentRouter.url("meishi", "action", "scan") { IntentRouter.open(url) }
        return .result()
    }
}

@available(iOS 16.0, *)
struct ScanDocumentIntent: AppIntent {
    static var title: LocalizedStringResource = "書類を撮る"
    static var description = IntentDescription("書類・やることアプリを開いて撮影を始めます。")
    static var openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        if let url = IntentRouter.url("docs", "action", "scan") { IntentRouter.open(url) }
        return .result()
    }
}

@available(iOS 16.0, *)
struct ScanReceiptIntent: AppIntent {
    static var title: LocalizedStringResource = "レシートを撮る"
    static var description = IntentDescription("家計簿を開いてレシートの撮影を始めます。")
    static var openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        if let url = IntentRouter.url("kakeibo", "action", "scan") { IntentRouter.open(url) }
        return .result()
    }
}

// MARK: - 追加する（D）

@available(iOS 16.0, *)
struct AddFridgeItemIntent: AppIntent {
    static var title: LocalizedStringResource = "冷蔵庫に追加"
    static var description = IntentDescription("冷蔵庫アプリの追加欄に品名を入れて開きます。保存は画面で押します。")
    static var openAppWhenRun = true

    @Parameter(title: "品名", requestValueDialog: "何を追加しますか？")
    var name: String

    @MainActor
    func perform() async throws -> some IntentResult {
        let text = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty, let url = IntentRouter.url("fridge", "add", text) { IntentRouter.open(url) }
        return .result()
    }
}

@available(iOS 16.0, *)
struct AddTodoIntent: AppIntent {
    static var title: LocalizedStringResource = "やることを追加"
    static var description = IntentDescription("書類・やることアプリの入力欄に件名を入れて開きます。保存は画面で押します。")
    static var openAppWhenRun = true

    @Parameter(title: "件名", requestValueDialog: "何をやりますか？")
    var title: String

    @MainActor
    func perform() async throws -> some IntentResult {
        let text = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty, let url = IntentRouter.url("docs", "todo", text) { IntentRouter.open(url) }
        return .result()
    }
}

// MARK: - 読み上げる（C）。ロック中は答えない

/// 一覧は最後に壱師アプリを開いたときの内容なので、古いときはそう添える
private func staleNote(_ snapshot: Snapshot) -> String {
    guard let today = snapshot.today, daysUntil(today) != 0 else { return "" }
    return "（最後にアプリを開いた時点の内容です）"
}

@available(iOS 16.0, *)
struct TodayMeetingsIntent: AppIntent {
    static var title: LocalizedStringResource = "今日の予定"
    static var description = IntentDescription("今日の会議・予定を読み上げます。")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let snapshot = SharedDefaults.loadSnapshot()
        let today = (snapshot.meetings ?? []).filter { $0.remaining == 0 }
        if today.isEmpty {
            return .result(dialog: IntentDialog(stringLiteral: "今日の予定はありません。" + staleNote(snapshot)))
        }
        let lines = today.prefix(5).map { meeting -> String in
            let time = meeting.time.map { $0 + "から" } ?? ""
            let place = meeting.place.map { "、場所は" + $0 } ?? ""
            return time + (meeting.title ?? "件名なし") + place
        }
        let more = today.count > 5 ? "ほか\(today.count - 5)件。" : ""
        let text = "今日の予定は\(today.count)件です。" + lines.joined(separator: "。") + "。" + more + staleNote(snapshot)
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

@available(iOS 16.0, *)
struct UpcomingDeadlinesIntent: AppIntent {
    static var title: LocalizedStringResource = "期限の近い書類"
    static var description = IntentDescription("1週間以内に期限が来る書類・やることを読み上げます。")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let snapshot = SharedDefaults.loadSnapshot()
        let near = (snapshot.deadlines ?? [])
            .filter { ($0.remaining ?? Int.max) <= 7 }
            .sorted { ($0.remaining ?? 0) < ($1.remaining ?? 0) }
        if near.isEmpty {
            return .result(dialog: IntentDialog(stringLiteral: "1週間以内の期限はありません。" + staleNote(snapshot)))
        }
        let lines = near.prefix(5).map { (dayLabel($0.remaining)) + "、" + ($0.title ?? "件名なし") }
        let more = near.count > 5 ? "ほか\(near.count - 5)件。" : ""
        let text = "期限の近いものは\(near.count)件です。" + lines.joined(separator: "。") + "。" + more + staleNote(snapshot)
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

@available(iOS 16.0, *)
struct ShoppingListIntent: AppIntent {
    static var title: LocalizedStringResource = "買い物リスト"
    static var description = IntentDescription("使い切って買い足すものを読み上げます。")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let snapshot = SharedDefaults.loadSnapshot()
        let names = (snapshot.shopping ?? []).compactMap { $0.name }.filter { !$0.isEmpty }
        if names.isEmpty {
            return .result(dialog: IntentDialog(stringLiteral: "買い物リストは空です。" + staleNote(snapshot)))
        }
        let text = "買うものは\(names.count)つです。" + names.prefix(10).joined(separator: "、") + "。" + staleNote(snapshot)
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

// MARK: - Siri に話しかける言葉

@available(iOS 16.0, *)
struct DailyAppsShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: ScanCardIntent(), phrases: [
            "\(.applicationName)で名刺を撮って", "\(.applicationName)で名刺を撮る"
        ])
        AppShortcut(intent: ScanDocumentIntent(), phrases: [
            "\(.applicationName)で書類を撮って", "\(.applicationName)で書類を撮る"
        ])
        AppShortcut(intent: ScanReceiptIntent(), phrases: [
            "\(.applicationName)でレシートを撮って", "\(.applicationName)でレシートを撮る"
        ])
        AppShortcut(intent: AddFridgeItemIntent(), phrases: [
            "\(.applicationName)で冷蔵庫に追加", "\(.applicationName)の冷蔵庫に追加して"
        ])
        AppShortcut(intent: AddTodoIntent(), phrases: [
            "\(.applicationName)でやることを追加", "\(.applicationName)のやることに追加して"
        ])
        AppShortcut(intent: TodayMeetingsIntent(), phrases: [
            "\(.applicationName)で今日の予定", "\(.applicationName)の今日の予定を教えて"
        ])
        AppShortcut(intent: UpcomingDeadlinesIntent(), phrases: [
            "\(.applicationName)で期限の近い書類", "\(.applicationName)の期限を教えて"
        ])
        AppShortcut(intent: ShoppingListIntent(), phrases: [
            "\(.applicationName)で買い物リスト", "\(.applicationName)の買い物リストを教えて"
        ])
    }
}
