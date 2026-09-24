// run_wasm.js -- run dist/tzdig.wasm under node with standard input and output, the same host functions
// the web page gives it (web/template.html, runWhen). build.sh checks the known answers through this,
// so the build that is tested is the build the page runs.
//
//   node tools/run_wasm.js dist/tzdig.wasm < input.txt
"use strict";
const fs = require("fs");

const bytes = fs.readFileSync(process.argv[2]);
const input = fs.readFileSync(0);
const decoder = new TextDecoder();
const out = [];
let cur = 0, memory = null;
const env = {
  print: (x) => out.push(String(x | 0) + "\n"),
  print_f64: (x) => out.push(String(x) + "\n"),
  print_i64: (x) => out.push(String(x) + "\n"),
  read: (fd, ptr, len) => {
    if (fd !== 0) return -1;
    const m = new Uint8Array(memory.buffer);
    let i = 0;
    while (i < len && cur < input.length) m[ptr + i++] = input[cur++];
    return i;
  },
  write: (fd, ptr, len) => {
    if (fd !== 1 && fd !== 2) return -1;
    out.push(decoder.decode(new Uint8Array(memory.buffer, ptr, len).slice()));
    return len;
  },
  open: () => -1,
  close: () => -1,
  // 55 is the clock: the year of a date written without one (the known answers set their own "now")
  host_call: (id) => (id === 55 ? Math.floor(Date.now() / 1000) | 0 : -1),
};
WebAssembly.instantiate(bytes, { env }).then(({ instance }) => {
  memory = instance.exports.memory;
  instance.exports.main();
  process.stdout.write(out.join(""));
}).catch((e) => {
  process.stdout.write(out.join(""));
  process.stderr.write("tzdig stopped: " + e.message + "\n");
  process.exit(1);
});
