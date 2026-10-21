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
        // 予定が始まった時刻に次の予定へ切り替えるため、その時刻ごとの表示を先に並べておく。
        // 残り日数は日付が変わると変わるため、次の正時と翌0時の早いほうで一覧を作り直す
        let now = Date()
        let snapshot = SharedDefaults.loadSnapshot()
        let hourLater = Calendar.current.date(byAdding: .hour, value: 1, to: now) ?? now.addingTimeInterval(3600)
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0),
                                                 matchingPolicy: .nextTime) ?? hourLater
        let next = min(hourLater, midnight)
        let times = [now] + upNextChangeTimes(from: snapshot, after: now)
        completion(Timeline(entries: times.map { entry(snapshot, at: $0) }, policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntry {
        entry(SharedDefaults.loadSnapshot(), at: Date())
    }

    private func entry(_ snapshot: Snapshot, at date: Date) -> NextUpEntry {
        guard let item = upNext(from: snapshot, at: date) else {
            return NextUpEntry(date: date, title: "予定なし", dayLabel: "", hasItem: false, docId: nil)
        }
        return NextUpEntry(date: date, title: item.title, dayLabel: dayLabel(item.days), hasItem: true, docId: item.docId)
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
        // 1行に収まらないと末尾が切れるため、残り日数を先頭に出す（会議名が長くても日数は残る）
        Text(entry.hasItem ? "\(entry.dayLabel)・\(entry.title)" : "予定なし")
    }

    private var cornerView: some View {
        // 角の本文は1行に収め、折れて「日」が消えないようにする。
        // 日数は本文に出すので、曲線のラベル側は件名だけにする（日数が2箇所に出ないように）
        Text(entry.hasItem ? entry.dayLabel : "―")
            .font(.system(size: 15, weight: .semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.5)
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
