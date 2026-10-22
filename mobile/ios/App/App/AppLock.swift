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

    private var backgroundAt: Date?
    private var locked = true          // 起動直後は確かめる
    private var authenticating = false
    private weak var window: UIWindow?
    private var cover: UIView?

    func attach(to window: UIWindow?) {
        self.window = window
        if locked { showCover() }
    }

    /// ほかのアプリへ移ったとき
    func didEnterBackground() {
        backgroundAt = Date()
        showCover()
    }

    /// 戻ってきたとき（起動直後も含む）
    func didBecomeActive() {
        if let at = backgroundAt, Date().timeIntervalSince(at) >= graceSeconds { locked = true }
        backgroundAt = nil
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
        guard let window = window else { return }
        if let cover = cover {
            window.bringSubviewToFront(cover)
            return
        }
        let view = UIView(frame: window.bounds)
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
        window.addSubview(view)
        cover = view
    }

    /// Face ID を取り消したときなどは、もう一度試すボタンを出す
    private func showRetry() {
        showCover()
        cover?.viewWithTag(1)?.isHidden = false
    }

    private func hideCover() {
        cover?.removeFromSuperview()
        cover = nil
    }

    @objc private func retryTapped() {
        cover?.viewWithTag(1)?.isHidden = true
        authenticate()
    }
}
