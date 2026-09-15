import { chromium } from '/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core/index.mjs';
import { writeFileSync } from 'node:fs';
const out='/private/tmp/codex-data-standalone-review-20260914';
const browser=await chromium.launch({executablePath:'/Users/charlie/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell',headless:true});
const observations=[];
try {
for (const width of [1440,390,320]) {
 const page=await browser.newPage({viewport:{width,height:900}});const errors=[];const requests=[];
 page.on('pageerror',e=>errors.push(e.message));await page.route('https://**/*',r=>{requests.push(r.request().url());return r.abort();});
 await page.goto('file://'+out+'/demo-app/.data-app-offline/exports/demo.html');await page.locator('[data-component-id]').first().waitFor();await page.screenshot({path:out+'/demo-'+width+'.png',fullPage:false});
 observations.push({width,errors,externalRequests:requests,components:await page.locator('[data-component-id]').count(),overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
 await page.close();
}
writeFileSync(out+'/demo-browser.json',JSON.stringify({browser:browser.version(),observations},null,2));
}finally{await browser.close();}
