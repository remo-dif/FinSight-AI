import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "playwright";
const origin = process.env.COOKIE_TEST_ORIGIN;
const scenario = process.argv[2];
const headers = { 'Content-Type': 'application/json', 'X-FinSight-Cookie-Session': 'true' };
(async () => {
  const engine = process.env.COOKIE_TEST_BROWSER || "chromium";
  const browser = await ({ chromium, firefox, webkit }[engine]).launch(scenario === 'sibling' ? {
    ...(engine === 'chromium' ? { args: ['--host-resolver-rules=MAP *.finsight.test 127.0.0.1'] } : {}),
    ...(engine === 'firefox' ? { firefoxUserPrefs: { 'network.dns.localDomains': 'app.finsight.test, sibling.finsight.test' } } : {})
  } : {});
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: scenario === "sibling" });
    const page = await context.newPage();
    page.setDefaultTimeout(8000);
    const accounts = ['a', 'b'].map(name => ({ email: `cookie-${name}@example.com`, password: 'synthetic-cookie-test-password', full_name: `Cookie ${name}` }));
    await page.goto(origin + '/__cookie-test');
    await page.evaluate(() => window.boot);
    for (const account of accounts) {
      assert.equal(await page.evaluate(async ({ url, account, headers }) => (await fetch(url, { method: 'POST', headers, body: JSON.stringify(account) })).status, { url: '/api/auth/register', account, headers }), 202);
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
    if (scenario === 'browser-contract') {
      assert.ok(loginA.data.refresh_token === '', 'Cookie-mode login must not disclose a refresh token');
      assert.ok((await post(page, '/api/auth/refresh')).data.refresh_token === '');
      return;
    }
    if (scenario === 'sibling') {
      const attacker = (await context.cookies()).find(c => c.name === '__Host-finsight_session' || c.name === 'finsight_session');
      assert.ok(attacker);
      assert.equal((await post(page, '/api/auth/login', accounts[1])).status, 200);
      await page.goto(origin.replace('app.finsight.test', 'sibling.finsight.test') + '/__toss/' + attacker.value);
      await page.goto(origin + '/__cookie-test');
      await page.evaluate(() => window.boot);
      assert.equal(await page.locator('#identity').textContent(), accounts[1].email);
      const selectors = (await context.cookies()).filter(c => c.name === '__Host-finsight_session');
      assert.equal(selectors.length, 1);
      assert.equal(selectors[0].domain, 'app.finsight.test');
      return;
    }
    if (scenario === 'repeated-login') {
      for (let index = 0; index < 8; index++) {
        assert.equal((await post(page, '/api/auth/login', accounts[index % 2])).status, 200);
      }
      const cookies = (await context.cookies()).filter(c => c.name.startsWith('finsight_'));
      assert.equal(cookies.filter(c => /^finsight_(?:refresh|access)_[a-f0-9]{32}$/.test(c.name)).length, 2);
      const headerBytes = Buffer.byteLength(cookies.map(c => c.name + '=' + c.value).join('; '));
      assert.ok(headerBytes < 2048, 'Sequential login auth cookies must fit the test header budget');
      await page.reload(); await page.evaluate(() => window.boot);
      assert.equal(await page.locator('#identity').textContent(), accounts[1].email);
      return;
    }
    if (scenario === 'stale-tab-binding') {
      const current = await context.newPage();
      await current.goto(origin + '/docs');
      assert.equal((await post(current, '/api/auth/login', accounts[1])).status, 200);
      const statuses = await page.evaluate(async ({ headers, accessToken }) => {
        const authorization = { ...headers, Authorization: 'Bearer ' + accessToken };
        const me = await fetch('/api/auth/me', { headers: authorization });
        const refresh = await fetch('/api/auth/refresh', { method: 'POST', headers: authorization, body: '{}' });
        return [me.status, refresh.status];
      }, { headers, accessToken: loginA.data.access_token });
      assert.deepEqual(statuses, [401, 401]);
      await current.goto(origin + '/__cookie-test');
      await current.evaluate(() => window.boot);
      assert.equal(await current.locator('#identity').textContent(), accounts[1].email);
      return;
    }
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
      assert.equal((await post(page, '/__revoke')).status, 200);
    }
    await page.evaluate(({ headers, scenario, account }) => {
      window.delayed = fetch((scenario === 'competing-login' ? '/api/auth/login' : scenario === 'stale-logout' ? '/api/auth/logout' : '/api/auth/refresh') + '?hold=1', { method: 'POST', headers, body: JSON.stringify(scenario === 'competing-login' ? account : {}) })
        .then(async r => ({ status: r.status, data: r.status === 204 ? null : await r.json() }));
    }, { headers, scenario, account: accounts[0] });
    const held = await (await context.request.get(origin + '/__held')).json();
    assert.ok(held.ready, 'Backend response was not held');
    if (scenario === 'stale-failure') assert.equal(held.carried_refresh_cookie, true);
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
    await context.request.post(origin + '/__release');
    const delayed = await page.evaluate(() => window.delayed);
    assert.equal(delayed.status, scenario === 'stale-failure' ? 401 : scenario === 'stale-logout' ? 204 : 200);
    if (['logout', 'concurrent-replay'].includes(scenario)) {
      const denied = await context.request.get(origin + '/api/auth/me', { headers: { Authorization: 'Bearer ' + delayed.data.access_token } });
      assert.equal(denied.status(), 401, 'Late access cookies must not authorize a revoked family');
    }
    await current.goto(origin + '/__cookie-test');
    await current.evaluate(() => window.boot);
    const actual = await current.locator('#identity').textContent();
    const expected = ['logout', 'concurrent-replay'].includes(scenario) ? 'anonymous' : scenario === 'competing-login' ? accounts[0].email : accounts[1].email;
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
