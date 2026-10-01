// Host-only candidate probe. This does not establish customer OS isolation.
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';

const candidate='/opt/agentai-native/2026.9.6-node24.16.0';
const require=createRequire(candidate+'/cli/package.json');
const { root, configureFsSafeNative }=require('@openclaw/fs-safe');
configureFsSafeNative({mode:'require'});
const temp=await fs.mkdtemp(candidate+'/probe-fs-');
try {
  const base=path.join(temp,'base');
  await fs.mkdir(base,{mode:0o700});
  await fs.writeFile(path.join(base,'canary'),'public-synthetic-check');
  await fs.writeFile(path.join(temp,'outside'),'public-synthetic-outside');
  await fs.symlink('../outside',path.join(base,'link'));
  const scoped=await root(base,{symlinks:'reject',hardlinks:'reject',maxBytes:128});
  const result=await scoped.read('canary');
  const positive=result.buffer.toString()==='public-synthetic-check';
  let traversal=false,symlink=false;
  try { await scoped.read('../outside'); } catch { traversal=true; }
  try { await scoped.read('link'); } catch { symlink=true; }
  // Atomic no-clobber move is native-only: no supported JS fallback.
  await scoped.move('canary','verified',{overwrite:false});
  const moved=(await scoped.read('verified')).buffer.toString()==='public-synthetic-check';
  console.log(JSON.stringify({native_mode:'require',positive_read:positive,
    traversal_denied:traversal,symlink_denied:symlink,native_no_clobber_move:moved,
    customer_os_isolation_proven:false}));
  if (!positive || !traversal || !symlink || !moved) process.exitCode=1;
} finally {
  await fs.rm(temp,{recursive:true,force:true});
}
