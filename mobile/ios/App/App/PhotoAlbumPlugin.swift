//
//  PhotoAlbumPlugin.swift
//
//  写真アプリの利用者作成アルバムから、キャラクター写真を端末内へ取り込む
//  Capacitor プラグイン。iCloud 上だけにある写真は PhotoKit 経由で取得する。
//
import Foundation
import UIKit
import Photos
import Capacitor

@objc(PhotoAlbumPlugin)
public class PhotoAlbumPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "PhotoAlbumPlugin"
    public let jsName = "PhotoAlbum"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isSupported", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "listAlbums", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "assetIds", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "loadPhoto", returnType: CAPPluginReturnPromise)
    ]

    @objc func isSupported(_ call: CAPPluginCall) {
        call.resolve(["supported": true])
    }

    /// 初回は写真ライブラリの読み取り許可を求め、利用者が作ったアルバムだけを返す。
    @objc func listAlbums(_ call: CAPPluginCall) {
        let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        if current == .notDetermined {
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
                self.resolveAlbums(call, authorization: status)
            }
            return
        }
        resolveAlbums(call, authorization: current)
    }

    /// 選んだアルバムにある写真の番号を、アルバム内の順番で返す。
    @objc func assetIds(_ call: CAPPluginCall) {
        let authorization = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        let status = statusName(for: authorization)
        guard status == "ok" else {
            call.resolve(["status": status, "ids": []])
            return
        }
        guard let albumId = call.getString("albumId"), !albumId.isEmpty else {
            call.reject("album-not-found")
            return
        }

        let collections = PHAssetCollection.fetchAssetCollections(
            withLocalIdentifiers: [albumId],
            options: nil
        )
        guard let album = collections.firstObject, album.assetCollectionType == .album else {
            call.reject("album-not-found")
            return
        }

        let assets = PHAsset.fetchAssets(in: album, options: imageFetchOptions())
        var ids: [String] = []
        assets.enumerateObjects { asset, _, _ in
            ids.append(asset.localIdentifier)
        }
        call.resolve(["status": "ok", "ids": ids])
    }

    /// 写真を縦横比を保ったまま縮小し、JPEG の base64 として返す。
    @objc func loadPhoto(_ call: CAPPluginCall) {
        guard let id = call.getString("id"), !id.isEmpty else {
            call.reject("photo-not-found")
            return
        }
        guard let maxSide = call.getInt("maxSide"), maxSide > 0 else {
            call.reject("invalid-max-side")
            return
        }

        let assets = PHAsset.fetchAssets(withLocalIdentifiers: [id], options: nil)
        guard let asset = assets.firstObject, asset.mediaType == .image else {
            call.reject("photo-not-found")
            return
        }

        let width = CGFloat(asset.pixelWidth)
        let height = CGFloat(asset.pixelHeight)
        guard width > 0, height > 0 else {
            call.reject("photo-load-failed")
            return
        }
        let scale = min(1, CGFloat(maxSide) / max(width, height))
        let targetSize = CGSize(
            width: max(1, (width * scale).rounded(.down)),
            height: max(1, (height * scale).rounded(.down))
        )

        let options = PHImageRequestOptions()
        options.isNetworkAccessAllowed = true
        options.deliveryMode = .highQualityFormat
        options.resizeMode = .exact

        PHImageManager.default().requestImage(
            for: asset,
            targetSize: targetSize,
            contentMode: .aspectFit,
            options: options
        ) { image, info in
            if let degraded = info?[PHImageResultIsDegradedKey] as? Bool, degraded {
                return
            }
            if let cancelled = info?[PHImageCancelledKey] as? Bool, cancelled {
                call.reject("photo-load-failed")
                return
            }
            if info?[PHImageErrorKey] as? Error != nil {
                call.reject("photo-load-failed")
                return
            }
            guard let image = image, let data = image.jpegData(compressionQuality: 0.85) else {
                call.reject("photo-load-failed")
                return
            }
            call.resolve(["data": data.base64EncodedString()])
        }
    }

    private func resolveAlbums(_ call: CAPPluginCall, authorization: PHAuthorizationStatus) {
        let status = statusName(for: authorization)
        guard status == "ok" else {
            call.resolve(["status": status, "albums": []])
            return
        }

        let collections = PHAssetCollection.fetchAssetCollections(
            with: .album,
            subtype: .any,
            options: nil
        )
        var albums: [[String: Any]] = []
        collections.enumerateObjects { album, _, _ in
            let assets = PHAsset.fetchAssets(in: album, options: self.imageFetchOptions())
            albums.append([
                "id": album.localIdentifier,
                "title": album.localizedTitle ?? "",
                "count": assets.count
            ])
        }
        call.resolve(["status": "ok", "albums": albums])
    }

    private func imageFetchOptions() -> PHFetchOptions {
        let options = PHFetchOptions()
        options.predicate = NSPredicate(
            format: "mediaType == %d",
            PHAssetMediaType.image.rawValue
        )
        return options
    }

    private func statusName(for authorization: PHAuthorizationStatus) -> String {
        switch authorization {
        case .authorized:
            return "ok"
        case .limited:
            return "limited"
        case .denied, .restricted, .notDetermined:
            return "denied"
        @unknown default:
            return "denied"
        }
    }
}
