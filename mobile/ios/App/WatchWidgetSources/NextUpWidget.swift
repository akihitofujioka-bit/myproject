//
//  NextUpWidget.swift
//
//  Watch の文字盤（インフォグラフなど）に出すコンプリケーション。
//  会議・書類の期限のうち、一番近いものをひとつだけ表示する。
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
}

struct NextUpProvider: TimelineProvider {
    func placeholder(in context: Context) -> NextUpEntry {
        NextUpEntry(date: Date(), title: "会議名など", dayLabel: "あと2日", hasItem: true, docId: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (NextUpEntry) -> Void) {
        completion(currentEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NextUpEntry>) -> Void) {
        // 残り日数は日付が変わると変わるため、次の正時と翌0時の早いほうで更新する
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: Date()) ?? Date().addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: Date(), matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        completion(Timeline(entries: [currentEntry()], policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntry {
        guard let item = nextItem(from: SharedDefaults.loadSnapshot()) else {
            return NextUpEntry(date: Date(), title: "予定なし", dayLabel: "", hasItem: false, docId: nil)
        }
        return NextUpEntry(date: Date(), title: item.title, dayLabel: dayLabel(item.days), hasItem: true, docId: item.docId)
    }
}

private struct NextItem {
    let title: String
    let days: Int
    let docId: String?
}

/// 会議と期限をまとめて、一番近い（days が小さい）ものをひとつ選ぶ。
private func nextItem(from snapshot: Snapshot) -> NextItem? {
    var candidates: [NextItem] = []
    for m in snapshot.meetings ?? [] {
        guard let days = m.remaining else { continue }
        candidates.append(NextItem(title: m.title ?? "（会議）", days: days, docId: m.docId))
    }
    for d in snapshot.deadlines ?? [] {
        guard let days = d.remaining else { continue }
        candidates.append(NextItem(title: d.title ?? "（書類）", days: days, docId: d.docId))
    }
    // これから来るもののうち一番近いものを選ぶ。
    // 過ぎたものしか無いときだけ、その中で今日に近いものを出す
    // （アプリをしばらく開いていないと、終わった会議がいつまでも残るため）。
    if let soonest = candidates.filter({ $0.days >= 0 }).min(by: { $0.days < $1.days }) {
        return soonest
    }
    return candidates.max { $0.days < $1.days }
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
        }
        .widgetBackground()
    }

    private var rectangularView: some View {
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

    private var inlineView: some View {
        Text(entry.hasItem ? "\(entry.title)・\(entry.dayLabel)" : "予定なし")
    }

    private var cornerView: some View {
        Text(entry.hasItem ? entry.dayLabel : "―")
            .font(.system(size: 15, weight: .semibold))
            .widgetLabel {
                Text(entry.hasItem ? entry.title : "予定なし")
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
