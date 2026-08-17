import AVFoundation
import SwiftUI

/// 速度・声・おやすみタイマーの設定。
struct SpeechSettingsView: View {
    @EnvironmentObject private var speech: SpeechController
    @Environment(\.dismiss) private var dismiss

    private let sleepOptions = [5, 10, 15, 30, 45, 60]

    var body: some View {
        NavigationStack {
            Form {
                Section("読み上げ速度") {
                    VStack(alignment: .leading) {
                        HStack {
                            Text("速さ")
                            Spacer()
                            Text(String(format: "×%.2f", speech.speechRate))
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $speech.speechRate, in: 0.5...2.0, step: 0.05) {
                            Text("速さ")
                        } minimumValueLabel: {
                            Image(systemName: "tortoise")
                        } maximumValueLabel: {
                            Image(systemName: "hare")
                        }
                    }

                    VStack(alignment: .leading) {
                        HStack {
                            Text("声の高さ")
                            Spacer()
                            Text(String(format: "×%.2f", speech.pitch))
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $speech.pitch, in: 0.5...2.0, step: 0.05)
                    }

                    Text("速度や声を変えると、いま読んでいる文の先頭から読み直します。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    ForEach(VoiceCatalog.allGroups()) { group in
                        DisclosureGroup(group.displayName) {
                            ForEach(group.voices, id: \.identifier) { voice in
                                Button {
                                    speech.voiceIdentifier = voice.identifier
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(voice.name)
                                                .foregroundStyle(.primary)
                                            Text(VoiceCatalog.qualityLabel(voice.quality))
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        if speech.voiceIdentifier == voice.identifier {
                                            Image(systemName: "checkmark")
                                                .foregroundStyle(Color.accentColor)
                                        }
                                    }
                                }
                            }
                        }
                    }
                } header: {
                    Text("声")
                } footer: {
                    Text("「設定 > アクセシビリティ > 読み上げコンテンツ > 声」から高品質な音声を追加すると、ここに表示されます。")
                }

                Section("おやすみタイマー") {
                    if let endDate = speech.sleepTimerEndDate {
                        HStack {
                            Text("停止まで")
                            Spacer()
                            Text(endDate, style: .timer)
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        Button("タイマーを解除", role: .destructive) {
                            speech.cancelSleepTimer()
                        }
                    } else {
                        ForEach(sleepOptions, id: \.self) { minutes in
                            Button("\(minutes) 分後に停止") {
                                speech.startSleepTimer(minutes: minutes)
                            }
                        }
                    }
                }
            }
            .navigationTitle("読み上げ設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完了") { dismiss() }
                }
            }
        }
    }
}
