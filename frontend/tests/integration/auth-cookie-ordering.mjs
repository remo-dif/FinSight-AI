import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "playwright";
const origin = process.env.COOKIE_TEST_ORIGIN;
const scenario = process.argv[2];
const headers = { 'Content-Type': 'application/json', 'X-FinSight-Cookie-Session': 'true' };
(async () => {
  const browser = await ({ chromium, firefox, webkit }[process.env.COOKIE_TEST_BROWSER || "chromium"]).launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(8000);
    const accounts = ['a', 'b'].map(name => ({ email: `cookie-${name}@example.com`, password: 'synthetic-cookie-test-password', full_name: `Cookie ${name}` }));
    for (const account of accounts) {
      assert.equal((await context.request.post(origin + '/api/auth/register', { data: account })).status(), 202);
    }
    await page.goto(origin + '/__cookie-test');
    await page.evaluate(() => window.boot);
    async function post(target, pathname, data = {}) {
      return target.evaluate(async ({ pathname, data, headers }) => {
        const response = await fetch(pathname, { method: 'POST', headers, body: JSON.stringify(data) });
        return { status: response.status, data: response.status === 204 ? null : await response.json() };
      }, { pathname, data, headers });
    }
    const loginA = await post(page, '/api/auth/login', accounts[0]);
    assert.equal(loginA.status, 200);
    assert.ok(loginA.data.refresh_token === '', 'Cookie-mode login must not disclose a refresh token');
    if (scenario === 'rotation') {
      const first = await post(page, '/api/auth/refresh');
      assert.equal(first.status, 200);
      const second = await post(page, '/api/auth/refresh');
      assert.equal(second.status, 200);
      await page.reload(); await page.evaluate(() => window.boot);
      assert.equal(await page.locator('#identity').textContent(), accounts[0].email);
      return;
    }
    if (scenario === 'stale-failure') {
      // Revoked A returns actual 401; headers are delayed until B's login succeeds.
      assert.equal((await post(page, '/api/auth/logout')).status, 204);
    }
    await page.evaluate(({ headers, scenario }) => {
      window.delayed = fetch((scenario === 'stale-logout' ? '/api/auth/logout' : '/api/auth/refresh') + '?hold=1', { method: 'POST', headers, body: '{}' })
        .then(async r => ({ status: r.status, data: r.status === 204 ? null : await r.json() }));
    }, { headers, scenario });
    const deadline = Date.now() + 8000;
    while (!(await (await context.request.get(origin + '/__held')).json()).ready) {
      if (Date.now() > deadline) throw new Error('Backend response was not held');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    let current = page;
    if (scenario === 'cross-tab') {
      current = await context.newPage();
      // No bootstrap here: A is intentionally still being rotated in the other tab.
      await current.goto(origin + '/docs');
    }
    if (scenario === 'logout') {
      assert.equal((await post(page, '/api/auth/logout')).status, 204);
    } else if (scenario === 'concurrent-replay') {
      assert.equal((await post(page, '/api/auth/refresh')).status, 401);
    } else {
      assert.equal((await post(current, '/api/auth/login', accounts[1])).status, 200);
    }
    if (scenario === 'cross-tab') {
      const mismatch = await page.evaluate(async ({ headers, token }) => (await fetch('/api/auth/refresh', { method: 'POST', headers: { ...headers, Authorization: 'Bearer ' + token }, body: '{}' })).status, { headers, token: loginA.data.access_token });
      // The stale tab must not adopt B or retry an A action as B.
      assert.equal(mismatch, 401);
    }
    await context.request.post(origin + '/__release');
    const delayed = await page.evaluate(() => window.delayed);
    assert.equal(delayed.status, scenario === 'stale-failure' ? 401 : scenario === 'stale-logout' ? 204 : 200);
    if (delayed.status === 200) assert.equal(delayed.data.refresh_token, '');
    if (['logout', 'concurrent-replay'].includes(scenario)) {
      const denied = await context.request.get(origin + '/api/auth/me', { headers: { Authorization: 'Bearer ' + delayed.data.access_token } });
      assert.equal(denied.status(), 401, 'Late access cookies must not authorize a revoked family');
    }
    await current.goto(origin + '/__cookie-test');
    await current.evaluate(() => window.boot);
    const actual = await current.locator('#identity').textContent();
    const expected = ['logout', 'concurrent-replay'].includes(scenario) ? 'anonymous' : accounts[1].email;
    console.log(JSON.stringify({ scenario, restored: actual === accounts[0].email ? 'A' : actual === accounts[1].email ? 'B' : actual }));
    assert.equal(actual, expected, 'An older response must not restore account A');
    await current.goto(origin.replace('127.0.0.1', 'localhost') + '/__cookie-test');
    await current.evaluate(() => window.boot);
    await current.evaluate(origin => fetch(origin + '/api/auth/__cookie-echo', {method:'POST', mode:'no-cors', credentials:'include'}).then(() => true), origin);
    const observed = await (await context.request.get(origin + '/__cookie-observed')).json();
    assert.equal(observed.cookie_sent, false, 'SameSite=Lax credentials must not be sent on cross-site POST');
    const cookies = await context.cookies();
    console.log(JSON.stringify({ cookieAttributes: cookies.filter(c => c.name.startsWith('finsight_')).map(({name, httpOnly, sameSite, path, secure}) => ({name, httpOnly, sameSite, path, secure})) }));
    assert.ok(cookies.filter(c => c.name.startsWith('finsight_')).every(c => c.httpOnly && c.sameSite === 'Lax'));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
