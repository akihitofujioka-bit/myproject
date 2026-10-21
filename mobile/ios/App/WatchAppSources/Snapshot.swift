//
//  Snapshot.swift
//
//  iPhone 側（apps/shared/watch.js）から受け取る一覧の形。
//  項目はどれも省略されうるため、読めなかったところは空として扱う。
//
import Foundation

struct Meeting: Codable, Identifiable {
    var docId: String?
    var title: String?
    var date: String?
    var days: Int?
    var time: String?
    var place: String?
    var social: String?

    enum CodingKeys: String, CodingKey {
        case docId = "id"
        case title, date, days, time, place, social
    }

    /// 書類・回覧・会議の期限トラッカー側の本当のID（無ければ日付＋件名で代用）
    var id: String { docId ?? ((date ?? "") + "/" + (title ?? "")) }

    /// 表示に使う残り日数。保存された days は使わない（下の remainingDays の説明を参照）
    var remaining: Int? { remainingDays(date: date, stored: days) }
}

struct Deadline: Codable, Identifiable {
    var docId: String?
    var title: String?
    var date: String?
    var days: Int?
    var kind: String?
    var dest: String?
    var status: String?

    enum CodingKeys: String, CodingKey {
        case docId = "id"
        case title, date, days, kind, dest, status
    }

    var id: String { docId ?? ((date ?? "") + "/" + (title ?? "")) }

    /// 表示に使う残り日数。保存された days は使わない（下の remainingDays の説明を参照）
    var remaining: Int? { remainingDays(date: date, stored: days) }
}

struct ShoppingItem: Codable, Identifiable {
    var name: String?
    var from: String?

    var id: String { (from ?? "") + "/" + (name ?? "") }
}

struct Snapshot: Codable {
    var version: Int?
    var today: String?
    var updatedAt: String?
    var meetings: [Meeting]?
    var deadlines: [Deadline]?
    var shopping: [ShoppingItem]?

    static let empty = Snapshot()

    var isEmpty: Bool {
        (meetings?.isEmpty ?? true) && (deadlines?.isEmpty ?? true) && (shopping?.isEmpty ?? true)
    }

    static func decode(_ json: String) -> Snapshot? {
        guard let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(Snapshot.self, from: data)
    }
}

private let ymdFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")   // 端末の暦設定に左右されないようにする
    f.timeZone = .current
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

/// "2026-09-24" のような日付まで、今日から何日あるかを数える（今日なら0、明日なら1）
func daysUntil(_ dateString: String?, from now: Date = Date()) -> Int? {
    guard let text = dateString, let target = ymdFormatter.date(from: text) else { return nil }
    let cal = Calendar.current
    return cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: target)).day
}

/*
 * 表示に使う残り日数。
 *
 * iPhone から届く JSON の days は「iPhone のアプリを最後に開いた時点」で数えた値のため、
 * 日をまたぐと古くなる（9/19 に開いたまま 9/20 に見ると、9/24 の期限が「あと5日」のまま
 * 出てしまう）。そこで表示のたびに日付から数え直し、日付が読めないときだけ保存値を使う。
 */
func remainingDays(date: String?, stored: Int?, from now: Date = Date()) -> Int? {
    daysUntil(date, from: now) ?? stored
}

/// 「あと何日か」を手首で読める言葉にする
func dayLabel(_ days: Int?) -> String {
    guard let d = days else { return "" }
    if d < 0 { return "\(-d)日超過" }
    if d == 0 { return "今日" }
    if d == 1 { return "明日" }
    return "あと\(d)日"
}

// MARK: - 次の予定（iPhone のウィジェット・Watch の文字盤で使う）

private let hmPattern = try? NSRegularExpression(pattern: "(\\d{1,2}):(\\d{2})")

/// "2026-09-24" と "13:30" を端末の時間帯の日時にする
private func dateAt(_ day: String?, _ hour: Int, _ minute: Int) -> Date? {
    guard let text = day, let base = ymdFormatter.date(from: text) else { return nil }
    return Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: base)
}

extension Meeting {
    /// 時刻の無い終日の予定か
    var isAllDay: Bool {
        let text = time ?? ""
        return (hmPattern?.firstMatch(in: text, range: NSRange(text.startIndex..., in: text))) == nil
    }

