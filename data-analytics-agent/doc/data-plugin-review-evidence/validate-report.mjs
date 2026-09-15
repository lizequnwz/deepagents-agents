import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { chromium } from '/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core/index.mjs';
import { marked } from '/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/marked/lib/marked.esm.js';

const here=path.dirname(fileURLToPath(import.meta.url));
const doc=path.dirname(here);
const html=path.join(doc,'data-plugin-standalone-review-2026-09-14.html');
const md=fs.readFileSync(path.join(doc,'data-plugin-standalone-review-2026-09-14.md'),'utf8');
const browser=await chromium.launch({executablePath:'/Users/charlie/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell',headless:true});
const receipt={browser:browser.version(),offline:true,viewports:[],assertions:{},limits:['Chromium only; no screen-reader or Safari session.','Contrast checked for defined principal text tokens; not a full WCAG audit.','Print checked through Chromium PDF generation and page text/geometry; no physical printer.']};
const requireTrue=(name,condition)=>{receipt.assertions[name]=Boolean(condition);if(!condition)throw new Error(name);};
try {
  const context=await browser.newContext({offline:true,reducedMotion:'reduce'});
  const page=await context.newPage();
  const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  await page.goto(pathToFileURL(html).href);
  for(const [width,height] of [[1440,1000],[768,1024],[390,844],[375,812],[320,740],[844,390]]) {
    await page.setViewportSize({width,height});
    await page.locator('#expand').click();
    const metrics=await page.evaluate(()=>({pageOverflow:document.documentElement.scrollWidth>innerWidth,clipped:[...document.querySelectorAll('main p,main td,main summary,.diagram-node')].filter(e=>e.scrollWidth>e.clientWidth+2).map(e=>e.textContent.slice(0,90)),sections:document.querySelectorAll('main section.chapter').length,diagrams:document.querySelectorAll('figure.diagram').length}));
    receipt.viewports.push({width,height,...metrics});
    requireTrue(`no overflow at ${width}x${height}`,!metrics.pageOverflow&&metrics.clipped.length===0);
    await page.locator('#collapse').click();
    await page.evaluate(()=>{document.getElementById('status').textContent='';window.scrollTo(0,0);});
    if([1440,390,320].includes(width)) await page.screenshot({path:path.join(here,`report-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#expand').click();
  const expected=marked.parse(md).replace(/<pre><code class="language-mermaid">[\s\S]*?<\/code><\/pre>/g,'');
  const parity=await page.evaluate(expected=>{
    const normalize=s=>s.replace(/\s+/g,' ').trim();
    const parsed=new DOMParser().parseFromString(expected,'text/html');
    const actual=normalize(document.querySelector('main').textContent);
    // Source path paragraphs gain a copy button; compare their unmodified substantive text separately.
    const blocks=[...parsed.querySelectorAll('p,td,li')].filter(e=>!e.querySelector('p'));
    return {blocks:blocks.length,missing:blocks.map(e=>normalize(e.textContent)).filter(text=>!actual.includes(text)&&!text.startsWith('Observed — Source.'))};
  },expected);
  receipt.contentParity=parity;
  requireTrue('all Markdown prose and table/list blocks preserved',parity.missing.length===0);
  const anchors=await page.evaluate(()=>[...document.querySelectorAll('a[href^="#"]')].filter(a=>!document.getElementById(a.hash.slice(1))).map(a=>a.hash));
  requireTrue('all internal anchors resolve',anchors.length===0);
  requireTrue('14 chapters and 3 diagrams',await page.locator('main section.chapter').count()===14&&await page.locator('figure.diagram').count()===3);
  await page.locator('#collapse').click();
  requireTrue('collapse closes all content disclosures',await page.locator('main details[open]').count()===0);
  await page.locator('a.citation[href="#ref-s05"]').first().click();
  await page.waitForFunction(()=>document.getElementById('ref-s05').open);
  requireTrue('citation opens its source disclosure',await page.locator('#ref-s05').getAttribute('open')!==null);
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedForTest=text;}}}));
  await page.locator('#ref-s05 .copy-reference').first().click();
  requireTrue('copy produces exact source path and range',await page.evaluate(()=>window.copiedForTest==='/Users/charlie/.codex/plugins/cache/openai-curated-remote/data-analytics/1.0.8/shared/data-app.md:21-98'));
  await page.locator('#ref-t01').evaluate(el=>el.open=true);
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#ref-t01 a[download]').click()]);
  requireTrue('embedded test receipt downloads offline',download.suggestedFilename()==='unit-tests.log'&&await download.failure()===null);
  await page.locator('#expand').click();
  await page.locator('#fig-01-title').scrollIntoViewIfNeeded();
  await page.evaluate(()=>document.getElementById('status').textContent='');
  await page.locator('figure.diagram').first().screenshot({path:path.join(here,'report-architecture.png')});
  await page.locator('#collapse').click();
  const before=await page.locator('main details[open]').count();
  await page.evaluate(()=>window.dispatchEvent(new Event('beforeprint')));
  requireTrue('print expands all details',await page.locator('main details[open]').count()===await page.locator('main details').count());
  await page.emulateMedia({media:'print'});
  const printGeometry=await page.evaluate(()=>({width:document.documentElement.scrollWidth,diagrams:[...document.querySelectorAll('figure.diagram')].map(e=>({title:e.querySelector('strong').textContent,height:e.getBoundingClientRect().height})),hiddenParagraphs:[...document.querySelectorAll('main p')].filter(e=>e.getClientRects().length===0).map(e=>e.textContent.slice(0,80))}));
  receipt.printGeometry=printGeometry;
  requireTrue('no hidden review paragraphs in print',printGeometry.hiddenParagraphs.length===0);
  await page.pdf({path:path.join(here,'report-print-check.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true,displayHeaderFooter:true,headerTemplate:'<div></div>',footerTemplate:'<div style="font:8px sans-serif;width:100%;padding:0 56px;color:#52626d;display:flex;justify-content:space-between"><span>Codex Data 1.0.8 · Technical and product review</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'});
  await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));
  requireTrue('print restores prior disclosure state',await page.locator('main details[open]').count()===before);
  await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390,height:844});
  await page.locator('#expand').click();
  await page.evaluate(()=>document.body.style.fontSize='32px');
  requireTrue('no page overflow with body text doubled to 32px',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  requireTrue('no uncaught browser errors',errors.length===0);
  requireTrue('no external network requests',external.length===0);
  receipt.errors=errors;receipt.externalRequests=external;
  const sources=JSON.parse(fs.readFileSync(path.join(here,'sources.json'),'utf8'));
  let passages=0;
  for(const [id,entries] of Object.entries(sources))for(const entry of entries){const bytes=fs.readFileSync(entry.path);const lines=bytes.toString().split('\n');requireTrue(`${id} ${++passages}: path, range and hash`,entry.start>=1&&entry.end<=lines.length&&createHash('sha256').update(bytes).digest('hex')===entry.sha256);}
  receipt.sourcePassages=passages;
  const allSourcePaths=await page.locator('.source-path').allTextContents();
  requireTrue('all cited source passages preserved in HTML',allSourcePaths.length===passages&&Object.values(sources).flat().every(e=>allSourcePaths.includes(e.path)));
  const ratios={};
  const luminance=hex=>{const a=hex.match(/\w\w/g).map(s=>parseInt(s,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return a[0]*.2126+a[1]*.7152+a[2]*.0722;};
  for(const [name,fg,bg] of [['body','172b3a','f6f7f6'],['muted','52626d','ffffff'],['observed','006b62','ffffff'],['inference','425277','ffffff'],['recommendation','85500b','ffffff'],['citation','006b62','eaf4f1']]){const l1=luminance(fg),l2=luminance(bg);ratios[name]=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);requireTrue(`${name} contrast >= 4.5`,ratios[name]>=4.5);}
  receipt.contrastRatios=ratios;
  receipt.markdownSha256=createHash('sha256').update(md).digest('hex');
  receipt.validatedHtmlSha256=createHash('sha256').update(fs.readFileSync(html)).digest('hex');
} finally {
  fs.writeFileSync(path.join(here,'report-validation.json'),JSON.stringify(receipt,null,2)+'\n');
  await browser.close();
}
console.log(JSON.stringify({assertions:Object.keys(receipt.assertions).length,viewports:receipt.viewports,parity:receipt.contentParity},null,2));
