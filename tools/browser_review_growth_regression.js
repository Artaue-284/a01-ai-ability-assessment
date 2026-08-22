const { chromium } = require('playwright');

const baseURL = process.env.A01_BASE_URL || 'http://127.0.0.1:8000';
const username = process.env.A01_TEACHER_USER;
const password = process.env.A01_TEACHER_PASSWORD;
if (!username || !password) throw new Error('teacher credentials are required');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.locator('#navAuthBtn').click();
    await page.locator('#authUsername').fill('must-be-cleared');
    await page.locator('#authPassword').fill('must-be-cleared');
    await page.locator('[data-auth-role="enterprise"]').click();
    if (await page.locator('#authUsername').inputValue() || await page.locator('#authPassword').inputValue()) throw new Error('role switch did not clear credentials');
    await page.locator('[data-auth-role="teacher"]').click();
    await page.locator('#authUsername').fill(username);
    await page.locator('#authPassword').fill(password);
    await page.locator('#authLoginBtn').click();
    await page.locator('#adminWorkspace').waitFor({ state: 'visible', timeout: 15000 });
    await page.locator('[data-admin-view="reviews"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#adminReviews .review-card').length === 5);
    const firstPageCount = await page.locator('#adminReviews .review-card').count();
    const firstText = await page.locator('#adminReviews .toolbar').innerText();
    await page.getByRole('button', { name: '下一页' }).click();
    await page.waitForFunction(() => document.querySelector('#adminReviews .toolbar')?.textContent.includes('第 2/'));
    const secondPageCount = await page.locator('#adminReviews .review-card').count();
    await page.locator('[data-admin-view="growth"]').click();
    await page.locator('#growthStudent').waitFor({ state: 'visible' });
    await page.locator('#growthStudent').selectOption('DEMO-001');
    await page.waitForTimeout(500);
    const historyCount = await page.evaluate(async () => (await (await fetch('/api/users/DEMO-001/history')).json()).tests.length);
    const result = { role_switch_cleared: true, first_page_cards: firstPageCount, second_page_cards: secondPageCount, pagination_text: firstText, growth_history_points: historyCount, page_errors: errors };
    if (firstPageCount !== 5 || secondPageCount !== 5 || historyCount !== 50 || errors.length) throw new Error(JSON.stringify(result));
    process.stdout.write(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(error => { process.stderr.write(error.stack); process.exit(1); });