    /// 開始と終了の日時。time は「10:00」「10:00〜11:00」などの形で届く。
    /// 時刻が無ければ終日（その日の0時〜翌0時）、終了が無ければ開始の1時間後とする
    var startEnd: (start: Date, end: Date)? {
        guard let day = date, let base = ymdFormatter.date(from: day) else { return nil }
        let text = time ?? ""
        let matches = hmPattern?.matches(in: text, range: NSRange(text.startIndex..., in: text)) ?? []
        let times: [(Int, Int)] = matches.compactMap { match in
            guard let h = Range(match.range(at: 1), in: text), let m = Range(match.range(at: 2), in: text),
                  let hour = Int(text[h]), let minute = Int(text[m]) else { return nil }
            return (hour, minute)
        }
        guard let first = times.first, let start = dateAt(day, first.0, first.1) else {
            let next = Calendar.current.date(byAdding: .day, value: 1, to: base) ?? base.addingTimeInterval(86400)
            return (base, next)
        }
        if times.count > 1, let end = dateAt(day, times[1].0, times[1].1), end > start {
            return (start, end)
        }
        return (start, start.addingTimeInterval(3600))
    }

    /// 次の予定から外す時刻。時刻のある予定は開始の時刻、終日の予定はその日の終わり
    var leavesAt: Date? {
        guard let range = startEnd else { return nil }
        return isAllDay ? range.end : range.start
    }

    /// 始まった（終日ならその日が終わった）予定か
    func hasStarted(at now: Date = Date()) -> Bool {
        guard let at = leavesAt else { return false }
        return at <= now
    }
}

struct UpNextItem {
    let title: String
    let days: Int
    let docId: String?
    /// 時刻のある予定の開始時刻（"13:00"）。終日の予定と期限は nil
    var startTime: String? = nil
}

private let hmFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = .current
    f.dateFormat = "H:mm"
    return f
}()

/*
 * 会議と期限のうち、これから来る一番近いものをひとつ選ぶ。
 * 会議は開始の時刻になったら外し、開始の早い順にする。終日の予定はその日の終わりまで残し、
 * 同じ日の時刻のある予定より後ろに並べる（一日じゅう先頭に居座らないように）。
 * 期限はその日の終わりまで残す（同じ日の会議より後ろに並ぶ）。
 * これから来るものが無いときだけ、過ぎた期限のうち今日に近いものを出す
 * （アプリをしばらく開いていないと、新しい一覧が届かないため）。
 */
func upNext(from snapshot: Snapshot, at now: Date = Date()) -> UpNextItem? {
    var upcoming: [(key: Date, item: UpNextItem)] = []
    var past: [UpNextItem] = []
    for m in snapshot.meetings ?? [] {
        guard let days = remainingDays(date: m.date, stored: m.days, from: now) else { continue }
        var item = UpNextItem(title: m.title ?? "（会議）", days: days, docId: m.docId)
        if let range = m.startEnd {
            if !m.isAllDay { item.startTime = hmFormatter.string(from: range.start) }
            // 終日の予定は、同じ日の時刻のある予定より後ろ（期限より前）に並べる
            let key = m.isAllDay ? (dateAt(m.date, 23, 58) ?? range.start) : range.start
            if !m.hasStarted(at: now) { upcoming.append((key, item)) }
        } else if days >= 0 {
            upcoming.append((now.addingTimeInterval(Double(days) * 86400), item))
        }
    }
    for d in snapshot.deadlines ?? [] {
        guard let days = remainingDays(date: d.date, stored: d.days, from: now) else { continue }
        let item = UpNextItem(title: d.title ?? "（書類）", days: days, docId: d.docId)
        if days >= 0 {
            let end = dateAt(d.date, 23, 59) ?? now.addingTimeInterval(Double(days) * 86400)
            upcoming.append((end, item))
        } else {
            past.append(item)
        }
    }
    if let soonest = upcoming.min(by: { $0.key < $1.key }) { return soonest.item }
    return past.max { $0.days < $1.days }
}

/// 表示を切り替える時刻（これから始まる会議の開始時刻など）。ウィジェットの予定表に使う
func upNextChangeTimes(from snapshot: Snapshot, after now: Date = Date(), within hours: Double = 24, limit: Int = 12) -> [Date] {
    let until = now.addingTimeInterval(hours * 3600)
    let ends = (snapshot.meetings ?? []).compactMap { $0.leavesAt }.filter { $0 > now && $0 <= until }
    return Array(Set(ends)).sorted().prefix(limit).map { $0 }
}
