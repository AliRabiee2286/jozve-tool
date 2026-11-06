// Execute the report's actual inline script against a minimal DOM, without packages or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const reduced = process.argv[3] === 'reduce';
class Element {
  constructor(textContent = '', dataset = {}) {
    Object.assign(this, {textContent, dataset, value: '', hidden: false, open: false});
    this.listeners = {};
    this.attrs = {};
    this.style = {setProperty: (key, value) => { this.attrs[key] = value; }};
  }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  setAttribute(key, value) { this.attrs[key] = value; }
  querySelector() { return this; }
  focus() { this.focused = true; }
  fire(event) { this.listeners[event](); }
}
const text = value => value.replace(/<[^>]*>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const ids = Object.fromEntries(['search', 'status-filter', 'results-count', 'empty', 'print-report']
  .map(id => [id, new Element()]));
ids['status-filter'].value = 'all';
const rows = [...html.matchAll(/<tr data-status="([A-Z]+)" data-file="([^"]+)">([\s\S]*?)<\/tr>/g)]
  .map(match => new Element(text(match[3]), {status: match[1], file: match[2]}));
const fileStarts = [...html.matchAll(/<details class="file-card [^"]+" id="([^"]+)"/g)];
fileStarts.forEach((match, index) => {
  const content = html.slice(match.index, fileStarts[index + 1]?.index || html.indexOf('<footer>'));
  ids[match[1]] = new Element(text(content));
});
const cards = [...html.matchAll(/data-filter="([A-Z]+)"/g)]
  .map(match => new Element('', {filter: match[1]}));
const links = [...html.matchAll(/data-open="([^"]+)"/g)]
  .map(match => new Element('', {open: match[1]}));
const counters = [...html.matchAll(/data-count="(\d+)"/g)]
  .map(match => new Element(match[1], {count: match[1]}));
const ring = new Element();
const disclosures = [new Element(), new Element()];
disclosures[1].open = true;
let printed = false;
let frames = 0;
const windowListeners = {};
const document = {
  getElementById: id => ids[id],
  querySelector: () => ring,
  querySelectorAll: selector => ({
    'tbody tr[data-file]': rows, '[data-filter]': cards,
    '[data-open]': links, '[data-count]': counters,
    '.detail-disclosure': disclosures,
  }[selector]),
};
const context = {
  document, Intl, performance: {now: () => 0},
  window: {matchMedia: () => ({matches: reduced}), print: () => { printed = true; },
    addEventListener: (event, callback) => { windowListeners[event] = callback; }},
  requestAnimationFrame: callback => { frames += 1; callback(700); },
};
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInNewContext(source, context, {timeout: 2000});
assert.equal(rows.length, 3);
assert.equal(rows.filter(row => !row.hidden).length, 3);
ids['status-filter'].value = 'REVIEW';
ids['status-filter'].fire('change');
assert.deepEqual(rows.map(row => row.hidden), [true, false, true]);
assert.equal(ids['file-2'].hidden, false);
ids.search.value = 'no matching lesson';
ids.search.fire('input');
assert.equal(rows.filter(row => !row.hidden).length, 0);
assert.equal(ids.empty.hidden, false);
ids.search.value = 'فيزيك'; // Arabic yeh/kaf should match the Persian sheet label.
ids.search.fire('input');
assert.equal(rows.filter(row => !row.hidden).length, 1);
ids.search.value = '';
cards.find(card => card.dataset.filter === 'REVIEW').fire('click');
assert.equal(ids['status-filter'].value, 'all');
assert.equal(rows.filter(row => !row.hidden).length, 3);
links[0].fire('click');
assert.equal(ids['file-1'].open, true);
assert.equal(ids['file-1'].focused, true);
ids['print-report'].fire('click');
assert.equal(printed, true);
ids['file-1'].open = false;
windowListeners.beforeprint();
assert.ok(disclosures.every(detail => detail.open));
assert.ok(rows.every(row => ids[row.dataset.file].open));
windowListeners.afterprint();
assert.deepEqual(disclosures.map(detail => detail.open), [false, true]);
assert.equal(ids['file-1'].open, false);
assert.equal(frames, reduced ? 0 : 1);
assert.ok(counters.every(counter => counter.textContent ===
  new Intl.NumberFormat('fa-IR').format(Number(counter.dataset.count))));
console.log('Inline script: filter, search, details, print, and motion checks passed');
