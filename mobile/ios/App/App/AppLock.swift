//
//  AppLock.swift
//
//  アプリを開くときに Face ID（使えなければパスコード）で確かめる。
//
//  ・起動したときと、ほかのアプリへ移ってから 5 分以上たって戻ったときに求める
//    （カメラやカレンダーを少し行き来するたびに聞かないため）
//  ・ほかのアプリへ移ったら画面を覆い、アプリ切り替えの一覧に中身が映らないようにする
//  ・iPhone 標準の「Face ID を必要にする」と違い、ロック画面のウィジェット・Watch・Siri は今までどおり動く
//  ・パスコードを設定していない端末では、確かめずにそのまま開く
//
import UIKit
import LocalAuthentication

final class AppLock {
    static let shared = AppLock()

    /// ほかのアプリへ移ってから、この秒数を過ぎて戻ったら確かめる
    private let graceSeconds: TimeInterval = 5 * 60

    /// 移った時刻。端末の時計（利用者が変えられる）ではなく、起動してからの経過時間で測る
    private var backgroundUptime: TimeInterval?
    private var locked = true          // 起動直後は確かめる
    private var authenticating = false
    private weak var window: UIWindow?
    /// 覆いは専用の窓に出す。今の画面に重ねるだけだと、後から出た画面（カメラなど）が上に来てしまうため
    private var lockWindow: UIWindow?
    private var cover: UIView?

    func attach(to window: UIWindow?) {
        self.window = window
        if locked { showCover() }
    }

    /// ほかのアプリへ移ったとき
    func didEnterBackground() {
        backgroundUptime = ProcessInfo.processInfo.systemUptime
        showCover()
    }

    /// 戻ってきたとき（起動直後も含む）
    func didBecomeActive() {
        if let at = backgroundUptime {
            let elapsed = ProcessInfo.processInfo.systemUptime - at
            // 測れないずれ（マイナス）が出たときも、ロックする側に倒す
            if elapsed >= graceSeconds || elapsed < 0 { locked = true }
        }
        backgroundUptime = nil
        if locked { authenticate() } else { hideCover() }
    }

    private func authenticate() {
        guard !authenticating else { return }
        let context = LAContext()
        var error: NSError?
        // パスコードも無い端末では守る手段が無いので、そのまま開く
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            unlock()
            return
        }
        authenticating = true
        showCover()
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "壱師を開きます") { success, _ in
            DispatchQueue.main.async {
                self.authenticating = false
                if success { self.unlock() } else { self.showRetry() }
            }
        }
    }

    private func unlock() {
        locked = false
        hideCover()
    }

    // MARK: - 覆い

    private func showCover() {
        guard let window = window, let scene = window.windowScene else { return }
        // 覆っているあいだは、読み上げ機能（VoiceOver）にも元の画面の中身を見せない
        window.accessibilityElementsHidden = true
        if lockWindow != nil, cover != nil {
            lockWindow?.isHidden = false
            lockWindow?.makeKeyAndVisible()
            return
        }
        let overlay = UIWindow(windowScene: scene)
        overlay.windowLevel = .alert + 1
        overlay.rootViewController = UIViewController()
        let view = UIView(frame: overlay.bounds)
        view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.backgroundColor = .systemBackground

        let stack = UIStackView()
        stack.axis = .vertical
        stack.alignment = .center
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false

        let icon = UIImageView(image: UIImage(systemName: "lock.fill"))
        icon.tintColor = .secondaryLabel
        icon.preferredSymbolConfiguration = UIImage.SymbolConfiguration(pointSize: 40)

        let title = UILabel()
        title.text = "壱師"
        title.font = .systemFont(ofSize: 28, weight: .bold)

        let button = UIButton(type: .system)
        button.setTitle("Face ID で開く", for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 18, weight: .semibold)
        button.addTarget(self, action: #selector(retryTapped), for: .touchUpInside)
        button.isHidden = true
        button.tag = 1

        stack.addArrangedSubview(icon)
        stack.addArrangedSubview(title)
        stack.addArrangedSubview(button)
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
        overlay.rootViewController?.view.addSubview(view)
        overlay.makeKeyAndVisible()
        lockWindow = overlay
        cover = view
    }

    /// Face ID を取り消したときなどは、もう一度試すボタンを出す
    private func showRetry() {
        showCover()
        cover?.viewWithTag(1)?.isHidden = false
    }

    private func hideCover() {
        cover = nil
        lockWindow?.isHidden = true
        lockWindow = nil
        window?.accessibilityElementsHidden = false
        window?.makeKeyAndVisible()
    }

    @objc private func retryTapped() {
        cover?.viewWithTag(1)?.isHidden = true
        authenticate()
    }
}
