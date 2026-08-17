import Foundation

enum ParseError: LocalizedError {
    case unsupportedFormat(String)
    case unreadableFile
    case encryptedPDF
    case noExtractableText
    case brokenEPUB(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedFormat(let ext):
            return "対応していない形式です（.\(ext)）。PDF・EPUB・テキスト（.txt / .md）を選んでください。"
        case .unreadableFile:
            return "ファイルを読み込めませんでした。壊れている可能性があります。"
        case .encryptedPDF:
            return "パスワードで保護された PDF は開けません。"
        case .noExtractableText:
            return "文字情報が見つかりませんでした。スキャン画像だけの PDF は読み上げできません（OCR で文字を埋め込んだ PDF が必要です）。"
        case .brokenEPUB(let detail):
            return "EPUB を解析できませんでした（\(detail)）。"
        }
    }
}
