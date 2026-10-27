// Fails when a stylesheet or component hardcodes a colour instead of using a token from src/styles/tokens.css.
// Allowed: tokens.css itself, safety.css (its own palette), pure-black scrims (rgb(0 0 0 / x)), chart data colours in genui/Cards.tsx, vendored code, emoji data.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
const ROOT = new URL('../src/', import.meta.url).pathname;
// styles/safety.css keeps its own grayscale terminal palette on purpose (the Safety console is meant to look apart from Lumina's design system).
const SKIP = [/styles\/tokens\.css$/, /styles\/safety\.css$/, /\/vendor\//, /\/openmoji/, /\.test\./, /genui\/Cards\.tsx$/, /\.json$/];
const COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\((?!\s*0[ ,]+0[ ,]+0\b)(?![^)]*var\()[^)]*\)|\bhsla?\([^)]*\)/g;
const hits = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { walk(path); continue; }
    if (!/\.(css|tsx?)$/.test(name) || SKIP.some(r => r.test(path))) continue;
    readFileSync(path, 'utf8').split('\n').forEach((line, i) => {
      const code = line.replace(/\/\*.*?\*\//g, '').replace(/\/\/.*$/, '');
      for (const m of code.matchAll(COLOR)) hits.push(`${path.replace(ROOT, 'src/')}:${i + 1}  ${m[0]}`);
    });
  }
})(ROOT);
if (hits.length) { console.error('Hardcoded colours (use a token from src/styles/tokens.css, see DESIGN.md):\n' + hits.join('\n')); process.exit(1); }
console.log('design check: no hardcoded colours outside tokens.css');
