// PoC: 縦書きプレビューHTMLを Chromium で描画し、(1) スクリーンショット (2) PDF を出力する。
// → Electron でも同じ Chromium 描画なので、紙面プレビューとPDF出力の見た目一致を裏付ける。
import { chromium } from 'playwright';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { mkdirSync } from 'node:fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, '..', 'out');
mkdirSync(outDir, { recursive: true });

const targets = [
  { html: '03-workbench.html', png: 'workbench.png', pdf: null,
    viewport: { width: 980, height: 560 } },
  { html: '03-vertical-preview.html', png: 'vertical-preview.png', pdf: 'vertical-preview.pdf',
    viewport: { width: 900, height: 1280 } },
];

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM || undefined,
});
try {
  for (const t of targets) {
    const page = await browser.newPage({ viewport: t.viewport, deviceScaleFactor: 2 });
    const url = pathToFileURL(path.join(__dirname, t.html)).href;
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(outDir, t.png), fullPage: true });
    console.log('スクショ:', path.join('out', t.png));
    if (t.pdf) {
      await page.pdf({
        path: path.join(outDir, t.pdf),
        format: 'A4', printBackground: true,
        margin: { top: '0', right: '0', bottom: '0', left: '0' },
      });
      console.log('PDF   :', path.join('out', t.pdf));
    }
    await page.close();
  }
} finally {
  await browser.close();
}
