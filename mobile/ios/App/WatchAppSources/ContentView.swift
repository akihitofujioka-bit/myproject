//
//  ContentView.swift
//
//  手首で見る画面。最初に「文字盤」（FaceView.swift。アナログ針とデジタル時刻、周りに8つのボタン）を出し、
//  ボタンから「予定」「期限」「TODO」「買い物」などの一覧へ進む。
//  次の予定がある日に会議が2件以上あるときは、一覧のいちばん上に10秒ごとに切り替わる欄を出す。
//  操作（消し込みや状態の変更）はここでは行わない。見るための画面に絞っている。
//
import SwiftUI

/// 文字盤のボタンから開く一覧の種類
enum FacePanel: Hashable {
    case meetings, deadlines, todos, shopping, next, all, info
}

struct ContentView: View {
    @ObservedObject var store: WatchStore
    @State private var path: [FacePanel] = []

    var body: some View {
        NavigationStack(path: $path) {
            FaceView(store: store) { panel in path = [panel] }
                .navigationDestination(for: FacePanel.self) { panel in
                    ItemsView(store: store, panel: panel)
                }
        }
        .onChange(of: store.focusedId) { id in
            // コンプリケーションから開いたときは、全部の一覧へ進んで該当の項目までスクロールする
            if id != nil { path = [.all] }
        }
    }
}

/// 一覧の画面。panel で出す欄を絞る（.all は全部）
struct ItemsView: View {
    @ObservedObject var store: WatchStore
    let panel: FacePanel

    private func shows(_ p: FacePanel) -> Bool { panel == .all || panel == p }

    var body: some View {
        ScrollViewReader { proxy in
            List {
                if panel == .info {
                    footer
                } else if store.snapshot.isEmpty && (store.snapshot.todos ?? []).isEmpty {
                    emptyView
                } else {
                    if shows(.next) { rotatingSection }
                    if panel == .next { upNextSection }
                    if shows(.meetings) { meetingSection }
                    if shows(.deadlines) { deadlineSection }
                    if shows(.todos) { todoSection }
                    if shows(.shopping) { shoppingSection }
                    if panel != .all && isPanelEmpty { Text("いまは何もありません").font(.footnote) }
                }
                if panel == .all { footer }
            }
            .scrollContentBackground(.hidden)
            .background {
                if let background = store.background {
                    ZStack {
                        Image(uiImage: background)
                            .resizable()
                            .scaledToFill()
                        Color.black.opacity(0.55)
                    }
                    .clipped()
                    .ignoresSafeArea()
                } else {
                    JojoPalette.backdrop.opacity(0.6).ignoresSafeArea()
                }
            }
            .navigationTitle(title)
            .onAppear { scroll(proxy, to: store.focusedId) }
            .onChange(of: store.focusedId) { id in scroll(proxy, to: id) }
        }
    }

