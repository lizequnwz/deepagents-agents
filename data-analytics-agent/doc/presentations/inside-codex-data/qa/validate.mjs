import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {chromium} from '/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core/index.mjs';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.dirname(here);
const html=path.join(root,'index.html');
const reviews=path.resolve(root,'../../reviews');
const receipt={checks:[],viewports:[],errors:[],externalRequests:[],limits:['Chromium only; no Safari, iOS, or screen-reader session.','Teaching clarity reviewed against the 16 audience questions; no audience study or timed presentation was conducted.','Copy payload tested using a clipboard stub; manual-copy fallback tested separately.','Simulations validate this educational artifact, not the Data plugin or a live source/host.']};
const check=(name,ok)=>{receipt.checks.push({name,passed:!!ok});if(!ok)throw new Error(name);};
const browser=await chromium.launch({executablePath:'/Users/charlie/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell',headless:true});
try{
 const context=await browser.newContext({offline:true,reducedMotion:'reduce'});receipt.browser=browser.version();
 const page=await context.newPage();page.on('pageerror',e=>receipt.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')receipt.errors.push(m.text());});page.on('request',r=>{if(/^https?:/.test(r.url()))receipt.externalRequests.push(r.url());});
 await page.goto(pathToFileURL(html).href);await page.locator('#skill-detail h3').waitFor();
 check('14 teaching scenes',await page.locator('.scene').count()===14);
 for(const [width,height] of [[2560,1440],[1440,900],[1280,800],[1024,768],[768,1024],[390,844],[375,812],[320,740],[844,390]]){
  await page.setViewportSize({width,height});
  const layout=await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,clipped:[...document.querySelectorAll('.scene h1,.scene h2,.scene h3,.scene p,.scene pre,.scene button,.topbar')].filter(e=>e.getClientRects().length&&e.scrollWidth>e.clientWidth+2).map(e=>({tag:e.tagName,text:e.textContent.slice(0,75),scroll:e.scrollWidth,client:e.clientWidth})),outliers:[...document.querySelectorAll('.scene button,.topbar button,.scene select,.topbar select')].filter(e=>e.getClientRects().length&&(e.getBoundingClientRect().right>innerWidth+1||e.getBoundingClientRect().left<0)).map(e=>e.textContent.slice(0,75))}));
  receipt.viewports.push({width,height,...layout});check(`viewport containment ${width}x${height}`,layout.width===layout.documentWidth&&!layout.clipped.length&&!layout.outliers.length);
  if([2560,1440,390,320].includes(width)){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(here,`hero-${width}.png`)});}
 }
 await page.setViewportSize({width:1440,height:900});
 await page.locator('#model-intro [data-model="2"]').click();check('mental model expands evidence',await page.locator('#model-intro .model-detail').isVisible()&&await page.locator('#model-intro .model-detail').innerText().then(t=>t.includes('metadata alone')));
 await page.locator('#expand-architecture').click();check('expanded architecture includes branch caveat',await page.locator('#expanded-architecture').isVisible()&&await page.locator('#expanded-architecture').innerText().then(t=>t.includes('Notebook')));
 await page.locator('#mental-model').screenshot({path:path.join(here,'mental-model.png')});
 for(let i=0;i<9;i++){await page.locator(`[data-step="${i}"]`).click();check(`walkthrough step ${i+1}`,await page.locator('#step-count').innerText()===`${i+1} / 9`&&await page.locator('.walk-node.active').count()===1);}
 check('walkthrough endpoints disabled',await page.locator('#step-next').isDisabled());
 await page.locator('[data-step="5"]').click();await page.locator('#request').screenshot({path:path.join(here,'request.png')});
 const inventory=await page.evaluate(()=>JSON.parse(document.getElementById('lesson-data').textContent).skills.map(s=>({name:s.name,family:s.family})));
 for(const family of [...new Set(inventory.map(s=>s.family))]){
  await page.locator(`[data-family="${family}"]`).click();
  for(const s of inventory.filter(s=>s.family===family)){await page.locator(`[data-skill="${s.name}"]`).click();check(`skill explorer ${s.name}`,await page.locator('#skill-detail h3').innerText()===s.name&&await page.locator('#skill-detail dt').count()===4&&await page.locator('#skill-detail .skill-rules li').count()===2);}
 }
 await page.locator('[data-family="Analyze"]').click();await page.locator('#skills').screenshot({path:path.join(here,'skills.png')});
 for(let i=0;i<5;i++){await page.locator('#distinction-select').selectOption(String(i));check(`semantic distinction ${i+1}`,await page.locator('#distinction-content strong').count()===2);}
 for(let i=0;i<3;i++){await page.locator(`[data-trace="${i}"]`).click();check(`evidence trace ${i+1}`,await page.locator(`[data-trace="${i}"]`).getAttribute('aria-pressed')==='true');}
 for(let i=0;i<6;i++){await page.locator(`[data-evidence="${i}"]`).click();check(`evidence field ${i+1}`,await page.locator('#evidence-detail p').innerText().then(t=>t.length>50));}
 const idsBefore=await page.locator('.identity-graph').innerText();await page.locator('#identity-refresh').click();check('refresh keeps stable identities',idsBefore===await page.locator('.identity-graph').innerText()&&await page.locator('#identity-status').innerText().then(t=>t.includes('17.1%')));
 const evidenceBefore=await page.locator('#evidence-json').innerText();await page.locator('#rename-card').click();await page.locator('#move-card').click();await page.locator('#hide-card').click();check('presentation edits preserve evidence',evidenceBefore===await page.locator('#evidence-json').innerText()&&await page.locator('#preview-card').isHidden());await page.locator('#hide-card').click();await page.locator('#refresh-evidence').click();check('refresh exposes stale narrative example',await page.locator('#stale-warning').isVisible()&&await page.locator('#narrative-example').innerText().then(t=>t.includes('18.4%'))&&await page.locator('#preview-value').innerText()==='17.1%');await page.locator('#state').screenshot({path:path.join(here,'state.png')});await page.locator('#reset-card').click();check('reset restores simulation',evidenceBefore===await page.locator('#evidence-json').innerText());
 for(let i=0;i<8;i++){await page.locator(`[data-lifecycle="${i}"]`).click();check(`lifecycle stage ${i+1}`,await page.locator('#lifecycle-detail strong').innerText().then(t=>t.startsWith(String(i+1))));}
 for(const mode of ['local','offline','sites']){await page.locator(`[data-delivery="${mode}"]`).click();check(`delivery mode ${mode}`,await page.locator(`[data-delivery="${mode}"]`).getAttribute('aria-pressed')==='true');}
 await page.locator('#cap-source').uncheck();await page.locator('#cap-sites').uncheck();check('host dependency states remain honest',await page.locator('#capability-result').innerText().then(t=>t.includes('needs source access')&&t.includes('publication is unavailable')));
 for(let i=0;i<9;i++){await page.locator(`[data-pattern="${i}"]`).click();check(`borrowing pattern ${i+1}`,await page.locator('#pattern-detail dt').count()===3);}
 for(let i=0;i<6;i++){await page.locator('#tradeoff-select').selectOption(String(i));check(`trade-off ${i+1}`,await page.locator('.tradeoff-pair>div').count()===2);}
 await page.locator('#evidence .hood summary').click();await page.locator('#evidence .source-button').click();check('source drawer opens',await page.locator('#source-drawer').isVisible());
 check('exact source path and lines available',await page.locator('.exact-path').first().innerText().then(t=>t.includes('/data-analytics/1.0.8/')&&/:[0-9]+–[0-9]+/.test(t)));
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>window.copied=text}}));await page.locator('#source-content [data-copy]').first().click();check('copy exact source reference',await page.evaluate(()=>window.copied.endsWith('shared/data-app.md:21-98')));
 await page.locator('#source-content details').first().locator('summary').click();await page.locator('#source-drawer').screenshot({path:path.join(here,'source-drawer.png')});
  await page.keyboard.press('Escape');check('Escape closes drawer and restores focus',await page.locator('#source-drawer').isHidden()&&await page.locator('#evidence .source-button').evaluate(e=>e===document.activeElement));
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('Clipboard denied in test');}}}));
 await page.locator('#mental-model .live-demo summary').click();await page.locator('#mental-model .live-demo [data-copy]').click();
 check('manual-copy fallback opens a usable drawer',await page.locator('#source-drawer').isVisible()&&await page.locator('#copy-fallback').isVisible()&&await page.locator('#copy-fallback').evaluate(e=>e===document.activeElement&&e.selectionEnd===e.value.length&&e.value.includes('Data index skill')));
 for(let i=0;i<6;i++){await page.keyboard.press('Tab');check(`modal focus containment ${i+1}`,await page.evaluate(()=>document.activeElement.closest('#source-drawer')!==null));}
 await page.keyboard.press('Escape');
 await page.locator('#scene-select').selectOption('beginning');await page.locator('#presentation-toggle').click();check('presentation mode hides optional navigation',await page.locator('body').evaluate(e=>e.classList.contains('presenting'))&&await page.locator('#scene-select').isHidden());
 await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.getElementById('scene-position').textContent.startsWith('02'));check('arrow advances scene',await page.locator('#scene-position').innerText()==='02 / 14');
 await page.keyboard.press('Space');await page.waitForFunction(()=>document.getElementById('scene-position').textContent.startsWith('03'));check('space advances scene',await page.locator('#scene-position').innerText()==='03 / 14');
 await page.locator('[data-step="0"]').focus();await page.keyboard.press('Space');check('interactive controls keep Space behavior',await page.locator('#step-count').innerText()==='1 / 9'&&await page.locator('#scene-position').innerText()==='03 / 14');
 await page.keyboard.press('Escape');check('Escape exits presentation',await page.locator('body').evaluate(e=>!e.classList.contains('presenting')));
 await page.locator('#open-review').click();const frame=page.frameLocator('#review-frame');await frame.locator('h1').waitFor();check('full embedded research loads',await frame.locator('main section.chapter').count()===14);await frame.locator('#expand').click();check('embedded research retains interactions',await frame.locator('main details:not([open])').count()===0);
 const payload=await page.evaluate(()=>{const d=JSON.parse(document.getElementById('lesson-data').textContent);return {html:d.reviewHtml,markdown:d.reviewMarkdown};});
 check('original review HTML preserved byte-for-byte',Buffer.from(payload.html,'base64').equals(fs.readFileSync(path.join(reviews,'data-plugin-standalone-review-2026-09-14.html'))));check('original review Markdown preserved byte-for-byte',Buffer.from(payload.markdown,'base64').equals(fs.readFileSync(path.join(reviews,'data-plugin-standalone-review-2026-09-14.md'))));
 const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#download-markdown').click()]);check('offline original-review download',download.suggestedFilename()==='data-plugin-standalone-review-2026-09-14.md'&&await download.failure()===null);
 await page.locator('#open-review').click();await page.setViewportSize({width:390,height:844});await page.locator('#all-sources').click();check('source drawer fits phone',await page.locator('#source-drawer').evaluate(e=>e.getBoundingClientRect().right<=innerWidth&&e.scrollWidth<=e.clientWidth+1));await page.keyboard.press('Escape');
 await page.locator('[data-family="Deliver"]').click();await page.locator('[data-skill="schedule-refresh-jobs"]').click();await page.evaluate(()=>{document.getElementById('status').textContent='';document.activeElement.blur();});await page.locator('#skills').screenshot({path:path.join(here,'skills-phone.png')});
 await page.locator('#scene-select').selectOption('beginning');await page.locator('#presentation-toggle').click();check('phone presentation controls fit',await page.locator('.presentation-controls').evaluate(e=>e.scrollWidth<=e.clientWidth));await page.keyboard.press('Escape');
 await page.emulateMedia({media:'print'});await page.pdf({path:path.join(here,'learning-layer-print.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true});await page.emulateMedia({media:'screen'});
 await page.setViewportSize({width:1440,height:900});await page.emulateMedia({reducedMotion:'no-preference'});await page.reload();await page.locator('#presentation-toggle').click();await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.getElementById('scene-position').textContent.startsWith('02'));check('presentation advances without animation dependency',await page.locator('#scene-position').innerText()==='02 / 14');await page.keyboard.press('Escape');
 const luminance=h=>{const v=h.match(/\w\w/g).map(s=>parseInt(s,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return v[0]*.2126+v[1]*.7152+v[2]*.0722;};
 receipt.contrast={scope:'Principal explicit text/background tokens; not an exhaustive contrast audit.',ratios:{}};
 for(const [name,fg,bg] of [['dark body','f3f1ea','141820'],['dark muted','b5bdcc','141820'],['light muted','5d6470','f4f2ec'],['violet body','141820','e9e3f3'],['agent node','171b24','83b6ff'],['skills node','171b24','bca1ff'],['evidence node','171b24','f5c36b'],['artifact node','171b24','8cdbbd']]){const l1=luminance(fg),l2=luminance(bg),ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);receipt.contrast.ratios[name]=ratio;check(`${name} text contrast >= 4.5`,ratio>=4.5);}
 check('no external network requests',receipt.externalRequests.length===0);check('no runtime or CSP errors',receipt.errors.length===0);
 receipt.htmlSha256=createHash('sha256').update(fs.readFileSync(html)).digest('hex');receipt.summary={passed:receipt.checks.filter(c=>c.passed).length,total:receipt.checks.length};
}finally{fs.writeFileSync(path.join(here,'validation.json'),JSON.stringify(receipt,null,2)+'\n');await browser.close();}
console.log(JSON.stringify(receipt.summary));
