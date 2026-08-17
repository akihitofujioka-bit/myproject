import SwiftUI

/// 画面下部の再生コントロール。
struct PlayerBar: View {
    let document: BookDocument
    @Binding var followsSpeech: Bool

    @EnvironmentObject private var speech: SpeechController
    @State private var scrubValue: Double?

    private var maxIndex: Double { Double(max(0, document.segments.count - 1)) }

    var body: some View {
        VStack(spacing: 10) {
            if let endDate = speech.sleepTimerEndDate {
                HStack(spacing: 6) {
                    Image(systemName: "moon.zzz.fill")
                    Text("おやすみタイマー")
                    Text(endDate, style: .timer)
                        .monospacedDigit()
                    Spacer()
                    Button("解除") { speech.cancelSleepTimer() }
                        .font(.caption)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            if !followsSpeech {
                Button {
                    followsSpeech = true
                } label: {
                    Label("読み上げ位置へ戻る", systemImage: "arrow.down.circle")
                        .font(.caption)
                }
            }

            Slider(
                value: Binding(
                    get: { scrubValue ?? Double(speech.currentIndex) },
                    set: { scrubValue = $0 }
                ),
                in: 0...max(maxIndex, 1),
                step: 1
            ) { editing in
                // 指を離したところで頭出しする。
                if !editing, let value = scrubValue {
                    followsSpeech = true
                    speech.seek(to: Int(value))
                    scrubValue = nil
                }
            }
            .disabled(document.segments.count <= 1)

            HStack {
                Text(positionLabel)
                Spacer()
                if let section = document.sectionTitle(at: speech.currentIndex) {
                    Text(section)
                        .lineLimit(1)
                        .truncationMode(.middle)
                } else if let locator = speech.currentSegment?.locator {
                    Text(locator)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            HStack(spacing: 28) {
                Button {
                    speech.previousHeading()
                } label: {
                    Image(systemName: "backward.end.fill")
                }
                .accessibilityLabel("前の見出しへ")

                Button {
                    speech.previousSegment()
                } label: {
                    Image(systemName: "gobackward")
                }
                .accessibilityLabel("前の文へ")

                Button {
                    followsSpeech = true
                    speech.togglePlayPause()
                } label: {
                    Image(systemName: speech.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 52))
                }
                .accessibilityLabel(speech.isPlaying ? "一時停止" : "再生")

                Button {
                    speech.nextSegment()
                } label: {
                    Image(systemName: "goforward")
                }
                .accessibilityLabel("次の文へ")

                Button {
                    speech.nextHeading()
                } label: {
                    Image(systemName: "forward.end.fill")
                }
                .accessibilityLabel("次の見出しへ")
            }
            .font(.title2)
            .buttonStyle(.plain)
            .foregroundStyle(Color.accentColor)
        }
        .padding(.horizontal)
        .padding(.top, 8)
        .padding(.bottom, 12)
        .background(.bar)
    }

    private var positionLabel: String {
        let total = document.segments.count
        guard total > 0 else { return "" }
        let percent = Int(Double(speech.currentIndex) / Double(max(total - 1, 1)) * 100)
        return "\(speech.currentIndex + 1) / \(total)（\(percent)%）"
    }
}
