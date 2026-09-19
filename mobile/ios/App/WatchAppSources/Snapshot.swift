//
//  Snapshot.swift
//
//  iPhone 側（apps/shared/watch.js）から受け取る一覧の形。
//  項目はどれも省略されうるため、読めなかったところは空として扱う。
//
import Foundation

struct Meeting: Codable, Identifiable {
    var title: String?
    var date: String?
    var days: Int?
    var time: String?
    var place: String?
    var social: String?

    var id: String { (date ?? "") + "/" + (title ?? "") }
}

struct Deadline: Codable, Identifiable {
    var title: String?
    var date: String?
    var days: Int?
    var kind: String?
    var dest: String?
    var status: String?

    var id: String { (date ?? "") + "/" + (title ?? "") }
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

/// 「あと何日か」を手首で読める言葉にする
func dayLabel(_ days: Int?) -> String {
    guard let d = days else { return "" }
    if d < 0 { return "\(-d)日超過" }
    if d == 0 { return "今日" }
    if d == 1 { return "明日" }
    return "あと\(d)日"
}
