//
//  ViewController.swift
//
//  アプリ内で定義したプラグインを Capacitor に登録するための入口。
//  Main.storyboard の画面クラスをこのクラスにしてある。
//
import UIKit
import Capacitor

class ViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(ReceiptScannerPlugin())
        // 登録が実際に行われたことを起動ログで確認できるようにする
        CAPLog.print("⚡️  ReceiptScanner plugin registered")
    }
}
