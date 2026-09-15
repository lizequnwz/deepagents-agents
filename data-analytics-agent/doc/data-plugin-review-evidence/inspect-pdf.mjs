import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const canvas=require('/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@napi-rs/canvas');
for(const key of ['DOMMatrix','ImageData','Path2D'])globalThis[key]=canvas[key];
const {getDocument}=await import('/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pdfjs-dist/legacy/build/pdf.mjs');
const here=path.dirname(fileURLToPath(import.meta.url));
const pdf=await getDocument({data:new Uint8Array(fs.readFileSync(path.join(here,'report-print-check.pdf'))),useSystemFonts:true}).promise;
const pages=[];
const thumbW=210,thumbH=320,cols=5;
const sheet=canvas.createCanvas(thumbW*cols,thumbH*Math.ceil(pdf.numPages/cols));
const ctx=sheet.getContext('2d');ctx.fillStyle='#cdd4d5';ctx.fillRect(0,0,sheet.width,sheet.height);
for(let i=1;i<=pdf.numPages;i++){
  const page=await pdf.getPage(i);const viewport=page.getViewport({scale:1});
  const text=(await page.getTextContent()).items.filter(e=>e.str?.trim());
  const str=text.map(e=>e.str).join(' ');
  const outside=text.filter(e=>e.transform[4]<-1||e.transform[5]<-1||e.transform[4]+e.width>viewport.width+1||e.transform[5]>viewport.height+1).map(e=>e.str);
  pages.push({page:i,characters:str.length,firstText:str.slice(0,110),outside});
  const scale=.32;const v=page.getViewport({scale});const c=canvas.createCanvas(Math.ceil(v.width),Math.ceil(v.height));
  await page.render({canvasContext:c.getContext('2d'),viewport:v}).promise;
  const x=((i-1)%cols)*thumbW+10,y=Math.floor((i-1)/cols)*thumbH+10;
  ctx.drawImage(c,x,y);ctx.font='13px sans-serif';ctx.fillStyle='#172b3a';ctx.fillText(String(i),x,y+v.height+18);
  if(i===1||str.includes('Architecture & trust boundaries')||str.includes('Prioritized recommendations')){
    const full=page.getViewport({scale:1.3});const out=canvas.createCanvas(Math.ceil(full.width),Math.ceil(full.height));
    await page.render({canvasContext:out.getContext('2d'),viewport:full}).promise;
    fs.writeFileSync(path.join(here,`print-page-${i}.png`),out.toBuffer('image/png'));
  }
}
fs.writeFileSync(path.join(here,'print-contact-sheet.png'),sheet.toBuffer('image/png'));
const result={pages:pdf.numPages,geometry:pages,allTextWithinPages:pages.every(p=>p.outside.length===0)};
fs.writeFileSync(path.join(here,'print-validation.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
