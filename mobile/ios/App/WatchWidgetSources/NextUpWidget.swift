//
//  NextUpWidget.swift
//
//  Watch の文字盤（インフォグラフなど）に出すコンプリケーション。
//  これから始まる予定（会議）のうち、一番近いものをひとつだけ表示する。書類・TODO の期限は出さない。
//  次の予定がある日に会議が2件以上あるときは10秒ごとに順に切り替え、四角い枠には2件並べて1件ずつずらす。
//  買い物リストは緊急性が低いためここには出さない（アプリ本体では見られる）。
//
//  未完了の TODO を出す「TODO」も同じファイルに置き、別の枠として選べるようにしている。
//
//  データは WatchStore が App Group に書き込んだものを読むだけで、
//  ここから新たに何かを取得したり外部へ送ったりはしない。
//
import WidgetKit
import SwiftUI

struct NextUpEntry: TimelineEntry {
    let date: Date
    let title: String
    let dayLabel: String
    let hasItem: Bool
    let docId: String?
    /// その日の会議を順に出しているときの「何件目／全何件」。それ以外は 0
    var index = 0
    var count = 0
    /// 四角い枠に並べるその日の会議（「13:00 件名」）。会議が2件以上あるときだけ入る
    var dayLines: [String] = []
    /// 四角い枠の見出しに出す日（「今日」「明日」など）
    var groupLabel = ""
}

/// その日の会議を順に出すときの切り替え間隔。
/// ウィジェットは決めた時刻に絵を差し替えるだけで、1分より短い間隔を OS が守るとは限らない
/// （常時表示の Watch は1分に1回しか描き直さない）。利用者の希望で10秒を試している（2026-11-02）。
/// 実機でうまく切り替わらなければ 60 に戻す
private let rotateInterval: TimeInterval = 10

