"""Check exact delivered diagrams without modifying or rerendering their HTML."""
import asyncio, hashlib, json, re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
VIEWPORTS = [(1440,900),(1600,1000),(1920,1080),(2048,1320)]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True,
            args=['--disable-background-networking','--disable-component-update','--no-first-run'])
        for name,query in [('general-assistant','DeepAgents harness'),('coding-workbench','Private execution')]:
            artifact=ROOT/(name+'.html'); original=artifact.read_bytes()
            context=await browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
            page=await context.new_page(); errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            await page.goto(artifact.as_uri()); await page.wait_for_timeout(100)
            measurements=[]
            for width,height in VIEWPORTS:
                await page.set_viewport_size({'width':width,'height':height}); await page.wait_for_timeout(100)
                m=await page.evaluate('''() => ({innerWidth,innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight})''')
                m['ok']=m['scrollWidth']<=width and m['scrollHeight']<=height
                assert m['ok']; measurements.append(m)
            await page.set_viewport_size({'width':1440,'height':900})
            await page.get_by_role('button',name='Find a node',exact=True).click()
            await page.get_by_placeholder('Search labels or IDs').fill(query)
            result=page.get_by_role('button',name=re.compile('^Focus '+re.escape(query)+', [0-9]+ related connections$'))
            assert await result.is_visible(); await result.click()
            close=page.get_by_role('button',name='Close semantic passport',exact=True)
            await close.wait_for(state='visible')
            await page.screenshot(path=str(ROOT/(name+'.reader-focus.png')))
            await close.click(); await close.wait_for(state='hidden')
            await page.get_by_role('button',name='Export diagram',exact=True).click()
            async with page.expect_download() as download:
                await page.get_by_text('Editable vector',exact=True).click()
            svg=ROOT/(name+'.reader-export.svg'); await (await download.value).save_as(svg)
            text=svg.read_text()
            assert text.count('<svg')==1 and query in text
            assert 'Close semantic passport' not in text and 'Export diagram' not in text
            await page.get_by_role('button',name='Export diagram',exact=True).click()
            async with page.expect_download() as download:
                await page.get_by_text('Lossless image',exact=True).click()
            png=ROOT/(name+'.reader-export.png'); await (await download.value).save_as(png)
            assert artifact.read_bytes()==original and not errors
            receipt={'evidenceKind':'supplementary-browser','artifact':{'path':str(artifact),'sha256':hashlib.sha256(original).hexdigest(),'bytes':len(original)},
                'viewports':measurements,'state':{'detail':'read','motion':'still'},'browser':'Installed Google Chrome through Playwright',
                'controls':{'search':{'query':query,'visible_result':True},'focus_passport':{'opened':True,'closed':True,'capture':name+'.reader-focus.png'},
                    'exports':{'svg':{'file':svg.name,'sha256':hashlib.sha256(svg.read_bytes()).hexdigest(),'bytes':svg.stat().st_size,'clean_semantic_svg':True},
                               'png':{'file':png.name,'sha256':hashlib.sha256(png.read_bytes()).hexdigest(),'bytes':png.stat().st_size}}},
                'page_errors':errors,'html_unchanged':True,'visualReview':'pending'}
            (ROOT/(name+'.reader-controls.json')).write_text(json.dumps(receipt,indent=2)+'\n')
            print(json.dumps({'diagram':name,'status':'pass','measurements':len(measurements),'search_focus_close_svg_png':True}))
            await context.close()
        await browser.close()

asyncio.run(main())
