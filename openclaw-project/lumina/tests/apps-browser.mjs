import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
await fs.mkdir('/tmp/lumina-app-qa', { recursive: true });
async function fixture(page, app) {
 await page.route('**/v1/conversations/completed/messages*',route=>route.fulfill({json:{messages:[{id:1,provenance:'agent',request_id:null,content:'```lumina-app\n'+JSON.stringify(app)+'\n```',created_at:''}],tasks:[],has_more:false}}));
 await page.goto('http://127.0.0.1:5182/app/chat/completed');
 assert.equal(await page.locator('.app-player-frame').count(),0);
 await page.getByRole('button',{name:'Open app',exact:true}).click();
 return page.frameLocator('.app-player-frame');
}
try {
for (const width of [1440, 390]) for (const motion of ['no-preference','reduce']) {
 const page = await browser.newPage({viewport:{width,height:960}, reducedMotion:motion});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const player=await fixture(page,{version:1,title:'Calculator',runtime:'html',code:'<button onclick="document.querySelector(\'output\').textContent=Function(\'return 2+3\')()">Calculate</button><output></output>'});
 const ui=player.frameLocator('#view');
 await ui.getByRole('button',{name:'Calculate'}).click();
 await ui.locator('output').filter({hasText:/^5$/}).waitFor();
 assert.equal(await ui.locator('output').textContent(),'5');
 assert.equal(await ui.locator('body').evaluate(()=>{try{return !!parent.document.body}catch{return false}}),false);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal(await page.locator('.dock').evaluate(el=>getComputedStyle(el).position),'static');
 await page.screenshot({path:`/tmp/lumina-app-qa/calculator-${width}-${motion}.png`});
 await page.getByRole('button',{name:'Restart',exact:true}).click();
 await ui.getByRole('button',{name:'Calculate'}).waitFor();
 await ui.locator('output').filter({hasText:/^$/}).waitFor({state:'attached'});
 assert.equal(await ui.locator('output').textContent(),'');
 await page.getByRole('button',{name:'Close app',exact:true}).click();
 await page.locator('.app-player-frame').waitFor({state:'detached'});
 assert.equal(await page.locator('.app-player-frame').count(),0);
 await page.waitForFunction(()=>document.activeElement?.textContent==='Open app');
 assert.equal(await page.getByRole('button',{name:'Open app',exact:true}).evaluate(el=>el===document.activeElement),true);
 assert.deepEqual(errors,[]);await page.close();
}
for (const runtime of ['javascript','python']) {
 const page = await browser.newPage();
 const code=runtime==='python'?'a=int(input())\nb=int(input())\ntry:\n input()\nexcept EOFError:\n print(a+b)':'console.log(Number(prompt()) + Number(prompt())); if(prompt()!==null) throw Error(\'EOF missing\')';
 page.on('console',m=>{if(m.type()==='error')console.log('Browser error:',m.text())});
 const player=await fixture(page,{version:1,title:'Console',runtime,code});
 await player.getByRole('textbox').fill('2\n3');
 await player.getByRole('button',{name:'Run',exact:true}).click();
 await player.locator('#status').filter({hasNotText:/^Ready$/}).waitFor({timeout:5000});
 await player.locator('#status').filter({hasText:/^(Finished|Program error|Runtime could|Runtime failed|Stopped)/}).waitFor({timeout:100000});
 assert.equal(await player.locator('#status').textContent(),'Finished',(await player.locator('#output').textContent()).slice(0,1000));
 assert.equal((await player.locator('#output').textContent()).trim(),'5');
 console.log(runtime,'real execution passed');await page.close();
}
for (const [code, expected] of [["throw new Error('test failure')", 'Program error'], ["console.log('started');while(true){}", 'Stopped']]) {
 const page=await browser.newPage();
 const player=await fixture(page,{version:1,title:'Lifecycle',runtime:'javascript',code});
 await player.getByRole('button',{name:'Run',exact:true}).click();
 if(expected==='Stopped') { await player.getByText('started',{exact:true}).waitFor(); await player.getByRole('button',{name:'Stop',exact:true}).click(); }
 await player.getByText(expected,{exact:true}).waitFor();
 assert.equal(await player.getByRole('button',{name:'Run',exact:true}).isEnabled(),true);
 await page.close();
}
// The UI must remain usable while an HTML app is busy in its own frame.
{
 const page=await browser.newPage();
 const player=await fixture(page,{version:1,title:'Busy app',runtime:'html',code:'<button>Loaded</button><script>setTimeout(()=>{const until=performance.now()+3000;while(performance.now()<until){}},500)</script>'});
 await player.frameLocator('#view').getByRole('button',{name:'Loaded'}).waitFor();
 await new Promise(resolve=>setTimeout(resolve,800));
 const start=Date.now();await page.getByRole('button',{name:'Close app',exact:true}).click();
 assert.ok(Date.now()-start<1500,'A busy HTML app blocked the Close control');
 await page.close();
}
for (const code of ["console.log('x'.repeat(99999))", "for(let i=0;i<100000;i++)console.info('x')"]) {
 const page=await browser.newPage();
 const player=await fixture(page,{version:1,title:'Output budget',runtime:'javascript',code});
 await player.getByRole('button',{name:'Run',exact:true}).click();
 await player.getByText('Stopped: output limit reached.',{exact:true}).waitFor();
 assert.equal((await player.locator('#output').textContent()).length,100000);
 // Later completion events must not overwrite the limit stop or interfere with a new run.
 await new Promise(resolve=>setTimeout(resolve,100));
 assert.equal(await player.locator('#status').textContent(),'Stopped: output limit reached.');
 await player.getByRole('button',{name:'Run',exact:true}).click();
 await player.getByText('Stopped: output limit reached.',{exact:true}).waitFor();
 await page.close();
}
{
 const page=await browser.newPage();
 await page.route('**/pyodide/v0.27.7/full/pyodide.js',route=>route.abort());
 const player=await fixture(page,{version:1,title:'Runtime outage',runtime:'python',code:'print(5)'});
 await player.getByRole('button',{name:'Run',exact:true}).click();
 await player.getByText('Runtime could not load. Check your connection and try again.',{exact:true}).waitFor();
 assert.equal(await player.getByRole('button',{name:'Run',exact:true}).isEnabled(),true);
 await page.unroute('**/pyodide/v0.27.7/full/pyodide.js');
 await player.getByRole('button',{name:'Run',exact:true}).click();
 await player.locator('#status').filter({hasText:/^(Finished|Program error|Runtime could|Runtime failed|Stopped)/}).waitFor({timeout:100000});
 assert.equal(await player.locator('#status').textContent(),'Finished',(await player.locator('#output').textContent()).slice(0,1000));
 assert.equal((await player.locator('#output').textContent()).trim(),'5');
 await page.close();
}
{
 const page=await browser.newPage();let escaped=false;
 await page.route('**/v1/app?generated=1',route=>{escaped=true;return route.fulfill({json:{}})});
 const player=await fixture(page,{version:1,title:'Isolated HTML',runtime:'html',code:'<output></output><script>fetch(\'/v1/app?generated=1\').then(()=>document.querySelector(\'output\').textContent=\'escaped\').catch(()=>document.querySelector(\'output\').textContent=\'network blocked\')</script>'});
 await player.frameLocator('#view').getByText('network blocked',{exact:true}).waitFor();
 assert.equal(escaped,false);await page.close();
}
{
 const page=await browser.newPage();
 await fixture(page,{version:1,title:'Broken HTML',runtime:'html',code:'<script>throw new Error(\'visible failure\')</script>'});
 await page.getByRole('alert').filter({hasText:'App error: Uncaught Error: visible failure'}).waitFor();
 await page.getByRole('button',{name:'Restart',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'App error: Uncaught Error: visible failure'}).waitFor();
 await page.getByRole('button',{name:'Close app',exact:true}).click();
 assert.equal(await page.getByRole('alert').count(),0);
 await page.close();
}
console.log('App browser QA passed: HTML controls, restart/close, isolation, mobile/desktop, motion, JS and Python.');
}catch(error){
 for(const context of browser.contexts()) for(const page of context.pages()) {
   console.error('Visible app diagnostics:',await page.getByRole('alert').allTextContents().catch(()=>[]));
 }
 throw error;
}finally{await browser.close()}

