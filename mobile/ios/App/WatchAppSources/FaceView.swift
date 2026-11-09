//
//  FaceView.swift
//
//  Watch アプリを開いたときの最初の画面。アナログの針とデジタルの時刻を重ね、
//  周りに8つのボタン（予定・期限・TODO・買い物・次・全部・更新・情報）を並べる。
//  色は、紫・金・桃・緑などの強い色を黒い太線で縁取る、劇画風の配色にしている。
//  （watchOS では、アプリが本物の文字盤を差し替えることはできないため、アプリの画面として作っている）
//
import SwiftUI

/// 劇画風の配色。強い原色を黒の太い縁取りで締める
enum JojoPalette {
    static let ink = Color.black
    static let gold = Color(red: 1.00, green: 0.78, blue: 0.10)
    static let magenta = Color(red: 0.90, green: 0.00, blue: 0.50)
    static let violet = Color(red: 0.56, green: 0.27, blue: 0.93)
    static let teal = Color(red: 0.00, green: 0.65, blue: 0.65)
    static let lime = Color(red: 0.61, green: 0.89, blue: 0.18)
    static let orange = Color(red: 1.00, green: 0.48, blue: 0.00)
    static let cyan = Color(red: 0.00, green: 0.76, blue: 1.00)
    static let red = Color(red: 0.91, green: 0.20, blue: 0.24)
    static let deepPurple = Color(red: 0.17, green: 0.04, blue: 0.24)
    static let wine = Color(red: 0.48, green: 0.12, blue: 0.42)

    static let backdrop = LinearGradient(
        colors: [deepPurple, wine],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
}

/// 文字盤の周りのボタン1つ分
private struct FaceButton {
    let label: String
    let symbol: String
    let color: Color
    let panel: FacePanel?   // nil は「更新」（画面を移らずに最新を取りに行く）
    let count: Int
}

struct FaceView: View {
    @ObservedObject var store: WatchStore
    let open: (FacePanel) -> Void

    private var buttons: [FaceButton] {
        let s = store.snapshot
        let meetings = (s.meetings ?? []).filter { !$0.hasEnded() }.count
        return [
            // 上から時計回り
            FaceButton(label: "予定", symbol: "calendar", color: JojoPalette.magenta, panel: .meetings, count: meetings),
            FaceButton(label: "期限", symbol: "doc.text", color: JojoPalette.gold, panel: .deadlines, count: s.deadlines?.count ?? 0),
            FaceButton(label: "TODO", symbol: "checklist", color: JojoPalette.lime, panel: .todos, count: s.todos?.count ?? 0),
            FaceButton(label: "買い物", symbol: "cart", color: JojoPalette.orange, panel: .shopping, count: s.shopping?.count ?? 0),
            FaceButton(label: "次", symbol: "forward.fill", color: JojoPalette.cyan, panel: .next, count: 0),
            FaceButton(label: "全部", symbol: "list.bullet", color: JojoPalette.violet, panel: .all, count: 0),
            FaceButton(label: "更新", symbol: "arrow.clockwise", color: JojoPalette.teal, panel: nil, count: 0),
            FaceButton(label: "情報", symbol: "info", color: JojoPalette.red, panel: .info, count: 0),
        ]
    }

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            let size = min(w, h) * 0.22
            let rx = w / 2 - size / 2
            let ry = h / 2 - size / 2
            let dial = max((min(rx, ry) - size / 2) * 0.86, 30)
            ZStack {
                ScreentoneBackground()
                DialView(radius: dial, isRequesting: store.isRequesting)
                    .position(x: w / 2, y: h / 2)
                ForEach(Array(buttons.enumerated()), id: \.offset) { i, b in
                    let angle = Double(i) * .pi / 4 - .pi / 2
                    buttonView(b, size: size)
                        .position(x: w / 2 + rx * cos(angle), y: h / 2 + ry * sin(angle))
                }
            }
        }
        .toolbar(.hidden, for: .navigationBar)
    }

    private func buttonView(_ b: FaceButton, size: CGFloat) -> some View {
        Button {
            if let panel = b.panel { open(panel) } else { store.requestLatest() }
        } label: {
            ZStack(alignment: .topTrailing) {
                Circle()
                    .fill(b.color)
                    .overlay(Circle().stroke(JojoPalette.ink, lineWidth: 2.5))
                    .overlay(
                        Image(systemName: b.symbol)
                            .font(.system(size: size * 0.42, weight: .heavy))
                            .foregroundStyle(.white)
                            .shadow(color: .black, radius: 0, x: 1, y: 1)
                            .rotationEffect(.degrees(b.panel == nil && store.isRequesting ? 180 : 0))
                    )
                if b.count > 0 {
                    Text(b.count > 99 ? "99+" : "\(b.count)")
                        .font(.system(size: 9, weight: .black))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 3)
                        .background(Capsule().fill(.white).overlay(Capsule().stroke(.black, lineWidth: 1)))
                        .offset(x: 4, y: -3)
                }
            }
            .frame(width: size, height: size)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(b.count > 0 ? "\(b.label) \(b.count)件" : b.label)
    }
}

