// Static layout check (part of `npm run build`, see LAYOUT.md). It reads every stylesheet and component of the app and fails on layout patterns that break when
// content changes, before anything is drawn. Three kinds of rule:
//
//   prohibited      never right in Lumina; change the code
//     z-index-raw       a z-index that is neither a layer token (var(--z-*), tokens.css) nor a small local order (-1..9) inside a component
//     vh-size           a height sized in vh: on phones vh includes the browser's bars, so the bottom is hidden. Use dvh
//     modifier-root     a bare modifier class (.md, .sm, .ok, .small…) given layout of its own: any component that uses the word as a modifier inherits it
//                       (this is how the task Status mark was squeezed to 9px by MasterDetail's old `.md` rule)
//   justify         allowed only with a reason: a comment containing "layout:" or "layer:" in the rule or on the line just above it
//     position-fixed    fixed boxes cover the page: say which layer it is
//     position-absolute out of the flow, so it cannot make room for anything (pseudo-elements and the visually-hidden pattern are exempt)
//     negative-margin   pulls a box over its neighbour
//     clip-fixed-height overflow hidden on a fixed pixel height: content that grows is cut without any sign (ellipsis and line clamps are exempt)
//     translate-offset  a transform placing a positioned box (centring by translate): it moves the paint, not the layout
//   inline styles   the same position, z-index and negative-margin rules for style={{…}} in components (justify with a "// layout:" comment)
//
// `node scripts/check-layout.mjs --report` also lists spacing values that are off the token scale (not blocking: there are older ones; new code uses --space-*).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('../src/', import.meta.url).pathname;
const SKIP = [/\/vendor\//, /\/openmoji/, /\.test\./, /styles\/theme\.css$/, /styles\/tokens\.css$/, /node_modules/];
const MODIFIERS = new Set(['xs', 'sm', 'md', 'lg', 'xl', 'ok', 'bad', 'live', 'warn', 'small', 'large', 'primary', 'tertiary', 'danger', 'ghost', 'open', 'active', 'selected', 'wide', 'narrow', 'tiny', 'compact', 'on', 'off']);
const LAYOUT_PROPS = /(^|;|\s)(display|position|flex[\w-]*|grid[\w-]*|margin[\w-]*|width|height|min-width|min-height|max-width|max-height|container[\w-]*|inset|top|left|right|bottom|float|order)\s*:/;
const SCALE = new Set([0, 1, 2, 4, 8, 12, 16, 24, 32, 48]);
const REPORT = process.argv.includes('--report');

/** The problems in one file's text: [{ line, rule, text, why }]. `offScale` (optional Map) collects off-scale spacing counts under `file`. */
export function check(file, raw, offScale = null) {
  const problems = [];
  const add = (_file, line, rule, text, why) => problems.push({ line, rule, text: text.trim().slice(0, 110), why });
  {
  if (file.endsWith('.tsx')) {
    raw.split('\n').forEach((line, i, all) => {
      const style = line.match(/style=\{\{([^}]*)\}\}/g);
      if (!style) return;
      const justified = /\/\/\s*(layout|layer):|\{\/\*\s*(layout|layer):/.test(line + (all[i - 1] || ''));
      for (const s of style) {
        if (/position:\s*['"](absolute|fixed)['"]/.test(s) && !justified) add(file, i + 1, 'inline-position', s, 'justify with a "// layout:" comment, or use a class');
        if (/zIndex:\s*\d/.test(s)) add(file, i + 1, 'inline-z-index', s, 'use a --z-* layer token in a stylesheet');
        if (/margin\w*:\s*-\d|margin\w*:\s*['"][^'"]*-\d/.test(s) && !justified) add(file, i + 1, 'inline-negative-margin', s, 'justify with a "// layout:" comment');
      }
    });
    return problems;
  }
  // CSS: walk rule blocks, keeping line numbers and the comments that belong to each rule.
  const re = /([^{}]*)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(raw))) {
    const prelude = m[1], body = m[2];
    if (/@(media|container|supports|layer)\b[^{]*$/.test(prelude.trim()) && !body.includes(':')) continue;
    const selectorRaw = prelude.replace(/\/\*[\s\S]*?\*\//g, '').trim();
    if (!selectorRaw || selectorRaw.startsWith('@') || /^(from|to|\d+%)/.test(selectorRaw)) continue;
    const selector = selectorRaw.split('\n').pop().trim().replace(/^@[^{]*\{\s*/, '');
    const startIndex = m.index + prelude.length - prelude.trimStart().length;
    const line = raw.slice(0, m.index + prelude.search(/\S|$/)).split('\n').length;
    // A reason: "layout:" or "layer:" in a comment inside the rule, in the prelude, or on the line just above the selector.
    const above = raw.slice(0, startIndex).split('\n').slice(-2).join('\n');
    const justified = /\/\*[^*]*(layout|layer):/.test(body) || /\/\*[^*]*(layout|layer):/.test(prelude) || /\/\*[^*]*(layout|layer):[^*]*\*\/\s*$/.test(above);
    const code = body.replace(/\/\*[\s\S]*?\*\//g, '');
    const decl = prop => { const d = code.match(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`)); return d ? d[1].trim() : null; };
    const pseudo = /::?(before|after|backdrop|marker|-webkit-[\w-]+)/.test(selector);

    const z = decl('z-index');
    if (z && !/var\(--z-/.test(z) && !(/^-?\d+$/.test(z) && +z >= -1 && +z <= 9)) add(file, line, 'z-index-raw', `${selector} { z-index: ${z} }`, 'use a --z-* layer token (tokens.css), or a local order of -1..9');
    for (const p of ['height', 'min-height', 'max-height']) { const v = decl(p); if (v && /\d(\.\d+)?vh\b/.test(v)) add(file, line, 'vh-size', `${selector} { ${p}: ${v} }`, 'use dvh: vh is taller than what a phone shows'); }
    if (LAYOUT_PROPS.test(code)) for (const part of selector.split(',')) {
      for (const compound of part.trim().split(/\s*[\s>+~]\s*/)) {
        const classes = [...compound.matchAll(/\.([a-zA-Z][\w-]*)/g)].map(c => c[1]);
        if (classes.length === 1 && MODIFIERS.has(classes[0]) && compound.replace(/:[\w-]+(\([^)]*\))?/g, '') === '.' + classes[0] && part.trim() === compound)
          add(file, line, 'modifier-root', `${selector}`, `".${classes[0]}" is a modifier word; scope it (.component.${classes[0]})`);
      }
    }
    if (justified) continue;
    const position = decl('position');
    if (position === 'fixed') add(file, line, 'position-fixed', selector, 'say which layer it is: /* layer: … */');
    if (position === 'absolute' && !pseudo && !/clip:\s*rect\(0|clip-path:\s*inset\(50%/.test(code)) add(file, line, 'position-absolute', selector, 'out of the flow: /* layout: why it may overlap */');
    if (/(?:^|;)\s*margin[\w-]*\s*:[^;]*(?:(?:^|[\s(:,])-(?:\d*\.?\d+[a-z%]*|var)|calc\(\s*-1\s*\*)/.test(code)) add(file, line, 'negative-margin', selector, '/* layout: why it pulls over its neighbour */');
    if (/overflow(-[xy])?\s*:\s*hidden/.test(code) && /(?:^|;)\s*(max-)?height\s*:\s*\d+px/.test(code) && !/text-overflow|line-clamp|clip:\s*rect|clip-path:\s*inset\(50%/.test(code)) add(file, line, 'clip-fixed-height', selector, '/* layout: why cutting content is right here */');
    if ((position === 'absolute' || position === 'fixed') && /transform\s*:[^;]*translate|(?:^|;)\s*translate\s*:/.test(code)) add(file, line, 'translate-offset', selector, '/* layout: … */');
    if (offScale) for (const d of code.matchAll(/(?:^|;)\s*(padding|margin|gap|row-gap|column-gap)[\w-]*\s*:\s*([^;]+)/g)) for (const px of d[2].matchAll(/(-?\d+(?:\.\d+)?)px/g)) {
      const v = Math.abs(+px[1]); if (!SCALE.has(v)) offScale.set(file, (offScale.get(file) || 0) + 1);
    }
  }
  }
  return problems;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const files = [];
  (function walk(dir) { for (const name of readdirSync(dir)) { const path = join(dir, name); if (statSync(path).isDirectory()) { walk(path); continue; } if (/\.(css|tsx)$/.test(name) && !SKIP.some(r => r.test(path))) files.push(path); } })(ROOT);
  const offScale = REPORT ? new Map() : null, problems = [];
  for (const file of files) for (const p of check(file.replace(ROOT, 'src/'), readFileSync(file, 'utf8'), offScale)) problems.push(`${file.replace(ROOT, 'src/')}:${p.line}  ${p.rule}  ${p.text}${p.why ? `  (${p.why})` : ''}`);

  if (REPORT && offScale.size) { console.log('Spacing values off the token scale (report only; new code uses --space-*):'); for (const [f, n] of [...offScale].sort((a, b) => b[1] - a[1])) console.log(`  ${n}\t${f}`); }
  if (problems.length) {
    console.error(`Layout check: ${problems.length} problem(s). See LAYOUT.md for each rule and how to justify a real exception.\n` + problems.join('\n'));
    process.exit(1);
  }
  console.log('layout check: no fragile layout patterns without a reason');
}