    private func scroll(_ proxy: ScrollViewProxy, to id: String?) {
        guard let id = id else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            withAnimation { proxy.scrollTo(id, anchor: .center) }
        }
    }

    private var title: String {
        switch panel {
        case .meetings: return "予定"
        case .deadlines: return "期限"
        case .todos: return "TODO"
        case .shopping: return "買い物"
        case .next: return "次"
        case .all: return "全部"
        case .info: return "情報"
        }
    }

    private var isPanelEmpty: Bool {
        let s = store.snapshot
        switch panel {
        case .meetings: return (s.meetings ?? []).filter { !$0.hasEnded() }.isEmpty
        case .deadlines: return (s.deadlines ?? []).isEmpty
        case .todos: return (s.todos ?? []).isEmpty
        case .shopping: return (s.shopping ?? []).isEmpty
        case .next: return upNext(from: s) == nil
        default: return false
        }
    }

    /// いちばん近い予定・期限をひとつ大きく出す
    @ViewBuilder
    private var upNextSection: some View {
        if let item = upNext(from: store.snapshot) {
            Section("いちばん近い") {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title).font(.headline).lineLimit(3)
                    Text("\(dayLabel(item.days)) \(item.startTime ?? "")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            }
        }
    }

    /// 未完了の TODO（形は期限と同じ）
    @ViewBuilder
    private var todoSection: some View {
        let list = store.snapshot.todos ?? []
        if !list.isEmpty {
            Section("TODO") {
                ForEach(list) { t in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t.title ?? "（件名なし）")
                            .font(.headline)
                            .lineLimit(2)
                        let label = dayLabel(t.remaining)
                        if !label.isEmpty {
                            Text(label)
                                .font(.caption)
                                .foregroundStyle((t.remaining ?? 99) <= 0 ? .red : .secondary)
                        }
                    }
                    .padding(.vertical, 4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private var emptyView: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("まだ何も届いていません")
                .font(.headline)
            Text("iPhone の「日常アプリ」を一度開くと、この画面に送られます。")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    /// 次の予定がある日の会議を、10秒ごとに1件ずつ順に出す（文字盤と同じ並び）。
    /// 2件未満の日は出さない（下の「予定」の一覧で足りるため）
    @ViewBuilder
    private var rotatingSection: some View {
        if nextDayMeetings(from: store.snapshot).count >= 2 {
            Section("次の予定") {
                TimelineView(.periodic(from: .now, by: 10)) { context in
                    let group = nextDayMeetings(from: store.snapshot, at: context.date)
                    if group.isEmpty {
                        Text("予定なし")
                            .font(.headline)
                    } else {
                        // 時刻から何件目かを決めるので、画面を開き直しても順番は続きから進む
                        let i = Int(context.date.timeIntervalSince1970 / 10) % group.count
                        let item = group[i]
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title)
                                .font(.headline)
                                .lineLimit(2)
                            Text("\(dayLabel(item.days)) \(item.startTime ?? "終日")　\(i + 1)/\(group.count)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var meetingSection: some View {
        // 終わった予定は出さない（iPhone のアプリを開くまで一覧が届かないため、Watch 側でも外す）
        let list = (store.snapshot.meetings ?? []).filter { !$0.hasEnded() }
        if !list.isEmpty {
            Section("予定") {
                ForEach(list) { m in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(m.title ?? "（件名なし）")
                            .font(.headline)
                            .lineLimit(2)
                        Text([dayLabel(m.remaining), m.time ?? ""].filter { !$0.isEmpty }.joined(separator: " "))
                            .font(.caption)
                        if let place = m.place, !place.isEmpty {
                            Text(place)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        if let social = m.social, !social.isEmpty {
                            Text(social)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(store.focusedId == m.id ? Color.yellow.opacity(0.35) : Color.clear)
                    )
                    .id(m.id)
                }
            }
        }
    }

    @ViewBuilder
    private var deadlineSection: some View {
        let list = store.snapshot.deadlines ?? []
        if !list.isEmpty {
            Section("期限") {
                ForEach(list) { d in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(d.title ?? "（件名なし）")
                            .font(.headline)
                            .lineLimit(2)
                        Text([dayLabel(d.remaining), d.kind ?? "", d.status ?? ""]
                            .filter { !$0.isEmpty }.joined(separator: " ／ "))
                            .font(.caption)
                            .foregroundStyle((d.remaining ?? 99) <= 0 ? .red : .secondary)
                        if let dest = d.dest, !dest.isEmpty {
                            Text(dest)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(store.focusedId == d.id ? Color.yellow.opacity(0.35) : Color.clear)
                    )
                    .id(d.id)
                }
            }
        }
    }

    @ViewBuilder
    private var shoppingSection: some View {
        let list = store.snapshot.shopping ?? []
        if !list.isEmpty {
            Section("買い物") {
                ForEach(list) { s in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(s.name ?? "")
                            .font(.body)
                            .lineLimit(2)
                        Spacer(minLength: 4)
                        Text(s.from ?? "")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                Text("消し込みはリマインダー App で行えます")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        Section {
            Button {
                store.requestLatest()
            } label: {
                Label(store.isRequesting ? "更新しています…" : "最新にする", systemImage: "arrow.clockwise")
                    .font(.caption)
            }
            .disabled(store.isRequesting)

            Text(updatedText)
                .font(.caption2)
                .foregroundStyle(.secondary)

            Text("版 " + buildLabel)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var updatedText: String {
        guard let at = store.receivedAt else { return "未受信" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "ja_JP")
        f.dateFormat = "M月d日 HH:mm 受信"
        return f.string(from: at)
    }

    /// iPhone側と同じ「日時（コミット番号）」形式。ビルド時にInfo.plistへ埋め込んでいる
    private var buildLabel: String {
        (Bundle.main.object(forInfoDictionaryKey: "AppBuildLabel") as? String) ?? "不明"
    }
}
