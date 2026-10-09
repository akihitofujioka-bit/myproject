//
//  ContentView.swift
//
//  手首で見る画面。上から「会議」「期限」「買い物」。
//  操作（消し込みや状態の変更）はここでは行わない。見るための画面に絞っている。
//
import SwiftUI

struct ContentView: View {
    @ObservedObject var store: WatchStore

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                List {
                    if store.snapshot.isEmpty {
                        emptyView
                    } else {
                        meetingSection
                        deadlineSection
                        shoppingSection
                    }
                    footer
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
                    }
                }
                .navigationTitle("日常")
                .onChange(of: store.focusedId) { id in
                    guard let id = id else { return }
                    withAnimation {
                        proxy.scrollTo(id, anchor: .center)
                    }
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

    @ViewBuilder
    private var meetingSection: some View {
        let list = store.snapshot.meetings ?? []
        if !list.isEmpty {
            Section("会議") {
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
