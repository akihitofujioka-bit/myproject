//
//  CalendarWriterPlugin.swift
//
//  会議や期限を iPhone のカレンダーへ直接書き込む Capacitor プラグイン。
//
//  ＜なぜ作るのか＞
//  これまでは .ics ファイルを共有シート経由で渡していたが、
//   ・「カレンダーに登録」を押すと共有の画面が出てしまい、操作が分かりにくい
//   ・同じ会議を登録し直すと、カレンダー側が別の予定として増やしてしまう
//  という2つの困りごとがあった（利用者からの指摘: 2026-09-24）。
//  EventKit で直接書けば、画面は出ず、識別子で同じ予定を上書きできる。
//
//  ・書き込むのは、このアプリから登録した予定だけ。ほかの予定は読み書きしない
//  ・外部への送信は行わない
//
import Foundation
import EventKit
import Capacitor

@objc(CalendarWriterPlugin)
public class CalendarWriterPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "CalendarWriterPlugin"
    public let jsName = "CalendarWriter"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestAccess", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "saveEvents", returnType: CAPPluginReturnPromise)
    ]

    private let store = EKEventStore()

    private static func isAuthorized() -> Bool {
        let status = EKEventStore.authorizationStatus(for: .event)
        if #available(iOS 17.0, *) {
            return status == .fullAccess
        }
        return status == .authorized
    }

    @objc func isSupported(_ call: CAPPluginCall) {
        call.resolve(["supported": true, "authorized": Self.isAuthorized()])
    }

    /*
     * 書き込みだけなら iOS 17 以降は write-only の許可でも足りるが、
     * 「前に入れた予定を書き換える」には読み取りが要るため full access を求める。
     * 読み取り側（CalendarReaderPlugin）と同じ許可なので、確認は1回で済む。
     */
    @objc func requestAccess(_ call: CAPPluginCall) {
        if #available(iOS 17.0, *) {
            store.requestFullAccessToEvents { granted, error in
                call.resolve(["granted": granted, "reason": error?.localizedDescription ?? ""])
            }
        } else {
            store.requestAccess(to: .event) { granted, error in
                call.resolve(["granted": granted, "reason": error?.localizedDescription ?? ""])
            }
        }
    }

    /*
     * 予定をまとめて書き込む。
     *
     * events の各要素:
     *   key       … アプリ側がこの予定を見分けるための文字列（戻り値で対応づける）
     *   eventId   … 前回書き込んだときの識別子。あれば上書きする（重複を防ぐ）
     *   title, date（YYYY-MM-DD）, startTime / endTime（HH:MM、空なら終日）
     *   location, notes, alarms（何分前に知らせるかの配列）
     *
     * 戻り値:
     *   { ok, saved: [{ key, eventId, updated }], failed: [{ key, reason }] }
     */
    @objc func saveEvents(_ call: CAPPluginCall) {
        guard Self.isAuthorized() else {
            call.resolve(["ok": false, "reason": "not-authorized", "saved": [], "failed": []])
            return
        }
        guard let items = call.getArray("events", JSObject.self), !items.isEmpty else {
            call.resolve(["ok": false, "reason": "no-events", "saved": [], "failed": []])
            return
        }
        guard let calendar = store.defaultCalendarForNewEvents else {
            call.resolve(["ok": false, "reason": "no-calendar", "saved": [], "failed": []])
            return
        }

        var saved: [[String: Any]] = []
        var failed: [[String: Any]] = []

        for item in items {
            let key = item["key"] as? String ?? ""
            guard let start = date(from: item["date"] as? String, time: item["startTime"] as? String) else {
                failed.append(["key": key, "reason": "bad-date"])
                continue
            }
            let allDay = ((item["startTime"] as? String) ?? "").isEmpty

            // 前に書き込んだ予定があれば、それを書き換える（無ければ新しく作る）
            var event: EKEvent?
            var updated = false
            if let id = item["eventId"] as? String, !id.isEmpty, let found = store.event(withIdentifier: id) {
                if found.calendar.allowsContentModifications {
                    event = found
                    updated = true
                }
            }
            let target = event ?? EKEvent(eventStore: store)
            if !updated { target.calendar = calendar }

            target.title = item["title"] as? String ?? "（件名なし）"
            target.location = item["location"] as? String
            target.notes = item["notes"] as? String
            target.isAllDay = allDay
            target.startDate = start
            if allDay {
                target.endDate = start
            } else if let end = date(from: item["date"] as? String, time: item["endTime"] as? String), end > start {
                target.endDate = end
            } else {
                target.endDate = start.addingTimeInterval(60 * 60)
            }

            // 以前に付けた通知は消してから付け直す（登録し直すたびに増えないように）
            for alarm in target.alarms ?? [] { target.removeAlarm(alarm) }
            let alarms = (item["alarms"] as? [Any])?.compactMap { ($0 as? NSNumber)?.intValue } ?? []
            for minutes in alarms {
                target.addAlarm(EKAlarm(relativeOffset: -Double(minutes) * 60))
            }

            do {
                try store.save(target, span: .thisEvent, commit: false)
                saved.append(["key": key, "eventId": target.eventIdentifier ?? "", "updated": updated])
            } catch {
                failed.append(["key": key, "reason": error.localizedDescription])
            }
        }

        do {
            try store.commit()
        } catch {
            call.resolve(["ok": false, "reason": error.localizedDescription, "saved": [], "failed": failed])
            return
        }
        call.resolve(["ok": failed.isEmpty, "reason": "", "saved": saved, "failed": failed])
    }

    /// "2026-09-24" と "13:30" を、端末の時間帯での日時にする（時刻が空なら0時）
    private func date(from day: String?, time: String?) -> Date? {
        guard let day = day, !day.isEmpty else { return nil }
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var comps = DateComponents()
        comps.year = parts[0]
        comps.month = parts[1]
        comps.day = parts[2]
        let hm = (time ?? "").split(separator: ":").compactMap { Int($0) }
        comps.hour = hm.count > 0 ? hm[0] : 0
        comps.minute = hm.count > 1 ? hm[1] : 0
        return Calendar.current.date(from: comps)
    }
}