struct NextUpProvider: TimelineProvider {
    func placeholder(in context: Context) -> NextUpEntry {
        NextUpEntry(date: Date(), title: "会議名など", dayLabel: "あと2日", hasItem: true, docId: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (NextUpEntry) -> Void) {
        completion(currentEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NextUpEntry>) -> Void) {
        // 予定が始まった時刻に次の予定へ切り替えるため、その時刻ごとの表示を先に並べておく。
        // 残り日数は日付が変わると変わるため、次の正時と翌0時の早いほうで一覧を作り直す
        let now = Date()
        let snapshot = SharedDefaults.loadSnapshot().meetingsOnly
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: now) ?? now.addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        if nextDayMeetings(from: snapshot, at: now).count >= 2 {
            // 次の予定がある日に会議が2件以上あるときは、次の作り直しまで10秒ごとに1件ずつ順に出す。
            // そのつどその時点の一覧で作るので、始まった会議は自然に外れる
            let turns = stride(from: now, to: next, by: rotateInterval).enumerated()
            completion(Timeline(entries: turns.map { entry(snapshot, at: $0.element, turn: $0.offset) }, policy: .after(next)))
            return
        }
        let times = [now] + upNextChangeTimes(from: snapshot, after: now)
        completion(Timeline(entries: times.map { entry(snapshot, at: $0) }, policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntry {
        entry(SharedDefaults.loadSnapshot().meetingsOnly, at: Date())
    }

    private func entry(_ snapshot: Snapshot, at date: Date, turn: Int = 0) -> NextUpEntry {
        let group = nextDayMeetings(from: snapshot, at: date)
        if group.count >= 2 {
            let i = turn % group.count
            let item = group[i]
            // 今日の時刻のある会議は開始時刻、それ以外は「明日」など（日数が2箇所に出ないように）
            let label = item.days == 0 ? (item.startTime ?? dayLabel(0)) : dayLabel(item.days)
            // 四角い枠は先頭の2件を出すので、3件以上なら今の1件が先頭に来るよう回しておく
            // （1・2 → 2・3 → 3・1）。2件だけのときは入れ替わると読みにくいので並びを変えない
            let all = group.map { "\($0.startTime ?? "終日") \($0.title)" }
            let lines = all.count > 2 ? Array(all[i...] + all[..<i]) : all
            return NextUpEntry(date: date, title: item.title, dayLabel: label, hasItem: true,
                docId: item.docId, index: i + 1, count: group.count, dayLines: lines,
                groupLabel: dayLabel(item.days))
        }
        guard let item = upNext(from: snapshot, at: date) else {
            return NextUpEntry(date: date, title: "予定なし", dayLabel: "", hasItem: false, docId: nil)
        }
        // 今日の時刻のある予定は「今日」ではなく開始時刻を出す（手首で一目で分かるように）
        let label = item.days == 0 ? (item.startTime ?? dayLabel(item.days)) : dayLabel(item.days)
        return NextUpEntry(date: date, title: item.title, dayLabel: label, hasItem: true, docId: item.docId)
    }
}

private extension View {
    /// containerBackground は watchOS 10 以降専用。それより前は背景を付けなくても表示できる。
    @ViewBuilder
    func widgetBackground() -> some View {
        if #available(watchOS 10.0, *) {
            containerBackground(.fill.tertiary, for: .widget)
        } else {
            background(.clear)
        }
    }
}

struct NextUpEntryView: View {
    var entry: NextUpProvider.Entry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        Group {
            switch family {
            case .accessoryCorner:
                cornerView
            case .accessoryCircular:
                circularView
            case .accessoryInline:
                inlineView
            default:
                rectangularView
            }
        }
        .widgetURL(DeepLink.watchItemURL(id: entry.docId))
    }

    private var circularView: some View {
        VStack(spacing: 1) {
            Image(systemName: "calendar")
                .font(.caption2)
            Text(entry.hasItem ? entry.dayLabel : "なし")
                .font(.system(size: 12, weight: .semibold))
                .minimumScaleFactor(0.6)
                .lineLimit(1)
            if entry.count >= 2 {
                Text("\(entry.index)/\(entry.count)")
                    .font(.system(size: 10))
                    .lineLimit(1)
            }
        }
        .widgetBackground()
    }

    @ViewBuilder
    private var rectangularView: some View {
        if entry.dayLines.count >= 2 {
            dayListView
        } else {
            singleView
        }
    }

    /// 同じ日に会議が複数あるときは2件並べる。3件以上なら切り替えのたびに1件ずつずれて全件が順に出る
    private var dayListView: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("\(entry.groupLabel) \(entry.count)件")
                .font(.caption2)
                .foregroundStyle(.secondary)
            ForEach(Array(entry.dayLines.prefix(2).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(.headline)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .widgetBackground()
    }

    private var singleView: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(entry.hasItem ? entry.title : "予定なし")
                .font(.headline)
                .lineLimit(1)
            if entry.hasItem {
                Text(entry.dayLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .widgetBackground()
    }

    /// その日の会議を順に出しているときは「 1/3」を添える。それ以外は空
    private var position: String {
        entry.count >= 2 ? " \(entry.index)/\(entry.count)" : ""
    }

    private var inlineView: some View {
        // 1行に収まらないと末尾が切れるため、残り日数を先頭に出す（会議名が長くても日数は残る）
        Text(entry.hasItem ? "\(entry.dayLabel)\(position)・\(entry.title)" : "予定なし")
    }

    private var cornerView: some View {
        // 角の本文は1行に収め、折れて「日」が消えないようにする。
        // 日数は本文に出すので、曲線のラベル側は件名だけにする（日数が2箇所に出ないように）
        Text(entry.hasItem ? entry.dayLabel : "―")
            .font(.system(size: 15, weight: .semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            .widgetLabel {
                Text(entry.hasItem ? "\(entry.title)\(position)" : "予定なし")
            }
            .widgetBackground()
    }
}

struct NextUpWidget: Widget {
    let kind = "NextUpWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NextUpProvider()) { entry in
            NextUpEntryView(entry: entry)
        }
        .configurationDisplayName("次の予定")
        .description("これから始まる予定のうち、一番近いものを表示します。")
        .supportedFamilies([.accessoryCorner, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

// MARK: - TODO（インフォグラフなどの枠に、次の予定とは別に置く）

struct TodoEntry: TimelineEntry {
    let date: Date
    let title: String
    /// 「15:00」「明日 10:00」「期限なし」など
    let label: String
    let docId: String?
    /// 何件目／全何件。TODO が無ければ count は 0
    var index = 0
    var count = 0
}

/// TODO の期限を手首で読める言葉にする。今日で時刻があれば時刻だけ（次の予定と同じ考え方）
private func todoLabel(_ todo: Deadline) -> String {
    guard let days = todo.remaining else { return "期限なし" }
    let time = todo.time ?? ""
    if days == 0 && !time.isEmpty { return time }
    return [dayLabel(days), time].filter { !$0.isEmpty }.joined(separator: " ")
}

struct TodoProvider: TimelineProvider {
    func placeholder(in context: Context) -> TodoEntry {
        TodoEntry(date: Date(), title: "資料を準備", label: "15:00", docId: nil, index: 1, count: 3)
    }

    func getSnapshot(in context: Context, completion: @escaping (TodoEntry) -> Void) {
        completion(entry(SharedDefaults.loadSnapshot(), at: Date(), turn: 0))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodoEntry>) -> Void) {
        // 残り日数は日付が変わると変わるため、次の正時と翌0時の早いほうで作り直す。
        // 2件以上あるときは、それまで10秒ごとに1件ずつ順に出す（次の予定と同じ間隔）
        let now = Date()
        let snapshot = SharedDefaults.loadSnapshot()
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: now) ?? now.addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        let turns = (snapshot.todos ?? []).count >= 2
            ? Array(stride(from: now, to: next, by: rotateInterval).enumerated()).map { ($0.element, $0.offset) }
            : [(now, 0)]
        completion(Timeline(entries: turns.map { entry(snapshot, at: $0.0, turn: $0.1) }, policy: .after(next)))
    }

    private func entry(_ snapshot: Snapshot, at date: Date, turn: Int) -> TodoEntry {
        let todos = snapshot.todos ?? []
        guard !todos.isEmpty else {
            return TodoEntry(date: date, title: "TODOなし", label: "", docId: nil)
        }
        let i = turn % todos.count
        return TodoEntry(date: date, title: todos[i].title ?? "（TODO）", label: todoLabel(todos[i]),
                         docId: todos[i].docId, index: i + 1, count: todos.count)
    }
}

struct TodoEntryView: View {
    var entry: TodoProvider.Entry
    @Environment(\.widgetFamily) private var family

    /// 2件以上を順に出しているときは「 1/3」を添える
    private var position: String {
        entry.count >= 2 ? " \(entry.index)/\(entry.count)" : ""
    }

    var body: some View {
        Group {
            switch family {
            case .accessoryCorner:
                Image(systemName: "checklist")
                    .font(.system(size: 18, weight: .semibold))
                    .widgetLabel {
                        Text(entry.count > 0 ? "\(entry.title)\(position)" : entry.title)
                    }
                    .widgetBackground()
            case .accessoryCircular:
                VStack(spacing: 1) {
                    Image(systemName: "checklist")
                        .font(.caption2)
                    Text(entry.count > 0 ? entry.title : "なし")
                        .font(.system(size: 12, weight: .semibold))
                        .minimumScaleFactor(0.6)
                        .lineLimit(1)
                    if entry.count >= 2 {
                        Text("\(entry.index)/\(entry.count)")
                            .font(.system(size: 10))
                            .lineLimit(1)
                    }
                }
                .widgetBackground()
            case .accessoryInline:
                Text(entry.count > 0 ? "\(entry.label)\(position)・\(entry.title)" : entry.title)
            default:
                VStack(alignment: .leading, spacing: 1) {
                    Text("TODO\(position)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(entry.title)
                        .font(.headline)
                        .lineLimit(2)
                        .minimumScaleFactor(0.8)
                    if !entry.label.isEmpty {
                        Text(entry.label)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .widgetBackground()
            }
        }
        .widgetURL(DeepLink.watchItemURL(id: entry.docId))
    }
}

struct TodoWidget: Widget {
    let kind = "TodoWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TodoProvider()) { entry in
            TodoEntryView(entry: entry)
        }
        .configurationDisplayName("TODO")
        .description("未完了の TODO を期限の近い順に、10秒ごとに1件ずつ表示します。")
        .supportedFamilies([.accessoryCorner, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct DailyAppsWidgetBundle: WidgetBundle {
    var body: some Widget {
        NextUpWidget()
        TodoWidget()
    }
}
