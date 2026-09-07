import UIKit
import Capacitor

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        excludeAppDataFromBackup()
        return true
    }

    /// 秘密鍵と会話の履歴を、iCloud やパソコンへのバックアップに含めない。
    ///
    /// このアプリの鍵は端末の中だけにあることを前提にしている。バックアップに含めると、
    /// 鍵と履歴の複製が端末の外に出てしまうため、明示的に対象から外す。
    /// Android 側でも同じ考えで自動バックアップを無効にしている。
    ///
    /// この結果、**機種変更してもメッセージは引き継がれない**。
    /// 引き継ぐときは、アプリの設定にある「JSONで保存」を使う。
    ///
    /// バックアップに含めたい場合は、下の呼び出し（excludeAppDataFromBackup）を消す。
    private func excludeAppDataFromBackup() {
        let manager = FileManager.default
        let targets: [FileManager.SearchPathDirectory] = [.libraryDirectory, .documentDirectory]
        for target in targets {
            guard var url = manager.urls(for: target, in: .userDomainMask).first else { continue }
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try? url.setResourceValues(values)
        }
    }

    func application(_ application: UIApplication,
                     configurationForConnecting connectingSceneSession: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let config = UISceneConfiguration(name: "Default Configuration",
                                          sessionRole: connectingSceneSession.role)
        config.delegateClass = SceneDelegate.self
        return config
    }
}
