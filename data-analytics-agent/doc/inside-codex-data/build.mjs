import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import * as content from './src/content.mjs';
import {families,skills} from './src/skills.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
const doc=path.dirname(here);
const plugin='/Users/charlie/.codex/plugins/cache/openai-curated-remote/data-analytics/1.0.8';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const hash=b=>createHash('sha256').update(b).digest('hex');
const read=name=>fs.readFileSync(path.join(here,name),'utf8');
const sources=JSON.parse(fs.readFileSync(path.join(doc,'data-plugin-review-evidence/sources.json'),'utf8'));
function excerpt(entry){const bytes=fs.readFileSync(entry.path);if(entry.sha256&&hash(bytes)!==entry.sha256)throw new Error('Source changed: '+entry.path);const lines=bytes.toString().split('\n');const end=Math.min(entry.end,entry.start+17);return {...entry,sha256:hash(bytes),excerptEnd:end,excerpt:lines.slice(entry.start-1,end).map((l,i)=>`${entry.start+i}  ${l}`).join('\n')};}
for(const key of Object.keys(sources))sources[key]=sources[key].map(excerpt);
for(const skill of skills){const file=path.join(plugin,'skills',skill.name,'SKILL.md');const lines=fs.readFileSync(file,'utf8').split('\n');let start=lines.findIndex(l=>l.includes(' owns '));if(start<0)start=lines.findIndex(l=>l.startsWith('## Workflow'));if(start<0)start=24;sources['K:'+skill.name]=[excerpt({path:file,start:1,end:Math.min(8,lines.length)}),excerpt({path:file,start:start+1,end:Math.min(start+30,lines.length)})];}
const reviewHtml=fs.readFileSync(path.join(doc,'data-plugin-standalone-review-2026-09-14.html'));
const reviewMarkdown=fs.readFileSync(path.join(doc,'data-plugin-standalone-review-2026-09-14.md'));
const css=read('src/styles.css');const js=read('src/app.js');
const data={...content,scenes:undefined,sceneTitles:content.scenes.map(s=>s.nav),families,skills,sources,reviewHtml:reviewHtml.toString('base64'),reviewMarkdown:reviewMarkdown.toString('base64')};
const sceneHtml=content.scenes.map((s,i)=>`<section class="scene ${s.tone}" id="${s.id}" aria-labelledby="title-${s.id}"><div class="scene-inner"><header class="scene-header"><span class="kicker">${s.kicker}</span><${i===0?'h1':'h2'} id="title-${s.id}">${s.title}</${i===0?'h1':'h2'}><p class="intro">${s.intro}</p></header>${s.body}<details class="hood"><summary>Under the Hood <span aria-hidden="true">/</span> implementation + sources</summary><div class="hood-body"><span class="eyebrow">Architecture detail · interpretations identified in context</span><p>${s.hood}</p><button class="source-button" data-sources="${s.refs}" data-source-title="${esc(s.nav)} · source evidence">Explore source files + excerpts ↗</button></div></details></div></section>`).join('\n');
const html=`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; frame-src about: blob: data:; connect-src 'none'; base-uri 'none'; form-action 'none'"><title>Inside Codex Data — Agent → Skills → Evidence → Artifact</title><meta name="description" content="An interactive architecture lesson for AI engineers. Follow one request through skills, reviewed evidence, durable artifacts, runtime, and delivery."><style>${css}</style></head>
<body tabindex="-1"><a class="skip" href="#beginning">Skip to the lesson</a><header class="topbar"><a class="brand" href="#beginning"><strong>DATA</strong><span>FIELD GUIDE</span></a><label class="sr-only" for="scene-select" style="position:absolute;width:1px;height:1px;clip-path:inset(50%);overflow:hidden">Choose a scene</label><select id="scene-select">${content.scenes.map((s,i)=>`<option value="${s.id}">${String(i+1).padStart(2,'0')} · ${s.nav}</option>`).join('')}</select><button id="presentation-toggle" aria-pressed="false">Presentation mode</button><div class="read-progress" id="read-progress"></div></header>
<main>${sceneHtml}<section id="research" class="research" aria-labelledby="research-title"><div class="research-inner"><span class="eyebrow">Research appendix / optional depth</span><h2 id="research-title">Keep learning below the surface.</h2><p>The complete original review is embedded here, including architecture findings, source references, test receipts, limitations, and improvement proposals. Explore it without leaving this file.</p><div class="research-actions"><button id="open-review" aria-expanded="false" aria-controls="review-viewer">Open full technical review</button><button id="all-sources">Browse all source references</button><button id="download-review">Download original HTML</button><button id="download-markdown">Download original Markdown</button></div><small>Teaching layer → implementation detail → original evidence. The learning exercises are illustrative simulations, not a running Data app.</small><div class="review-viewer" id="review-viewer" hidden><iframe id="review-frame" title="Complete original technical review" sandbox="allow-scripts allow-downloads"></iframe></div><div class="footnote">Based on installed Codex Data 1.0.8 and the standalone review of 14 September 2026. Architectural interpretations and adoption lessons are separated from implementation facts in the deep dives. No live connector, Sites identity flow, or cloud refresh was executed for this lesson. The installed plugin and original review are unchanged.</div></div></section></main>
<div id="presentation-controls" class="presentation-controls" hidden><span id="scene-position">01 / 14</span><span id="present-scene-title"></span><button id="scene-prev">← Previous</button><button id="scene-next">Next →</button><button id="exit-present">Exit / Esc</button></div>
<dialog id="source-drawer" class="source-drawer" aria-labelledby="source-title"><header class="drawer-header"><h2 id="source-title">Source evidence</h2><button id="close-source">Close / Esc</button></header><p class="drawer-intro">Exact installed paths and cited line ranges. Excerpts are verbatim source snapshots. Teaching examples and architectural takeaways are interpretations; they are not execution traces or benchmark results.</p><div id="source-content" class="source-content"></div><textarea id="copy-fallback" aria-label="Text to copy manually" hidden></textarea></dialog><div id="status" class="status" role="status" aria-live="polite"></div>
<noscript><p style="padding:20px;background:#fff;color:#111">Enable JavaScript to explore the interactive lessons, sources, and embedded research. The main scene narrative remains available above.</p></noscript><script type="application/json" id="lesson-data">${JSON.stringify(data).replaceAll('<','\\u003c')}</script><script>${js}</script></body></html>`;
fs.writeFileSync(path.join(here,'index.html'),html);
fs.mkdirSync(path.join(here,'qa'),{recursive:true});
fs.writeFileSync(path.join(here,'qa/build.json'),JSON.stringify({htmlBytes:Buffer.byteLength(html),htmlSha256:hash(html),originalHtmlSha256:hash(reviewHtml),originalMarkdownSha256:hash(reviewMarkdown),scenes:content.scenes.length,skills:skills.length,sourceGroups:Object.keys(sources).length,sourcePassages:Object.values(sources).flat().length},null,2)+'\n');
const guide=`# Presenter guide — Inside Codex Data

## Run of show

Open index.html directly in a browser. Use normal scrolling for preparation and exploration. For screen sharing, choose Presentation mode. Left/Right, Up/Down, PageUp/PageDown, or Space advance major scenes when focus is outside an interactive control; Escape exits. Use visible Previous/Next controls at any time. Focus on a button, select, or source drawer keeps that control’s normal keyboard behavior. The page remains scrollable in presentation mode; no content is clipped into a fixed slide canvas.

Plan for **27 minutes** without live demos. Demonstrations are optional: replace discussion time or add 4–8 minutes. All numbers and advisor examples are visibly labelled teaching fixtures. Never present them as plugin test output or business findings.

Start at scene 1. Keep Under the Hood closed during the main narrative; open only the detail that answers the audience’s question. The four colors stay consistent: blue Agent, violet Skills, amber Evidence, mint Artifact. The original review remains available after the final scene.

${content.scenes.map((s,i)=>`## ${i+1}. ${s.nav} — ${s.duration} minutes

