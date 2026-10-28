const { chromium } = require('playwright');
(async () => {
  const [file, out, ...ts] = process.argv.slice(2);
  const b = await chromium.launch(); const pg = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  await pg.goto('file://' + file); await pg.waitForTimeout(500);
  for (const t of ts) {
    await pg.evaluate((t) => {
      document.querySelectorAll('.clip').forEach(c => { const s = +c.dataset.start, d = +c.dataset.duration;
        c.style.visibility = (t >= s && t < s + d) ? 'visible' : 'hidden'; });
      window.__timelines.main.seek(t);
    }, +t);
    await pg.screenshot({ path: `${out}_${t}.png` });
  }
  await b.close();
})();
