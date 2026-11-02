//
//  NextUpWidget.swift
//
//  Watch の文字盤（インフォグラフなど）に出すコンプリケーション。
//  会議・書類の期限のうち、一番近いものをひとつだけ表示する。
//  今日これからの会議が2件以上あるときは1分ごとに順に切り替え、四角い枠には2件並べる。
//  買い物リストは緊急性が低いためここには出さない（アプリ本体では見られる）。
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
    /// 今日の会議を順に出しているときの「何件目／全何件」。それ以外は 0
    var index = 0
    var count = 0
    /// 四角い枠に並べる今日の会議（「13:00 件名」）。今日の会議が2件以上あるときだけ入る
    var todayLines: [String] = []
}

/// 今日の会議を順に出すときの切り替え間隔。
/// ウィジェットは決めた時刻に絵を差し替えるだけで、1分より短い間隔は OS が守らない
/// （常時表示の Watch は1分に1回しか描き直さない）ため、1分にしている。
private let rotateInterval: TimeInterval = 60

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
        let snapshot = SharedDefaults.loadSnapshot()
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: now) ?? now.addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        if todayMeetings(from: snapshot, at: now).count >= 2 {
            // 今日これからの会議が2件以上あるときは、次の作り直しまで1分ごとに1件ずつ順に出す。
            // 毎分その時点の一覧で作るので、始まった会議は自然に外れる
            let turns = stride(from: now, to: next, by: rotateInterval).enumerated()
            completion(Timeline(entries: turns.map { entry(snapshot, at: $0.element, turn: $0.offset) }, policy: .after(next)))
            return
        }
        let times = [now] + upNextChangeTimes(from: snapshot, after: now)
        completion(Timeline(entries: times.map { entry(snapshot, at: $0) }, policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntry {
        entry(SharedDefaults.loadSnapshot(), at: Date())
    }

    private func entry(_ snapshot: Snapshot, at date: Date, turn: Int = 0) -> NextUpEntry {
        let today = todayMeetings(from: snapshot, at: date)
        if today.count >= 2 {
            let i = turn % today.count
            let item = today[i]
            let lines = today.map { "\($0.startTime ?? "終日") \($0.title)" }
            return NextUpEntry(date: date, title: item.title, dayLabel: item.startTime ?? "今日", hasItem: true,
                docId: item.docId, index: i + 1, count: today.count, todayLines: lines)
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
        if entry.todayLines.count >= 2 {
            todayListView
        } else {
            singleView
        }
    }

    /// 今日の会議が複数あるときは、2件並べて残りは「ほかN件」と出す
    private var todayListView: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(entry.count > 2 ? "今日 \(entry.count)件・ほか\(entry.count - 2)件" : "今日 \(entry.count)件")
                .font(.caption2)
                .foregroundStyle(.secondary)
            ForEach(Array(entry.todayLines.prefix(2).enumerated()), id: \.offset) { _, line in
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

    /// 今日の会議を順に出しているときは「 1/3」を添える。それ以外は空
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
        .description("会議・書類の期限のうち、一番近いものを表示します。")
        .supportedFamilies([.accessoryCorner, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct DailyAppsWidgetBundle: WidgetBundle {
    var body: some Widget {
        NextUpWidget()
    }
}
