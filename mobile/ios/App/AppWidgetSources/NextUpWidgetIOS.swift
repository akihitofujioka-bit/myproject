//
//  NextUpWidgetIOS.swift
//
//  iPhoneのロック画面（および StandBy）に出すウィジェット。
//  Watchのコンプリケーションと同じく、会議・書類の期限のうち一番近いものを
//  ひとつだけ表示する。
//  次の予定がある日に会議が2件以上あるときは10秒ごとに順に切り替え、四角い枠には2件並べて1件ずつずらす。
//  丸い枠だけは予定ではなく未完了の TODO を、10秒ごとに1件ずつ順に出す。
//  タップすると、書類・回覧・会議の期限トラッカーの
//  該当項目を直接開く（既存の myproject://docs?id=xxx を使う）。
//
//  データは WatchBridgePlugin が App Group に書き込んだものを読むだけで、
//  ここから新たに何かを取得したり外部へ送ったりはしない。
//
import WidgetKit
import SwiftUI

struct NextUpEntryIOS: TimelineEntry {
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
    /// 丸い枠に出す TODO。todoCount が 0 なら TODO なし
    var todoTitle = ""
    var todoId: String? = nil
    var todoIndex = 0
    var todoCount = 0
}

/// その日の会議を順に出すときの切り替え間隔。
/// ウィジェットは決めた時刻に絵を差し替えるだけで、1分より短い間隔を OS が守るとは限らない
/// （常時表示の Watch は1分に1回しか描き直さない）。利用者の希望で10秒を試している（2026-11-02）。
/// 実機でうまく切り替わらなければ 60 に戻す
private let rotateInterval: TimeInterval = 10

struct NextUpProviderIOS: TimelineProvider {
    func placeholder(in context: Context) -> NextUpEntryIOS {
        NextUpEntryIOS(date: Date(), title: "会議名など", dayLabel: "あと2日", hasItem: true, docId: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (NextUpEntryIOS) -> Void) {
        completion(currentEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NextUpEntryIOS>) -> Void) {
        // 予定が始まった時刻に次の予定へ切り替えるため、その時刻ごとの表示を先に並べておく。
        // 残り日数は日付が変わると変わるため、次の正時と翌0時の早いほうで一覧を作り直す
        let now = Date()
        let snapshot = SharedDefaults.loadSnapshot()
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: now) ?? now.addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        if nextDayMeetings(from: snapshot, at: now).count >= 2 || (snapshot.todos ?? []).count >= 2 {
            // 次の予定がある日に会議が2件以上あるとき（丸い枠は TODO が2件以上あるとき）は、次の作り直しまで10秒ごとに1件ずつ順に出す。
            // そのつどその時点の一覧で作るので、始まった会議は自然に外れる
            let turns = stride(from: now, to: next, by: rotateInterval).enumerated()
            completion(Timeline(entries: turns.map { entry(snapshot, at: $0.element, turn: $0.offset) }, policy: .after(next)))
            return
        }
        let times = [now] + upNextChangeTimes(from: snapshot, after: now)
        completion(Timeline(entries: times.map { entry(snapshot, at: $0) }, policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntryIOS {
        entry(SharedDefaults.loadSnapshot(), at: Date())
    }

    private func entry(_ snapshot: Snapshot, at date: Date, turn: Int = 0) -> NextUpEntryIOS {
        var e = scheduleEntry(snapshot, at: date, turn: turn)
        let todos = snapshot.todos ?? []
        if !todos.isEmpty {
            let i = turn % todos.count
            e.todoTitle = todos[i].title ?? "（TODO）"
            e.todoId = todos[i].docId
            e.todoIndex = i + 1
            e.todoCount = todos.count
        }
        return e
    }

    /// 四角・1行の枠に出す予定（会議・書類の期限）
    private func scheduleEntry(_ snapshot: Snapshot, at date: Date, turn: Int) -> NextUpEntryIOS {
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
            return NextUpEntryIOS(date: date, title: item.title, dayLabel: label, hasItem: true,
                docId: item.docId, index: i + 1, count: group.count, dayLines: lines,
                groupLabel: dayLabel(item.days))
        }
        guard let item = upNext(from: snapshot, at: date) else {
            return NextUpEntryIOS(date: date, title: "予定なし", dayLabel: "", hasItem: false, docId: nil)
        }
        return NextUpEntryIOS(date: date, title: item.title, dayLabel: dayLabel(item.days), hasItem: true, docId: item.docId)
    }
}

private extension View {
    /// containerBackground は iOS 17 以降専用。それより前は背景を付けなくても表示できる。
    @ViewBuilder
    func widgetBackground() -> some View {
        if #available(iOS 17.0, *) {
            containerBackground(.fill.tertiary, for: .widget)
        } else {
            background(.clear)
        }
    }
}

struct NextUpEntryViewIOS: View {
    var entry: NextUpProviderIOS.Entry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular:
                circularView
            case .accessoryInline:
                inlineView
            default:
                rectangularView
            }
        }
        // 丸い枠は TODO を出しているので、その TODO を開く
        .widgetURL(DeepLink.docsURL(id: family == .accessoryCircular ? entry.todoId : entry.docId))
    }

    /// 丸い枠は未完了の TODO を出す。2件以上なら10秒ごとに順に切り替え、「1/3」を添える
    private var circularView: some View {
        VStack(spacing: 1) {
            Image(systemName: "checklist")
                .font(.caption2)
            Text(entry.todoCount > 0 ? entry.todoTitle : "なし")
                .font(.system(size: 12, weight: .semibold))
                .minimumScaleFactor(0.6)
                .lineLimit(1)
            if entry.todoCount >= 2 {
                Text("\(entry.todoIndex)/\(entry.todoCount)")
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
        Text(entry.hasItem ? "\(entry.title)・\(entry.dayLabel)\(position)" : "予定なし")
    }
}

struct NextUpWidgetIOS: Widget {
    let kind = "NextUpWidgetIOS"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NextUpProviderIOS()) { entry in
            NextUpEntryViewIOS(entry: entry)
        }
        .configurationDisplayName("次の予定")
        .description("丸い枠は TODO、四角と1行の枠は会議・書類の期限のうち一番近いものを表示します。")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct DailyAppsWidgetBundleIOS: WidgetBundle {
    var body: some Widget {
        NextUpWidgetIOS()
    }
}
