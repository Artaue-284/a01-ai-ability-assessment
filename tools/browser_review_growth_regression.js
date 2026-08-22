const { chromium } = require('playwright-core');

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
    const homeText = await page.locator('body').innerText();
    const removedPhrases = ['队内预测试推荐25题', '题库已就绪', '系统就绪'].filter(text => homeText.includes(text));
    if (removedPhrases.length) throw new Error(`internal copy remains: ${removedPhrases.join(',')}`);
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
    await page.waitForTimeout(800);
    await page.locator('[data-admin-view="reviews"]').click();
    await page.locator('#adminReviews').waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelectorAll('#adminReviews .review-card').length === 5);
    const firstPageCount = await page.locator('#adminReviews .review-card').count();
    const firstText = await page.locator('#adminReviews .toolbar').innerText();
    const reviewTotal = await page.evaluate(() => reviewTotal);
    await page.locator('#reviewPageInput').fill('2');
    await page.locator('#adminReviews').getByRole('button', { name: '跳转' }).click();
    await page.waitForFunction(() => document.querySelector('#adminReviews .toolbar')?.textContent.includes('第 2/'));
    const secondPageCount = await page.locator('#adminReviews .review-card').count();
    await page.locator('[data-admin-view="questions"]').click();
    await page.locator('#questionRows').waitFor({ state: 'visible' });
    const firstQuestionPageCount = await page.locator('#questionRows tr').count();
    await page.locator('#questionPageInput').fill('3');
    await page.locator('#questionPager').getByRole('button', { name: '跳转' }).click();
    await page.waitForFunction(() => document.querySelector('#questionPager')?.textContent.includes('第 3/'));
    const thirdQuestionPageCount = await page.locator('#questionRows tr').count();
    await page.locator('[data-admin-view="growth"]').click();
    await page.locator('#growthStudent').waitFor({ state: 'visible' });
    const defaultGrowthSeries = await page.locator('.growth-series-btn.active').getAttribute('data-series');
    await page.locator('#growthStudent').selectOption('DEMO-001');
    await page.waitForTimeout(500);
    await page.locator('.growth-series-btn[data-series="prompt"]').click();
    const selectedGrowthSeries = await page.locator('.growth-series-btn.active').getAttribute('data-series');
    const historyCount = await page.evaluate(async () => (await (await fetch('/api/users/DEMO-001/history')).json()).tests.length);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-admin-view="questions"]').click();
    await page.locator('#questionPager').waitFor({ state: 'visible' });
    const mobileNoPageOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    const mobilePagerVisible = await page.locator('#questionPageInput').isVisible();
    const result = { removed_phrases: removedPhrases, role_switch_cleared: true, review_total: reviewTotal, first_page_cards: firstPageCount, second_page_cards: secondPageCount, pagination_text: firstText, question_page_1_rows: firstQuestionPageCount, question_page_3_rows: thirdQuestionPageCount, default_growth_series: defaultGrowthSeries, selected_growth_series: selectedGrowthSeries, growth_history_points: historyCount, mobile_no_page_overflow: mobileNoPageOverflow, mobile_pager_visible: mobilePagerVisible, page_errors: errors };
    if (reviewTotal >= 100 || firstPageCount !== 5 || secondPageCount !== 5 || firstQuestionPageCount !== 10 || thirdQuestionPageCount !== 10 || defaultGrowthSeries !== 'overall' || selectedGrowthSeries !== 'prompt' || historyCount !== 50 || !mobileNoPageOverflow || !mobilePagerVisible || errors.length) throw new Error(JSON.stringify(result));
    process.stdout.write(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(error => { process.stderr.write(error.stack); process.exit(1); });
