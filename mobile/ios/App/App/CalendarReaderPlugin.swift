//
//  CalendarReaderPlugin.swift
//
//  iPhone のカレンダーから予定を読み取り、会議として取り込むための Capacitor プラグイン。
//
//  ・読み取りだけを行う。このアプリからカレンダーへの書き込みは、これまで通り
//    .ics ファイル経由（ics.js）で行う。読み取った予定をそのまま書き戻すと
//    同じ予定が重複して増えるため、書き込みとは別の経路にしている
//  ・EventKit（iOS 標準）を使う。取得した予定は端末の外へは送らない
//
import Foundation
import EventKit
import Capacitor

@objc(CalendarReaderPlugin)
public class CalendarReaderPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "CalendarReaderPlugin"
    public let jsName = "CalendarReader"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestAccess", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "listCalendars", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "listEvents", returnType: CAPPluginReturnPromise)
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

    @objc func requestAccess(_ call: CAPPluginCall) {
        store.requestAccess(to: .event) { granted, error in
            call.resolve(["granted": granted, "reason": error?.localizedDescription ?? ""])
        }
    }

    @objc func listCalendars(_ call: CAPPluginCall) {
        guard Self.isAuthorized() else {
            call.resolve(["calendars": []])
            return
        }
        let calendars = store.calendars(for: .event).map { cal -> [String: Any] in
            [
                "id": cal.calendarIdentifier,
                "title": cal.title,
                "source": cal.source?.title ?? ""
            ]
        }
        call.resolve(["calendars": calendars])
    }

    /// 選んだカレンダーの予定を、今日から指定日数分だけ返す（既定60日）。
    @objc func listEvents(_ call: CAPPluginCall) {
        guard Self.isAuthorized() else {
            call.resolve(["events": [], "reason": "not-authorized"])
            return
        }
        let ids = call.getArray("calendarIds", String.self) ?? []
        guard !ids.isEmpty else {
            call.resolve(["events": [], "reason": "no-calendar-selected"])
            return
        }
        let calendars = store.calendars(for: .event).filter { ids.contains($0.calendarIdentifier) }
        guard !calendars.isEmpty else {
            call.resolve(["events": [], "reason": "calendar-not-found"])
            return
        }
        let days = call.getInt("days") ?? 60
        let cal = Calendar.current
        let start = cal.startOfDay(for: Date())
        guard let end = cal.date(byAdding: .day, value: max(1, days), to: start) else {
            call.resolve(["events": [], "reason": "invalid-range"])
            return
        }

        let dateFmt = DateFormatter()
        dateFmt.locale = Locale(identifier: "en_US_POSIX")
        dateFmt.dateFormat = "yyyy-MM-dd"
        let timeFmt = DateFormatter()
        timeFmt.locale = Locale(identifier: "en_US_POSIX")
        timeFmt.dateFormat = "HH:mm"

        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
        let events = store.events(matching: predicate)
            .sorted { $0.startDate < $1.startDate }
            .map { ev -> [String: Any] in
                [
                    "id": ev.eventIdentifier ?? "",
                    "title": ev.title ?? "",
                    "date": dateFmt.string(from: ev.startDate),
                    "startTime": ev.isAllDay ? "" : timeFmt.string(from: ev.startDate),
                    "endTime": ev.isAllDay ? "" : timeFmt.string(from: ev.endDate),
                    "place": ev.location ?? ""
                ]
            }
        call.resolve(["events": events])
    }
}
