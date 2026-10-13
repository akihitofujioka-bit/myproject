import Foundation
import Compression

/// 外部ライブラリに依存せず ZIP を読み込む軽量リーダー。
/// 圧縮方式 0（無圧縮）と 8（deflate）に対応する。
struct ZipReader {
    enum ZipError: Error {
        case invalidArchive
    }

    let entries: [String: Data]

    init(data: Data) throws {
        let bytes = [UInt8](data)
        guard let endOffset = Self.findEndOfCentralDirectory(bytes) else {
            throw ZipError.invalidArchive
        }

        let entryCount = Int(Self.readUInt16(bytes, endOffset + 10))
        let centralOffset = Int(Self.readUInt32(bytes, endOffset + 16))
        var result: [String: Data] = [:]
        var position = centralOffset

        for _ in 0..<entryCount {
            guard position >= 0,
                  position + 46 <= bytes.count,
                  Self.readUInt32(bytes, position) == 0x02014b50 else {
                throw ZipError.invalidArchive
            }

            let method = Self.readUInt16(bytes, position + 10)
            let compressedSize = Int(Self.readUInt32(bytes, position + 20))
            let uncompressedSize = Int(Self.readUInt32(bytes, position + 24))
            let nameLength = Int(Self.readUInt16(bytes, position + 28))
            let extraLength = Int(Self.readUInt16(bytes, position + 30))
            let commentLength = Int(Self.readUInt16(bytes, position + 32))
            let localOffset = Int(Self.readUInt32(bytes, position + 42))

            guard position + 46 + nameLength <= bytes.count,
                  localOffset >= 0,
                  localOffset + 30 <= bytes.count,
                  Self.readUInt32(bytes, localOffset) == 0x04034b50 else {
                throw ZipError.invalidArchive
            }

            let name = String(
                decoding: bytes[(position + 46)..<(position + 46 + nameLength)],
                as: UTF8.self
            )
            let localNameLength = Int(Self.readUInt16(bytes, localOffset + 26))
            let localExtraLength = Int(Self.readUInt16(bytes, localOffset + 28))
            let dataOffset = localOffset + 30 + localNameLength + localExtraLength
            guard dataOffset >= 0, dataOffset + compressedSize <= bytes.count else {
                throw ZipError.invalidArchive
            }

            let compressed = Data(bytes[dataOffset..<(dataOffset + compressedSize)])
            switch method {
            case 0:
                result[name] = compressed
            case 8:
                guard let inflated = Self.inflate(compressed, expectedSize: uncompressedSize) else {
                    throw ZipError.invalidArchive
                }
                result[name] = inflated
            default:
                throw ZipError.invalidArchive
            }

            position += 46 + nameLength + extraLength + commentLength
        }

        entries = result
    }

    private static func inflate(_ data: Data, expectedSize: Int) -> Data? {
        guard expectedSize > 0 else { return data.isEmpty ? Data() : nil }
        var destination = Data(count: expectedSize)
        let written = destination.withUnsafeMutableBytes { destinationBytes -> Int in
            data.withUnsafeBytes { sourceBytes -> Int in
                guard let destinationAddress = destinationBytes.bindMemory(to: UInt8.self).baseAddress,
                      let sourceAddress = sourceBytes.bindMemory(to: UInt8.self).baseAddress else {
                    return 0
                }
                return compression_decode_buffer(
                    destinationAddress,
                    expectedSize,
                    sourceAddress,
                    data.count,
                    nil,
                    COMPRESSION_ZLIB
                )
            }
        }
        guard written == expectedSize else { return nil }
        return destination
    }

    private static func readUInt16(_ bytes: [UInt8], _ offset: Int) -> UInt16 {
        UInt16(bytes[offset]) | (UInt16(bytes[offset + 1]) << 8)
    }

    private static func readUInt32(_ bytes: [UInt8], _ offset: Int) -> UInt32 {
        UInt32(bytes[offset])
            | (UInt32(bytes[offset + 1]) << 8)
            | (UInt32(bytes[offset + 2]) << 16)
            | (UInt32(bytes[offset + 3]) << 24)
    }

    /// 末尾から ZIP の中央ディレクトリ終端を探す。
    private static func findEndOfCentralDirectory(_ bytes: [UInt8]) -> Int? {
        guard bytes.count >= 22 else { return nil }
        var offset = bytes.count - 22
        let lowerBound = max(0, bytes.count - 22 - 65_535)
        while offset >= lowerBound {
            if bytes[offset] == 0x50,
               bytes[offset + 1] == 0x4b,
               bytes[offset + 2] == 0x05,
               bytes[offset + 3] == 0x06 {
                return offset
            }
            offset -= 1
        }
        return nil
    }
}
