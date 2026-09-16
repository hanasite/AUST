import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// fileURLToPath correctly decodes percent-encoded non-ASCII path segments
// (the repo path contains CJK characters) and handles the Windows drive prefix.
const dir = fileURLToPath(new URL('./icons/', import.meta.url));
const out = fileURLToPath(new URL('./sprite-out.html', import.meta.url));
const ids = { 'chart-column':'ic-chart', 'refresh-cw':'ic-refresh', 'graduation-cap':'ic-gradcap',
  'book-open':'ic-book', 'smartphone':'ic-phone', 'circle-alert':'ic-alert' };

const files = fs.readdirSync(dir).filter(f => f.endsWith('.svg'));
const symbols = files.map(f => {
  const name = f.replace('.svg', '');
  const id = ids[name] || ('ic-' + name);
  let svg = fs.readFileSync(path.join(dir, f), 'utf8');
  const viewBox = (svg.match(/viewBox="([^"]+)"/) || [, '0 0 24 24'])[1];
  // The opening <svg …> tag (carrying the root width/height/class) is removed by the
  // first replace, so width/height must NOT be stripped globally: inner <rect width height>
  // values are geometry and a rect without them renders invisible.
  const inner = svg.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>[\s\S]*$/, '')
    .replace(/\s*class="[^"]*"/g, '').trim();
  return `  <symbol id="${id}" viewBox="${viewBox}">${inner}</symbol>`;
}).sort();
fs.writeFileSync(out, `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n${symbols.join('\n')}\n</svg>\n`);
console.log('symbols:', symbols.length);
