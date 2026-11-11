//
//  FaceView.swift
//
//  Watch アプリを開いたときの最初の画面。機能にすぐ進めるショートカットの画面で、
//  8つのボタン（予定・期限・TODO・買い物・次・全部・更新・情報）を2列に並べる。
//  背景には利用者のイラストを透かして敷き、ボタンは強い色を黒い太線で縁取る劇画風の配色にしている。
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

/// 漫画の効果線を思わせる、角の立ったボタン枠
private struct ComicBadgeShape: Shape {
    func path(in rect: CGRect) -> Path {
        let points: [CGPoint] = [
            CGPoint(x: 0.18, y: 0.02), CGPoint(x: 0.76, y: 0.00),
            CGPoint(x: 1.00, y: 0.25), CGPoint(x: 0.94, y: 0.78),
            CGPoint(x: 0.70, y: 1.00), CGPoint(x: 0.19, y: 0.95),
            CGPoint(x: 0.00, y: 0.72), CGPoint(x: 0.04, y: 0.23),
        ]
        var path = Path()
        for (index, point) in points.enumerated() {
            let position = CGPoint(
                x: rect.minX + point.x * rect.width,
                y: rect.minY + point.y * rect.height
            )
            if index == 0 { path.move(to: position) } else { path.addLine(to: position) }
        }
        path.closeSubpath()
        return path
    }
}

struct FaceView: View {
    @ObservedObject var store: WatchStore
    let open: (FacePanel) -> Void

    private var buttons: [FaceButton] {
        let s = store.snapshot
        let meetings = (s.meetings ?? []).filter { !$0.hasEnded() }.count
        return [
            // 左上から右へ、よく使う順
            FaceButton(label: "予定", symbol: "calendar", color: JojoPalette.magenta, panel: .meetings, count: meetings),
            FaceButton(label: "TODO", symbol: "checklist", color: JojoPalette.lime, panel: .todos, count: s.todos?.count ?? 0),
            FaceButton(label: "期限", symbol: "doc.text", color: JojoPalette.gold, panel: .deadlines, count: s.deadlines?.count ?? 0),
            FaceButton(label: "買い物", symbol: "cart", color: JojoPalette.orange, panel: .shopping, count: s.shopping?.count ?? 0),
            FaceButton(label: "次", symbol: "forward.fill", color: JojoPalette.cyan, panel: .next, count: 0),
            FaceButton(label: "全部", symbol: "list.bullet", color: JojoPalette.violet, panel: .all, count: 0),
            FaceButton(label: "更新", symbol: "arrow.clockwise", color: JojoPalette.teal, panel: nil, count: 0),
            FaceButton(label: "情報", symbol: "info", color: JojoPalette.red, panel: .info, count: 0),
        ]
    }

    var body: some View {
        GeometryReader { geo in
            let gap: CGFloat = 6
            let width = (geo.size.width - gap * 3) / 2
            // 4段が1画面に収まり、ボタンの間からイラストが見える高さにする
            let height = max(34, min(width * 0.46, (geo.size.height - gap * 5) / 4))
            ScrollView {
                LazyVGrid(columns: [GridItem(.fixed(width), spacing: gap), GridItem(.fixed(width), spacing: gap)],
                          spacing: gap) {
                    ForEach(Array(buttons.enumerated()), id: \.offset) { _, b in
                        buttonView(b, width: width, height: height)
                    }
                }
                .padding(.vertical, gap)
            }
            .background(ScreentoneBackground())
        }
        .toolbar(.hidden, for: .navigationBar)
    }

    private func buttonView(_ b: FaceButton, width: CGFloat, height: CGFloat) -> some View {
        Button {
            if let panel = b.panel { open(panel) } else { store.requestLatest() }
        } label: {
            ZStack(alignment: .topTrailing) {
                ComicBadgeShape()
                    .fill(JojoPalette.ink)
                    .offset(x: 2, y: 3)
                ComicBadgeShape()
                    .fill(b.color.opacity(0.92))
                    .overlay(ComicBadgeShape().stroke(.white, lineWidth: 1).padding(3))
                    .overlay(ComicBadgeShape().stroke(JojoPalette.ink, lineWidth: 2.5))
                HStack(spacing: 4) {
                    Image(systemName: b.symbol)
                        .font(.system(size: height * 0.42, weight: .heavy))
                        .rotationEffect(.degrees(b.panel == nil && store.isRequesting ? 180 : 0))
                    Text(b.label)
                        .font(.system(size: max(11, height * 0.34), weight: .black, design: .rounded))
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                .foregroundStyle(.white)
                .shadow(color: JojoPalette.ink, radius: 0, x: 1, y: 1)
                .frame(width: width, height: height)
                if b.count > 0 {
                    Text(b.count > 99 ? "99+" : "\(b.count)")
                        .font(.system(size: 10, weight: .black))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 4)
                        .background(Capsule().fill(.white).overlay(Capsule().stroke(.black, lineWidth: 1)))
                        .offset(x: 3, y: -3)
                }
            }
            .frame(width: width, height: height)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(b.count > 0 ? "\(b.label) \(b.count)件" : b.label)
    }
}

/// 背景。利用者のイラストを透かして敷き、上のボタンが読めるよう暗い紫を重ねる
private struct ScreentoneBackground: View {
    var body: some View {
        GeometryReader { geo in
            ZStack {
                JojoPalette.backdrop
                Image("ShortcutBackground")
                    .resizable()
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()
                    .opacity(0.55)
                Color.black.opacity(0.25)
            }
        }
        .ignoresSafeArea()
    }
}
