//
//  NextUpWidgetIOS.swift
//
//  iPhoneのロック画面（および StandBy）に出すウィジェット。
//  Watchのコンプリケーションと同じく、会議・書類の期限のうち一番近いものを
//  ひとつだけ表示する。タップすると、書類・回覧・会議の期限トラッカーの
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
}

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
        let times = [now] + upNextChangeTimes(from: snapshot, after: now)
        completion(Timeline(entries: times.map { entry(snapshot, at: $0) }, policy: .after(next)))
    }

    private func currentEntry() -> NextUpEntryIOS {
        entry(SharedDefaults.loadSnapshot(), at: Date())
    }

    private func entry(_ snapshot: Snapshot, at date: Date) -> NextUpEntryIOS {
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
        .widgetURL(DeepLink.docsURL(id: entry.docId))
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
}

struct NextUpWidgetIOS: Widget {
    let kind = "NextUpWidgetIOS"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NextUpProviderIOS()) { entry in
            NextUpEntryViewIOS(entry: entry)
        }
        .configurationDisplayName("次の予定")
        .description("会議・書類の期限のうち、一番近いものを表示します。")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct DailyAppsWidgetBundleIOS: WidgetBundle {
    var body: some Widget {
        NextUpWidgetIOS()
    }
}
