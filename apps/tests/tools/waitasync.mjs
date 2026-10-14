// Playwright の waitForFunction は async の条件を「すぐ満たした」と扱うため、読み込みを待ってから判定し直す
export const waitAsync = async (target, predicate, arg, timeout = 30000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await target.evaluate(predicate, arg)) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("waitAsync: 条件を満たすまで待てませんでした");
};
