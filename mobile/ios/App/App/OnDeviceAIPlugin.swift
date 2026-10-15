//
//  OnDeviceAIPlugin.swift
//
//  Apple Intelligence の端末内モデルを Web 画面から呼ぶ Capacitor プラグイン。
//  入力と回答は端末の外へ送らない。
//
import Foundation
import Capacitor
#if canImport(FoundationModels)
import FoundationModels
#endif

@objc(OnDeviceAIPlugin)
public class OnDeviceAIPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "OnDeviceAIPlugin"
    public let jsName = "OnDeviceAI"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "status", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "respond", returnType: CAPPluginReturnPromise)
    ]

    @objc func status(_ call: CAPPluginCall) {
        guard #available(iOS 26.0, *) else {
            call.resolve(["available": false, "reason": "oldOS"])
            return
        }

#if canImport(FoundationModels)
        switch SystemLanguageModel.default.availability {
        case .available:
            call.resolve(["available": true, "reason": ""])
        case .unavailable(let reason):
            let code: String
            switch reason {
            case .deviceNotEligible:
                code = "unsupported"
            case .appleIntelligenceNotEnabled:
                code = "disabled"
            case .modelNotReady:
                code = "notReady"
            @unknown default:
                code = "unsupported"
            }
            call.resolve(["available": false, "reason": code])
        @unknown default:
            call.resolve(["available": false, "reason": "unsupported"])
        }
#else
        call.resolve(["available": false, "reason": "unsupported"])
#endif
    }

    @objc func respond(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard #available(iOS 26.0, *) else {
                call.reject("この iOS では端末内 AI を使えません", "unavailable")
                return
            }

#if canImport(FoundationModels)
            guard case .available = SystemLanguageModel.default.availability else {
                call.reject("端末内 AI を利用できません", "unavailable")
                return
            }
            let instructions = call.getString("instructions") ?? ""
            let prompt = call.getString("prompt") ?? ""
            guard !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                call.reject("質問を入力してください", "failed")
                return
            }
            Task {
                do {
                    let session = LanguageModelSession(instructions: instructions)
                    let response = try await session.respond(to: prompt)
                    call.resolve(["text": response.content])
                } catch let error as LanguageModelSession.GenerationError {
                    switch error {
                    case .exceededContextWindowSize(_):
                        call.reject("入力が長すぎます", "tooLong")
                    case .guardrailViolation(_), .refusal(_, _):
                        call.reject("安全上の理由で回答できません", "refused")
                    default:
                        call.reject("回答を作れませんでした", "failed")
                    }
                } catch {
                    call.reject("回答を作れませんでした", "failed")
                }
            }
#else
            call.reject("この端末では端末内 AI を使えません", "unavailable")
#endif
        }
    }
}
