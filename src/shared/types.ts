// 議会だより 共通データモデル（設計仕様書 §6）
// main / renderer 双方から参照する。レイアウト(見た目)とデータ(中身)を分離する方針。

/** プロジェクトファイル形式のバージョン。互換性チェックに使う。 */
export const PROJECT_SCHEMA_VERSION = 1 as const;

/** 紙面サイズ */
export type PageSize = 'A4' | 'B5' | 'B4' | 'A3';

/** 書字方向（R-2: 縦書き必須） */
export type WritingMode = 'vertical' | 'horizontal';

/** 取り込み元の種別（来歴。F-IMP-10） */
export type ArticleSource =
  | 'handwritten' // 手書き原稿（スキャンを見ながら書き起こし）
  | 'word'
  | 'excel'
  | 'pdf'
  | 'text'
  | 'manual'; // アプリ内で直接作成

/** 議員（§6.1） */
export interface CouncilMember {
  id: string;
  name: string;
  nameKana: string;
  faction: string; // 会派
  seatNumber: number | null; // 議席番号
  portraitImageId: string | null; // ImageAsset.id への参照（顔写真）
  order: number; // 掲載順（手動並べ替え時の確定値）
}

/** 記事内に置かれる画像の参照とキャプション */
export interface ArticleImageRef {
  imageId: string; // ImageAsset.id
  caption: string;
}

/** 記事（§6.2） */
export interface Article {
  id: string;
  memberId: string | null; // 紐づく議員（会派記事・事務局記事は null）
  sectionId: string; // 配置するコーナー/枠の種類
  title: string;
  subtitle: string;
  /** 本文。P1 では段落配列の簡易構造。後フェーズでリッチテキスト化。 */
  body: string[];
  images: ArticleImageRef[];
  source: ArticleSource;
  sourceFile: string | null; // 取り込み元ファイル名
  sourceScanImageId: string | null; // 手書き時の参照スキャン画像
  charCount: number; // 文字数（自動計算）
}

/** 画像の非破壊編集パラメータ（§6.3 / F-IMG-5） */
export interface ImageEdits {
  crop: { x: number; y: number; width: number; height: number } | null;
  rotate: number; // 度
  flipH: boolean;
  flipV: boolean;
  brightness: number; // 0 を基準とした調整値
  contrast: number;
  saturation: number;
}

/** 画像素材（§6.3） */
export interface ImageAsset {
  id: string;
  /** プロジェクトフォルダ内の相対パス（assets/...） */
  relativePath: string;
  edits: ImageEdits;
  caption: string;
  dpiWarning: boolean; // 印刷解像度不足フラグ
}

/** 枠定義 */
export interface FrameDef {
  id: string;
  /** 用途（記事/写真/見出し 等） */
  role: 'article' | 'image' | 'heading' | 'free';
  /** ページ内の位置・サイズ（mm） */
  x: number;
  y: number;
  width: number;
  height: number;
}

/** テンプレート（§6.4・見た目） */
export interface Template {
  id: string;
  name: string;
  pageSize: PageSize;
  writingMode: WritingMode;
  margins: { top: number; right: number; bottom: number; left: number };
  columns: number; // 段組数
  fonts: { heading: string; body: string; headingSizePt: number; bodySizePt: number };
  frames: FrameDef[];
}

/** 1ページ分の枠割り当て */
export interface FrameAssignment {
  frameId: string;
  /** 割り当て対象。記事 or 画像。 */
  articleId?: string;
  imageId?: string;
}

export interface LayoutPage {
  id: string;
  frameAssignments: FrameAssignment[];
}

/** レイアウト（§6.4） */
export interface Layout {
  pages: LayoutPage[];
}

/** プロジェクトのメタ情報 */
export interface ProjectMeta {
  /** 号数（例: 128） */
  issueNumber: number | null;
  /** 発行日（ISO日付文字列 or 空） */
  publishDate: string;
  /** 自治体名 */
  municipality: string;
  /** 紙面サイズ（既定テンプレートと一致させる初期値） */
  pageSize: PageSize;
}

/** プロジェクト全体（1号分。§6） */
export interface Project {
  schemaVersion: typeof PROJECT_SCHEMA_VERSION;
  /** 一意ID（複製時の追跡用） */
  id: string;
  meta: ProjectMeta;
  councilMembers: CouncilMember[];
  articles: Article[];
  images: ImageAsset[];
  layout: Layout;
  templates: Template[];
  /** 使用中テンプレートの id */
  activeTemplateId: string | null;
  /** 作成・更新時刻（ISO文字列。呼び出し側で付与） */
  createdAt: string;
  updatedAt: string;
}
