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
import CoreImage

final class AppLock {
    static let shared = AppLock()

    /// ほかのアプリへ移ってから、この秒数を過ぎて戻ったら確かめる
    private let graceSeconds: TimeInterval = 5 * 60

    /// 移った時刻。スリープ中も進む時計（CLOCK_MONOTONIC。利用者は変えられない）と、端末の時計の両方で覚える
    private var backgroundMonotonic: UInt64?
    private var backgroundWallClock: Date?
    private var locked = true          // 起動直後は確かめる
    private var authenticating = false
    private weak var window: UIWindow?
    /// 覆いは専用の窓に出す。今の画面に重ねるだけだと、後から出た画面（カメラなど）が上に来てしまうため
    private var lockWindow: UIWindow?
    private var cover: UIView?

    func attach(to window: UIWindow?) {
        self.window = window
        if locked { showCover() }
        // iPhone 本体がロックされたら、アプリもロックする
        NotificationCenter.default.addObserver(forName: UIApplication.protectedDataWillBecomeUnavailableNotification,
                                               object: nil, queue: .main) { [weak self] _ in
            self?.locked = true
            self?.showCover()
        }
    }

    private static func monotonicNow() -> UInt64 {
        clock_gettime_nsec_np(CLOCK_MONOTONIC)
    }

    /// ほかのアプリへ移ったとき
    func didEnterBackground() {
        backgroundMonotonic = Self.monotonicNow()
        backgroundWallClock = Date()
        showCover()
    }

    /// 戻ってきたとき（起動直後も含む）
    func didBecomeActive() {
        if let at = backgroundMonotonic, let wall = backgroundWallClock {
            let now = Self.monotonicNow()
            let monotonic = now >= at ? TimeInterval(now - at) / 1_000_000_000 : -1
            let wallElapsed = Date().timeIntervalSince(wall)
            // どちらかで 5 分を過ぎたとき、または時計が戻っていたときは、ロックする側に倒す
            if monotonic < 0 || wallElapsed < 0 || monotonic >= graceSeconds || wallElapsed >= graceSeconds {
                locked = true
            }
        }
        backgroundMonotonic = nil
        backgroundWallClock = nil
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
        view.backgroundColor = .black

        // 背景に壱師のアイコンのイラストを敷き、ぼかして暗めにする（中身は見せない）
        let background = UIImageView(image: Self.softenedBackground())
        background.frame = view.bounds
        background.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        background.contentMode = .scaleAspectFill
        background.clipsToBounds = true
        view.addSubview(background)
        // 文字が読めるよう、薄く暗くする
        let shade = UIView(frame: view.bounds)
        shade.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        shade.backgroundColor = UIColor.black.withAlphaComponent(0.3)
        view.addSubview(shade)

        let stack = UIStackView()
        stack.axis = .vertical
        stack.alignment = .center
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false

        let icon = UIImageView(image: UIImage(systemName: "lock.fill"))
        icon.tintColor = UIColor.white.withAlphaComponent(0.85)
        icon.preferredSymbolConfiguration = UIImage.SymbolConfiguration(pointSize: 40)

        let title = UILabel()
        title.text = "壱師"
        title.font = .systemFont(ofSize: 28, weight: .bold)
        title.textColor = .white

        let button = UIButton(type: .system)
        button.setTitle("Face ID で開く", for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 18, weight: .semibold)
        button.tintColor = .white
        button.addTarget(self, action: #selector(retryTapped), for: .touchUpInside)
        button.isHidden = true
        button.tag = 1

        // 絵の上でも文字が読めるよう、薄い影を付ける
        for item in [icon, title, button] as [UIView] {
            item.layer.shadowColor = UIColor.black.cgColor
            item.layer.shadowOpacity = 0.6
            item.layer.shadowRadius = 4
            item.layer.shadowOffset = .zero
        }

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

    /// 背景のイラストは日替わり。壱師と各アプリのアイコンの絵（LockBackground〜LockBackground7）を順に使う
    private static func todaysBackgroundName(_ date: Date = Date()) -> String {
        let names = ["LockBackground"] + (2...7).map { "LockBackground\($0)" }
        let day = Calendar.current.ordinality(of: .day, in: .era, for: date) ?? 0
        return names[day % names.count]
    }

    /// 背景のイラストを軽くぼかす（絵柄は分かる程度。強さは radius で決める）
    private static func softenedBackground() -> UIImage? {
        let image = UIImage(named: todaysBackgroundName()) ?? UIImage(named: "LockBackground")
        guard let image = image, let input = CIImage(image: image) else { return nil }
        let filter = CIFilter(name: "CIGaussianBlur")
        filter?.setValue(input.clampedToExtent(), forKey: kCIInputImageKey)
        filter?.setValue(6, forKey: kCIInputRadiusKey)
        guard let output = filter?.outputImage?.cropped(to: input.extent),
              let cg = CIContext().createCGImage(output, from: input.extent) else { return image }
        return UIImage(cgImage: cg)
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
