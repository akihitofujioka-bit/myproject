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
