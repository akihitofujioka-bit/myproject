import Compression
import Foundation

/// EPUB を開くための最小限の ZIP リーダー。
/// 外部ライブラリを足さずに済むよう、格納（stored）と deflate だけを扱う。
struct ZIPArchive {
    struct Entry {
        let path: String
        let compressionMethod: UInt16
        let compressedSize: Int
        let uncompressedSize: Int
        let localHeaderOffset: Int
    }

    enum ZIPError: LocalizedError {
        case notAZIP
        case corrupted
        case unsupportedCompression(UInt16)
        case zip64Unsupported
        case decompressionFailed
        case entryNotFound(String)

        var errorDescription: String? {
            switch self {
            case .notAZIP: return "ZIP 形式ではありません"
            case .corrupted: return "アーカイブが壊れています"
            case .unsupportedCompression(let method): return "未対応の圧縮方式です（method \(method)）"
            case .zip64Unsupported: return "ZIP64 形式には未対応です"
            case .decompressionFailed: return "展開に失敗しました"
            case .entryNotFound(let path): return "\(path) が見つかりません"
            }
        }
    }

    private let data: Data
    private(set) var entries: [String: Entry] = [:]

    init(data: Data) throws {
        self.data = data
        try parseCentralDirectory()
    }

    init(url: URL) throws {
        try self.init(data: try Data(contentsOf: url, options: .mappedIfSafe))
    }

    func contains(_ path: String) -> Bool {
        entries[ZIPArchive.normalize(path)] != nil
    }

    /// エントリを展開して返す。
    func data(for path: String) throws -> Data {
        let key = ZIPArchive.normalize(path)
        guard let entry = entries[key] else { throw ZIPError.entryNotFound(path) }

        // ローカルヘッダの可変長フィールドを読み飛ばして本体位置を求める。
        let signature: UInt32 = try value(at: entry.localHeaderOffset)
        guard signature == 0x0403_4B50 else { throw ZIPError.corrupted }
        let nameLength: UInt16 = try value(at: entry.localHeaderOffset + 26)
        let extraLength: UInt16 = try value(at: entry.localHeaderOffset + 28)
        let start = entry.localHeaderOffset + 30 + Int(nameLength) + Int(extraLength)
        let end = start + entry.compressedSize
        guard start >= 0, end <= data.count else { throw ZIPError.corrupted }

        let payload = data.subdata(in: start..<end)
        switch entry.compressionMethod {
        case 0:
            return payload
        case 8:
            return try ZIPArchive.inflate(payload, expectedSize: entry.uncompressedSize)
        default:
            throw ZIPError.unsupportedCompression(entry.compressionMethod)
        }
    }

    func string(for path: String) throws -> String {
        let raw = try data(for: path)
        if let utf8 = String(data: raw, encoding: .utf8) { return utf8 }
        if let utf16 = String(data: raw, encoding: .utf16) { return utf16 }
        if let latin = String(data: raw, encoding: .isoLatin1) { return latin }
        throw ZIPError.corrupted
    }

    // MARK: - Central directory

