// Pure-function tests for phone/www/index.html.
// The app is a single HTML file with no module boundary, so the functions under test
// are regex-extracted from the source and evaluated here (same pattern used during
// P1/P2 review). Assertions live in this repo so contributors can re-run them.
//
// Usage: node phone/tools/test-pure.mjs
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// fileURLToPath decodes the percent-encoded CJK path segments of this repo.
const htmlPath = fileURLToPath(new URL('../www/index.html', import.meta.url));
const html = fs.readFileSync(htmlPath, 'utf8');

function extract(name, re) {
  const m = html.match(re);
  if (!m) {
    console.error(`[extract] ${name}() not found in ${htmlPath}`);
    process.exit(1);
  }
  // Wrap in parens: ESM is strict mode, so a bare eval of `function f(){}` would not
  // leak the declaration into this scope, but the expression form returns the function.
  return eval('(' + m[0] + ')');
}

const normalizeUrl = extract('normalizeUrl', /function normalizeUrl\(input\)\s*\{[\s\S]*?\n\}/);
const escHtml = extract('escHtml', /function escHtml\(s\)\{[^\n]*\}/);
const ensureSections = extract('ensureSections', /function ensureSections\(data, defaults\)\s*\{[\s\S]*?\n\}/);

let pass = 0, fail = 0;
function eq(label, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { pass++; return; }
  fail++;
  console.error(`FAIL ${label}\n  actual:   ${a}\n  expected: ${e}`);
}

// ---------- normalizeUrl ----------
eq('normalizeUrl github.com', normalizeUrl('github.com'), 'https://github.com');
eq('normalizeUrl https url unchanged', normalizeUrl('https://a.cn/x'), 'https://a.cn/x');
eq('normalizeUrl empty string', normalizeUrl(''), null);
eq('normalizeUrl non-url text', normalizeUrl('打不开的网址'), null);
eq('normalizeUrl scheme only', normalizeUrl('http://'), null);
eq('normalizeUrl embedded space', normalizeUrl('https://a b.com'), null);
eq('normalizeUrl ip:port', normalizeUrl('10.255.0.19:8080'), 'http://10.255.0.19:8080');
eq('normalizeUrl localhost:port', normalizeUrl('localhost:3000'), 'http://localhost:3000');
eq('normalizeUrl trims input', normalizeUrl('  github.com  '), 'https://github.com');
eq('normalizeUrl null input', normalizeUrl(null), null);
eq('normalizeUrl bare domain + path', normalizeUrl('a.cn/x'), 'https://a.cn/x');

// ---------- escHtml ----------
eq('escHtml escapes all five', escHtml('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
eq('escHtml mixed text',
  escHtml('a & b <c> "d" \'e\''),
  'a &amp; b &lt;c&gt; &quot;d&quot; &#39;e&#39;');
eq('escHtml coerces non-string', escHtml(42), '42');
eq('escHtml re-escapes entities', escHtml('&amp;'), '&amp;amp;');

// ---------- ensureSections ----------
// Missing defaults are merged in.
{
  const data = [{ section: 'A', items: [{ n: 1 }] }];
  const defaults = [{ section: 'A', items: [{ n: 9 }] }, { section: 'B', items: [{ n: 2 }] }];
  const res = ensureSections(data, defaults);
  eq('ensureSections merge length', res.length, 2);
  eq('ensureSections merge appended default', res[1], { section: 'B', items: [{ n: 2 }] });
  eq('ensureSections existing section untouched', res[0].items, [{ n: 1 }]);
}
// EMPTY sections are preserved (not re-populated from defaults).
{
  const data = [{ section: 'A', items: [] }];
  const defaults = [{ section: 'A', items: [{ n: 9 }] }];
  const res = ensureSections(data, defaults);
  eq('ensureSections empty section length', res.length, 1);
  eq('ensureSections empty section kept empty', res[0].items, []);
}
// Section order: data order first, then missing defaults in defaults order.
{
  const data = [{ section: 'B', items: [] }, { section: 'A', items: [] }];
  const defaults = [{ section: 'A', items: [] }, { section: 'B', items: [] }, { section: 'C', items: [] }];
  eq('ensureSections order stable', ensureSections(data, defaults).map(s => s.section), ['B', 'A', 'C']);
}
// Defaults items are deep-copied before merging.
{
  const defaults = [{ section: 'X', items: [{ n: 1 }] }];
  const res = ensureSections([], defaults);
  eq('ensureSections empty data gets all defaults', res.length, 1);
  res[0].items[0].n = 99;
  eq('ensureSections deep-copies default items', defaults[0].items[0].n, 1);
}

const total = pass + fail;
console.log(`PASS ${pass}/${total}`);
if (fail > 0) {
  console.error(`${fail} assertion(s) failed`);
  process.exit(1);
}