/// 背景。紫のグラデーションに、漫画のトーンのような斜めの線を薄く重ねる
private struct ScreentoneBackground: View {
    var body: some View {
        ZStack {
            JojoPalette.backdrop
            Canvas { ctx, size in
                var path = Path()
                let step: CGFloat = 7
                var x: CGFloat = -size.height
                while x < size.width {
                    path.move(to: CGPoint(x: x, y: size.height))
                    path.addLine(to: CGPoint(x: x + size.height, y: 0))
                    x += step
                }
                ctx.stroke(path, with: .color(.white.opacity(0.06)), lineWidth: 1)
            }
        }
        .ignoresSafeArea()
    }
}

/// 中央の時計。アナログの針と、針の下にデジタルの時刻・日付を重ねる
private struct DialView: View {
    let radius: CGFloat
    let isRequesting: Bool

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let date = context.date
            let cal = Calendar.current
            let hour = Double(cal.component(.hour, from: date) % 12)
            let minute = Double(cal.component(.minute, from: date))
            let second = Double(cal.component(.second, from: date))
            ZStack {
                // 盤面: 金の太い縁と黒の縁取り、内側は紫
                Circle()
                    .fill(RadialGradient(colors: [JojoPalette.violet, JojoPalette.deepPurple],
                                         center: .center, startRadius: 0, endRadius: radius))
                Circle()
                    .stroke(JojoPalette.gold, lineWidth: radius * 0.10)
                Circle()
                    .stroke(JojoPalette.ink, lineWidth: 2)
                    .padding(-radius * 0.05)
                Circle()
                    .stroke(JojoPalette.ink, lineWidth: 1.5)
                    .padding(radius * 0.05)

                // 目盛り（3・6・9・12 は太く桃色）
                ForEach(0..<12) { i in
                    let major = i % 3 == 0
                    Capsule()
                        .fill(major ? JojoPalette.magenta : .white)
                        .overlay(Capsule().stroke(.black, lineWidth: major ? 1 : 0))
                        .frame(width: major ? 3.5 : 1.5, height: radius * (major ? 0.20 : 0.12))
                        .offset(y: -radius * 0.78)
                        .rotationEffect(.degrees(Double(i) * 30))
                }

                // デジタル: 上に日付、下に時刻
                Text(dateText(date))
                    .font(.system(size: radius * 0.20, weight: .heavy, design: .rounded))
                    .foregroundStyle(JojoPalette.lime)
                    .shadow(color: .black, radius: 0, x: 1, y: 1)
                    .offset(y: -radius * 0.38)
                Text(timeText(date))
                    .font(.system(size: radius * 0.30, weight: .black, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(JojoPalette.gold)
                    .padding(.horizontal, 4)
                    .background(RoundedRectangle(cornerRadius: 4).fill(.black.opacity(0.75)))
                    .offset(y: radius * 0.40)

                // 針（時: 金、分: 桃、秒: 緑）。黒で縁取る
                hand(length: radius * 0.50, width: 5, color: JojoPalette.gold,
                     degrees: (hour + minute / 60) * 30)
                hand(length: radius * 0.72, width: 3.5, color: JojoPalette.magenta,
                     degrees: (minute + second / 60) * 6)
                hand(length: radius * 0.80, width: 1.5, color: JojoPalette.lime,
                     degrees: second * 6)
                Circle()
                    .fill(JojoPalette.gold)
                    .overlay(Circle().stroke(.black, lineWidth: 1.5))
                    .frame(width: 7, height: 7)
            }
            .frame(width: radius * 2, height: radius * 2)
            .opacity(isRequesting ? 0.7 : 1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("時計")
    }

    private func hand(length: CGFloat, width: CGFloat, color: Color, degrees: Double) -> some View {
        Capsule()
            .fill(color)
            .overlay(Capsule().stroke(.black, lineWidth: 1))
            .frame(width: width, height: length)
            .offset(y: -length / 2)
            .rotationEffect(.degrees(degrees))
    }

    private func timeText(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ja_JP")
        f.dateFormat = "H:mm"
        return f.string(from: date)
    }

    private func dateText(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ja_JP")
        f.dateFormat = "M/d(E)"
        return f.string(from: date)
    }
}