    private mutating func parseCentralDirectory() throws {
        let eocd = try findEndOfCentralDirectory()
        let entryCount: UInt16 = try value(at: eocd + 10)
        let directoryOffset: UInt32 = try value(at: eocd + 16)
        guard directoryOffset != 0xFFFF_FFFF, entryCount != 0xFFFF else { throw ZIPError.zip64Unsupported }

        var offset = Int(directoryOffset)
        for _ in 0..<Int(entryCount) {
            let signature: UInt32 = try value(at: offset)
            guard signature == 0x0201_4B50 else { throw ZIPError.corrupted }

            let method: UInt16 = try value(at: offset + 10)
            let compressedSize: UInt32 = try value(at: offset + 20)
            let uncompressedSize: UInt32 = try value(at: offset + 24)
            let nameLength: UInt16 = try value(at: offset + 28)
            let extraLength: UInt16 = try value(at: offset + 30)
            let commentLength: UInt16 = try value(at: offset + 32)
            let localOffset: UInt32 = try value(at: offset + 42)

            guard compressedSize != 0xFFFF_FFFF,
                  uncompressedSize != 0xFFFF_FFFF,
                  localOffset != 0xFFFF_FFFF else { throw ZIPError.zip64Unsupported }

            let nameStart = offset + 46
            let nameEnd = nameStart + Int(nameLength)
            guard nameEnd <= data.count else { throw ZIPError.corrupted }
            let nameData = data.subdata(in: nameStart..<nameEnd)
            let path = String(data: nameData, encoding: .utf8)
                ?? String(data: nameData, encoding: .isoLatin1)
                ?? ""

            if !path.isEmpty, !path.hasSuffix("/") {
                entries[ZIPArchive.normalize(path)] = Entry(
                    path: path,
                    compressionMethod: method,
                    compressedSize: Int(compressedSize),
                    uncompressedSize: Int(uncompressedSize),
                    localHeaderOffset: Int(localOffset)
                )
            }

            offset = nameEnd + Int(extraLength) + Int(commentLength)
        }

        guard !entries.isEmpty else { throw ZIPError.corrupted }
    }

    /// 末尾から EOCD シグネチャ（0x06054b50）を探す。コメント長の上限は 64KB。
    private func findEndOfCentralDirectory() throws -> Int {
        let minimumSize = 22
        guard data.count >= minimumSize else { throw ZIPArchive.ZIPError.notAZIP }
        let searchLimit = min(data.count, minimumSize + 0xFFFF)
        var offset = data.count - minimumSize
        let lowerBound = data.count - searchLimit

        while offset >= lowerBound {
            let signature: UInt32 = try value(at: offset)
            if signature == 0x0605_4B50 { return offset }
            offset -= 1
        }
        throw ZIPError.notAZIP
    }

    // MARK: - Primitives

    /// リトルエンディアンで固定長整数を読み出す。
    private func value<T: FixedWidthInteger>(at offset: Int) throws -> T {
        let size = MemoryLayout<T>.size
        guard offset >= 0, offset + size <= data.count else { throw ZIPError.corrupted }
        var result: T = 0
        for index in 0..<size {
            result |= T(data[data.startIndex + offset + index]) << (8 * index)
        }
        return result
    }

    /// raw deflate（zlib ヘッダ無し）を展開する。
    static func inflate(_ input: Data, expectedSize: Int) throws -> Data {
        guard expectedSize > 0 else { return Data() }
        guard !input.isEmpty else { throw ZIPError.decompressionFailed }

        var output = Data(count: expectedSize)
        let written: Int = output.withUnsafeMutableBytes { outBuffer in
            input.withUnsafeBytes { inBuffer -> Int in
                guard let outBase = outBuffer.baseAddress?.assumingMemoryBound(to: UInt8.self),
                      let inBase = inBuffer.baseAddress?.assumingMemoryBound(to: UInt8.self) else {
                    return 0
                }
                return compression_decode_buffer(
                    outBase, expectedSize,
                    inBase, input.count,
                    nil, COMPRESSION_ZLIB
                )
            }
        }

        guard written > 0 else { throw ZIPError.decompressionFailed }
        return written == expectedSize ? output : Data(output.prefix(written))
    }

    /// "./OEBPS/../text/ch1.xhtml" のような表記を素直なパスへ揃える。
    static func normalize(_ path: String) -> String {
        var components: [String] = []
        for component in path.split(separator: "/", omittingEmptySubsequences: true) {
            switch component {
            case ".": continue
            case "..": if !components.isEmpty { components.removeLast() }
            default: components.append(String(component))
            }
        }
        return components.joined(separator: "/")
    }

    /// baseDirectory を起点に相対パスを解決する。
    static func resolve(_ path: String, relativeTo baseDirectory: String) -> String {
        if path.hasPrefix("/") { return normalize(path) }
        guard !baseDirectory.isEmpty else { return normalize(path) }
        return normalize(baseDirectory + "/" + path)
    }
}
