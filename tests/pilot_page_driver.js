// Runs the pilot page's script against a minimal DOM stub: start, answer every case with the scripted
// choices (argv[3], e.g. "ALAL..."), write a rule, press save, and print the downloaded JSON.
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const choices = process.argv[3];
const script = html.split("<script>")[1].split("</script>")[0];
const els = {};
function el(id) {
  return els[id] || (els[id] = { id, hidden: id !== "intro", value: "", textContent: "", innerHTML: "", onclick: null, tagName: "DIV", style: {} });
}
let saved = null;
const listeners = {};
global.document = {
  getElementById: el,
  addEventListener: (t, f) => (listeners[t] = f),
  createElement: () => ({ click() { saved = this.blob; }, set href(v) { }, set download(v) { } }),
};
global.performance = { now: () => 0 };
global.URL = { createObjectURL: (b) => { document.lastBlob = b; return "blob:x"; } };
global.Blob = class { constructor(parts) { this.text = parts.join(""); } };
const origCreate = document.createElement;
document.createElement = () => { const a = { click() { saved = document.lastBlob.text; } }; return a; };
eval(script);
el("start").onclick();
for (const c of choices) listeners.keydown({ key: c, target: { tagName: "BODY" } });
if (!el("end").hidden === false) { console.error("end screen not shown"); process.exit(2); }
el("rule").value = "I act when the first number is high.";
el("save").onclick();
console.log(saved);
