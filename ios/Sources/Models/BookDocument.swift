import Foundation

/// 読み上げ用に分割済みの本文。1 セグメント = 1 発話単位（おおむね 1 文）。
struct BookDocument: Codable, Hashable {
    var segments: [Segment]

    var isEmpty: Bool { segments.isEmpty }

    /// セグメント位置 → 章タイトル（見出しセグメントを遡って探す）。
    func sectionTitle(at index: Int) -> String? {
        guard segments.indices.contains(index) else { return nil }
        for i in stride(from: index, through: 0, by: -1) where segments[i].isHeading {
            return segments[i].text
        }
        return segments[index].locator
    }
}

struct Segment: Identifiable, Codable, Hashable {
    /// segments 配列内での位置と一致する連番。
    let id: Int
    let text: String
    /// 見出し行（章タイトルなど）かどうか。
    let isHeading: Bool
    /// "12 ページ" や章名など、由来を示すラベル。
    let locator: String?

    init(id: Int, text: String, isHeading: Bool = false, locator: String? = nil) {
        self.id = id
        self.text = text
        self.isHeading = isHeading
        self.locator = locator
    }
}

/// 解析途中の中間表現。段落と見出しの並びを表す。
struct RawBlock {
    var text: String
    var isHeading: Bool
    var locator: String?

    init(text: String, isHeading: Bool = false, locator: String? = nil) {
        self.text = text
        self.isHeading = isHeading
        self.locator = locator
    }
}
