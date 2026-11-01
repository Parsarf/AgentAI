// Uses tests/mcp_ui_fixture.py: real Django auth/APIs, encrypted DB, SDK and runtime proof; synthetic external service only.
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const origin = process.argv[2];
if (!/^https:\/\/localhost:\d+$/.test(origin || '')) throw new Error('Pass the local TLS fixture origin printed by mcp_ui_fixture.py');
await mkdir('/tmp/lumina-mcp-ui', { recursive: true });
const waitChecked = async (locator, value) => { for (let n=0;n<50;n++) { if (await locator.getAttribute('aria-checked')===value) return; await new Promise(r=>setTimeout(r,100)); } throw new Error('Switch did not update'); };
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width, height: 1000 } });
    const page = await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin+'/app/integrations');
    await page.getByLabel('Email',{exact:true}).fill('mcp-fixture@example.invalid');
    await page.getByLabel('Password',{exact:true}).fill('Lumina fixture password 2026!');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:'MCP connections',exact:true}).waitFor();
    const addButton=page.getByRole('button',{name:'Add custom server'});
    for (let n=0;n<50 && !await addButton.isEnabled();n++) await new Promise(r=>setTimeout(r,100));
    while (await page.getByRole('button',{name:'Disconnect',exact:true}).count()) {
      const count=await page.getByRole('button',{name:'Disconnect',exact:true}).count();
      await page.getByRole('button',{name:'Disconnect',exact:true}).first().click();
      for (let n=0;n<50 && await page.getByRole('button',{name:'Disconnect',exact:true}).count()===count;n++) await new Promise(r=>setTimeout(r,100));
    }
    await page.getByRole('button',{name:'Add custom server'}).click();
    const connectionName='Fixture '+width;
    await page.getByLabel('Connection name',{exact:true}).fill(connectionName);
    await page.getByLabel('Server URL',{exact:true}).fill('https://fixture.mcp-demo.net/mcp');
    await page.getByLabel('Authentication',{exact:true}).selectOption('none');
    await page.getByRole('button',{name:'Connect and discover tools'}).click();
    const card=page.getByRole('article',{name:connectionName,exact:true});
    await card.getByText('Connected',{exact:true}).waitFor();
    assert.equal(await card.getByRole('switch',{name:'echo',exact:true}).getAttribute('aria-checked'),'false');
    await card.getByRole('switch',{name:'echo',exact:true}).click();
    await waitChecked(card.getByRole('switch',{name:'echo',exact:true}),'true');
    const agent=async(name,arguments_={})=>(await (await page.request.post(origin+'/__fixture__/agent',{data:{name,arguments:arguments_}})).json()).result;
    const catalog=await agent('lumina_mcp_discover');
    const specs=JSON.parse(catalog.content[0].text.split('\n').slice(1).join('\n'));
    const tool=specs.find(s=>s.name.startsWith('lumina_mcp_')&&s.description.includes('Echo text'));
    assert.ok(tool,'enabled tool must reach the agent through the relay');
    const arguments_={text:'Hello from browser fixture '+width};
    const pending=await agent(tool.name,arguments_);assert.equal(pending.isError,true);assert.match(pending.content[0].text,/approval required/i);
    await page.getByRole('button',{name:'Approve this exact call'}).waitFor();
    await page.getByRole('button',{name:'Approve this exact call'}).click();
    await page.getByText(/This exact call is approved/).waitFor();
    const result=await agent(tool.name,arguments_);assert.deepEqual(result.structuredContent,arguments_);
    assert.match(result.content[0].text,/Untrusted tool data/);
    assert.equal(await page.locator('.mcp-section script').count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:`/tmp/lumina-mcp-ui/connected-${width}.png`,fullPage:true});
    await card.getByRole('switch',{name:'echo',exact:true}).click();
    await waitChecked(card.getByRole('switch',{name:'echo',exact:true}),'false');
    const disabled=await agent(tool.name,arguments_);assert.equal(disabled.isError,true);
    await card.getByLabel('Name for '+connectionName).fill(connectionName+' renamed');
    await card.getByRole('button',{name:'Save name'}).click();
    const renamed=page.getByRole('article',{name:connectionName+' renamed',exact:true});await renamed.waitFor();
    await renamed.getByRole('button',{name:'Disconnect',exact:true}).click();
    await page.getByText('No MCP servers connected.').waitFor();
    const removed=await agent(tool.name,arguments_);assert.equal(removed.isError,true);
    await page.getByRole('button',{name:'Choose a service'}).click();
    await page.getByText(/OAuth setup is not available/).waitFor();
    await page.screenshot({path:`/tmp/lumina-mcp-ui/asana-${width}.png`,fullPage:true});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({width,flow:'UI → account API → encrypted connection → SDK fixture → enabled tool → runtime proof → exact approval → result',status:'passed'}));
    await context.close();
  }
} finally { await browser.close(); }
