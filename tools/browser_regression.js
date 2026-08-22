const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const baseURL = process.env.A01_BASE_URL || 'http://127.0.0.1:8000';
const username = process.env.A01_TEACHER_USER;
const password = process.env.A01_TEACHER_PASSWORD;
if (!username || !password) throw new Error('A01_TEACHER_USER/A01_TEACHER_PASSWORD are required');

const outDir = path.resolve('docs', 'regression');
fs.mkdirSync(outDir, { recursive: true });

async function login(page) {
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.locator('#navAuthBtn').click();
  await page.locator('#authUsername').fill(username);
  await page.locator('#authPassword').fill(password);
  await page.locator('#authLoginBtn').click();
  await page.locator('#adminWorkspace').waitFor({ state: 'visible', timeout: 15000 });
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' });
  const report = { baseURL, desktop: {}, mobile: {}, generated_question_id: '', errors: [] };
  try {
    const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
    const page = await desktop.newPage();
    page.on('pageerror', error => report.errors.push(`desktop pageerror: ${error.message}`));
    await login(page);
    await page.locator('[data-admin-view="questions"]').click();
    await page.locator('#qId').waitFor({ state: 'visible' });
    await page.locator('#draftQuestion').click();
    await page.waitForFunction(() => document.querySelector('#qId')?.value.length > 3, null, { timeout: 120000 });
    const questionId = await page.locator('#qId').inputValue();
    report.generated_question_id = questionId;
    await page.locator('#qExplanation').fill((await page.locator('#qExplanation').inputValue()) + '（教师浏览器回归确认）');
    await page.locator('#saveQuestion').click();
    await page.waitForFunction(() => document.querySelector('#toast')?.textContent.includes('题目已保存'), null, { timeout: 20000 });
    const versionInfo = await page.evaluate(async id => {
      const token = sessionStorage.getItem('a01AuthToken');
      const response = await fetch(`/api/admin/questions/${id}/versions`, { headers: { Authorization: `Bearer ${token}` } });
      return response.json();
    }, questionId);
    if (!versionInfo.versions || versionInfo.versions.length < 1) throw new Error('version tracking missing');
    report.desktop = { login: true, draft: true, edit: true, save: true, version_count: versionInfo.versions.length };
    await page.screenshot({ path: path.join(outDir, 'teacher-desktop.png'), fullPage: true });
    await desktop.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: 'zh-CN' });
    const mobilePage = await mobile.newPage();
    mobilePage.on('pageerror', error => report.errors.push(`mobile pageerror: ${error.message}`));
    await login(mobilePage);
    await mobilePage.locator('[data-admin-view="questions"]').click();
    await mobilePage.locator('#qId').waitFor({ state: 'visible' });
    const layout = await mobilePage.evaluate(() => ({ viewport: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, qIdVisible: !!document.querySelector('#qId')?.offsetParent }));
    report.mobile = { login: true, teacher_workspace: true, question_manager: true, ...layout };
    await mobilePage.screenshot({ path: path.join(outDir, 'teacher-mobile.png'), fullPage: true });
    await mobile.close();
    fs.writeFileSync(path.join(outDir, 'browser-regression.json'), JSON.stringify(report, null, 2), 'utf8');
    process.stdout.write(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { process.stderr.write(error.stack); process.exit(1); });
