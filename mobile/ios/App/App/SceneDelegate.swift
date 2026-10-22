import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        // 素の CAPBridgeViewController ではなく、自作プラグイン（レシート撮影）を登録する
        // ViewController を使う。以前は素の画面を生成していたため、storyboard で指定した
        // ViewController が使われず、プラグインの登録コードが一度も動いていなかった。
        window?.rootViewController = ViewController()
        window?.makeKeyAndVisible()
        // 開くときに Face ID で確かめる（AppLock.swift）
        AppLock.shared.attach(to: window)

        connectionOptions.urlContexts.forEach { context in
            if context.url.isFileURL {
                DocumentReaderPlugin.receive(url: context.url)
            }
        }

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        URLContexts.forEach { context in
            if context.url.isFileURL {
                DocumentReaderPlugin.receive(url: context.url)
            }
        }
        let otherContexts = Set(URLContexts.filter { !$0.url.isFileURL })
        if !otherContexts.isEmpty {
            SceneDelegateProxy.shared.scene(scene, openURLContexts: otherContexts)
        }
    }

    func sceneDidBecomeActive(_ scene: UIScene) {
        AppLock.shared.didBecomeActive()
    }

    func sceneDidEnterBackground(_ scene: UIScene) {
        AppLock.shared.didEnterBackground()
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