**Purpose:** ${s.purpose}

**Key takeaway:** ${s.takeaway}

**Talking points / interaction:** ${s.talk}

**Optional live demo:** ${s.body.includes('LIVE DEMO')?'Expand the marked Live Demo panel and copy its prompt into Codex. Return to the same scene afterward.':'No live demo needed; the teaching interaction stands alone.'}
`).join('\n')}
## Technical guardrails for the presenter

- Skills are instructions and responsibilities, not necessarily separate agents or execution processes.
- The end-to-end walkthrough is an illustrative route. Actual analysis can iterate or omit unnecessary steps.
- Reports and dashboards use the shared React app. Notebooks and document conversions branch to their respective tools.
- Saved provenance supports inspection; it does not authenticate the agent’s claim that a query ran or prove correct causal inference.
- Presentation filters can change the visible population without mutating stored rows. Hiding a component is not access control.
- Stable IDs are logical references, not content hashes or secrets.
- The state exercise’s stale-narrative warning is a teaching mechanism, not an assertion that Data automatically detects stale prose.
- Offline rendering does not imply offline source execution, scheduled refresh, or host-assisted conversion.
- Source/build integrity checks are not arbitrary-code sandboxing or independent publisher signatures.

## Audience self-check / coverage

| Question after the session | Scene |
|---|---|
| What problem is Data solving? | 1 |
| Is it an agent, skill library, framework, or artifact system? | 2, 8, 11 |
| What does the host supply? | 3, 11 |
| What is a skill and why specialize? | 4 |
| How does a request become a dashboard? | 3 |
| What is reviewed evidence and why preserve provenance? | 5 |
| What is the artifact contract and why stable IDs? | 6 |
| Why separate evidence and presentation? | 7 |
| Why a runtime/compiler? | 8 |
| How do report and dashboard jobs differ? | 9 |
| What happens during refresh? | 7, 10 |
| What should we borrow, and what may be too much? | 12, 13 |

For a 20-minute version: demonstrate four request steps (1, 4, 6, 9), inspect two skills, and discuss three borrowing patterns. For a 30-minute version: let the audience choose another skill and one trade-off. This timing is a presenter plan, not a measured learning outcome.
`;
fs.writeFileSync(path.join(here,'PRESENTER_GUIDE.md'),guide);
console.log(`Built ${path.join(here,'index.html')} — ${content.scenes.length} scenes, ${skills.length} skills, ${Buffer.byteLength(html)} bytes`);
