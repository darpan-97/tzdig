#!/usr/bin/env bash
# build.sh -- every build of `tzdig` that nitro can make, each checked against the known answers in
# tests/vectors.tsv. One source, many outputs; an output that gives a different answer fails the build.
#
#   bash build.sh          every build, side by side (about 20 s):
#       dist/tzdig.exe       native, from nitro's ISO C at clang -O2 -- the command-line tool
#       web/index.html       the web page, from nitro's wasm
#       web/mobile.html      the phone page: one timestamp in all 418 zones, grouped by UTC offset
#       dist/tzdig.cpp       readable C++ (with nitro_rt.h), built with clang++ -O2
#       dist/tzdig.rs        readable Rust (with nitro_rt.rs), built with rustc -O
#       dist/tzdig.js        readable JavaScript (with node_modules/nitro_rt.js), run by node
#       dist/tzdig_aot.exe   native with no C compiler at all: nitro's own AOT, in under a second
#   bash build.sh --fast   nirvm and the native binary at -O0 (about 5 s) -- for trying things
#   bash build.sh --python adds dist/tzdig.py, from nitro's Python back end. It gives every known answer
#                          but runs the program as emulated machine code: one value with a zone takes
#                          about 30 s, so it proves the back end rather than ships a tool.
#
# Every build but the web page takes the command line, so each is checked the way it is used:
# `<build> --vectors < tests/vectors.tsv`. The page has no command line; its options come on a first
# "#tzdig" line of the input, and the wasm is checked that way.
#
# Needs the nitro toolchain: NITRO is its checkout (default ~/Desktop/NITRO), NIRVM its VM. CC, CXX,
# RUSTC, NODE and a Python are found on PATH (or set); a build whose tool is missing is skipped ALOUD.
# Nothing here regenerates src/zones.nitro: that is tools/make_zones.py, run when IANA publishes.
set -u
cd "$(dirname "$0")"
ROOT="$(pwd)"
NITRO="${NITRO:-$HOME/Desktop/NITRO}"
FAST=0; PYTHON=0
for a in "$@"; do case "$a" in --fast) FAST=1 ;; --python) PYTHON=1 ;; *) echo "build: unknown option $a"; exit 2 ;; esac; done
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1; EXE=.exe ;; *) WIN=0; EXE= ;; esac
if [ -z "${NIRVM:-}" ]; then
    if [ $WIN = 1 ]; then NIRVM="$NITRO/nirvm.exe"; else NIRVM="$NITRO/build/release/nirvm"
        [ -x "$NIRVM" ] || NIRVM="$NITRO/build/linux/release/nirvm"; fi
fi
LLVM="/c/Program Files/LLVM/bin"
if [ -z "${CC:-}" ]; then
    if [ $WIN = 1 ] && [ -x "$LLVM/clang.exe" ]; then CC="$LLVM/clang.exe"; else CC="$(command -v clang || command -v cc)"; fi
fi
if [ -z "${CXX:-}" ]; then
    if [ $WIN = 1 ] && [ -x "$LLVM/clang++.exe" ]; then CXX="$LLVM/clang++.exe"; else CXX="$(command -v clang++ || command -v g++ || true)"; fi
fi
RUSTC="${RUSTC:-$(command -v rustc || true)}"
NODE="${NODE:-$(command -v node || true)}"
PY="$(command -v python3 || command -v python)"
[ -x "$NIRVM" ] || { echo "build: no nirvm at $NIRVM (set NITRO or NIRVM)"; exit 1; }
[ -n "$CC" ] || { echo "build: no C compiler (set CC)"; exit 1; }
mkdir -p dist
ms() { echo $(( $(date +%s%N) / 1000000 )); }
T0=$(ms)
VEC="$ROOT/tests/vectors.tsv"
WANT="$(tr -d '\r' < "$VEC")"
# the page's form of the same questions: the options on a first "#tzdig" line. It also names zones
# with a quoted space: a build that reads the line differently from a shell stops at "no zone called".
{ printf '#tzdig --vectors --in "au sydney, est"\n'; cat "$VEC"; } > dist/vectors_in.txt

# same <what> <output file>: the same rows back, line endings aside
same() {
    if [ "$(tr -d '\r' < "$2")" = "$WANT" ]; then echo "  $1: $(grep -c . "$VEC") known answers match"; return 0; fi
    diff <(printf '%s\n' "$WANT") <(tr -d '\r' < "$2") | head -8
    echo "FAIL: $1 does not give the known answers"; return 1
}
# nirvm transpile reads nitro's transpilers relative to its own checkout, so it runs from there
nitro() { (cd "$NITRO" && NITRO_LIB=lib "$NIRVM" "$@"); }
bad() { echo "FAIL: $*"; return 1; }

# ---- the builds; each is independent of the others and runs beside them -----------------------
b_nirvm() {     # the reference: nitro's VM, then its JIT
    nitro run "$ROOT/src/tzdig.nitro" --vectors < "$VEC" > dist/out_vm.txt 2>&1; same "nirvm" dist/out_vm.txt || return 1
    [ $FAST = 1 ] && return 0
    nitro run --engine jit "$ROOT/src/tzdig.nitro" --vectors < "$VEC" > dist/out_jit.txt 2>&1
    same "nirvm JIT" dist/out_jit.txt
}
b_native() {
    if [ $FAST = 1 ]; then
        nitro transpile "$ROOT/src/tzdig.nitro" --target c -o "$ROOT/dist/tzdig.c" > dist/transpile.log 2>&1 || bad "transpile to C (dist/transpile.log)" || return 1
        "$CC" -O0 -w -o "dist/tzdig$EXE" dist/tzdig.c || bad "C compile" || return 1
    else
        nitro transpile "$ROOT/src/tzdig.nitro" --target iso-c -o "$ROOT/dist/tzdig.c" > dist/transpile.log 2>&1 || bad "transpile to ISO C (dist/transpile.log)" || return 1
        "$CC" -O2 -w -std=c99 -o "dist/tzdig$EXE" dist/tzdig.c || bad "C compile" || return 1
    fi
    "./dist/tzdig$EXE" --vectors < "$VEC" > dist/out_native.txt 2>&1
    same "native dist/tzdig$EXE ($(wc -c < "dist/tzdig$EXE") bytes)" dist/out_native.txt
}
b_web() {
    nitro transpile "$ROOT/src/tzdig_web.nitro" --target wasm -o "$ROOT/dist/tzdig.wasm" > dist/transpile_wasm.log 2>&1 || bad "transpile to wasm (dist/transpile_wasm.log)" || return 1
    if [ -n "$NODE" ]; then
        "$NODE" tools/run_wasm.js dist/tzdig.wasm < dist/vectors_in.txt > dist/out_wasm.txt 2>&1
        same "wasm dist/tzdig.wasm" dist/out_wasm.txt || return 1
    else
        echo "  wasm: no node on PATH -- the wasm build is NOT checked"
    fi
    local iana; iana=$(sed -n 's/^pub fn zones_version(): return "\(.*\)"$/\1/p' src/zones.nitro)
    "$PY" tools/embed_page.py web/template.html dist/tzdig.wasm "$iana" web/index.html || bad "web page" || return 1
    "$PY" tools/embed_page.py web/mobile_template.html dist/tzdig.wasm "$iana" web/mobile.html --doctype || bad "phone page" || return 1
    echo "  web/index.html: $(wc -c < web/index.html) bytes, web/mobile.html: $(wc -c < web/mobile.html) bytes, IANA $iana"
}
b_cpp() {
    [ -n "$CXX" ] || { echo "  readable C++: no clang++ or g++ -- NOT built"; return 0; }
    nitro transpile "$ROOT/src/tzdig.nitro" --target cpp -o "$ROOT/dist/tzdig.cpp" > dist/transpile_cpp.log 2>&1 || bad "transpile to C++ (dist/transpile_cpp.log)" || return 1
    cp "$NITRO/lib/nitro_rt.h" dist/
    "$CXX" -std=c++17 -O2 -fwrapv -w -Idist -o "dist/tzdig_cpp$EXE" dist/tzdig.cpp || bad "C++ compile" || return 1
    "./dist/tzdig_cpp$EXE" --vectors < "$VEC" > dist/out_cpp.txt 2>&1
    same "readable C++ dist/tzdig.cpp" dist/out_cpp.txt
}
b_rust() {
    [ -n "$RUSTC" ] || { echo "  readable Rust: no rustc -- NOT built"; return 0; }
    nitro transpile "$ROOT/src/tzdig.nitro" --target rust -o "$ROOT/dist/tzdig.rs" > dist/transpile_rust.log 2>&1 || bad "transpile to Rust (dist/transpile_rust.log)" || return 1
    cp "$NITRO/lib/nitro_rt.rs" dist/
    "$RUSTC" -O --crate-type rlib dist/nitro_rt.rs -o dist/libnitro_rt.rlib || bad "Rust runtime compile" || return 1
    "$RUSTC" --edition 2021 -O --extern nitro_rt=dist/libnitro_rt.rlib -o "dist/tzdig_rs$EXE" dist/tzdig.rs || bad "Rust compile" || return 1
    "./dist/tzdig_rs$EXE" --vectors < "$VEC" > dist/out_rust.txt 2>&1
    same "readable Rust dist/tzdig.rs" dist/out_rust.txt
}
b_js() {
    [ -n "$NODE" ] || { echo "  readable JavaScript: no node -- NOT built"; return 0; }
    nitro transpile "$ROOT/src/tzdig.nitro" --target nodejs -o "$ROOT/dist/tzdig.js" > dist/transpile_js.log 2>&1 || bad "transpile to JavaScript (dist/transpile_js.log)" || return 1
    mkdir -p dist/node_modules && cp "$NITRO/lib/nitro_rt.js" dist/node_modules/
    "$NODE" dist/tzdig.js --vectors < "$VEC" > dist/out_js.txt 2>&1
    same "readable JavaScript dist/tzdig.js" dist/out_js.txt
}
b_py() {        # nitro's Python back end (the transpiler's mode 9, run from its toolgen copy)
    [ -f "$NITRO/toolgen/ut_py.nitro" ] || { echo "  Python: this nitro has no Python back end (toolgen/ut_py.nitro) -- NOT built"; return 0; }
    nitro ut-input "$ROOT/src/tzdig.nitro" -o "$ROOT/dist/tzdig_py.bin" -t 9 > dist/transpile_py.log 2>&1 || bad "Python: the transpiler input (dist/transpile_py.log)" || return 1
    tail -c +2 dist/tzdig_py.bin > dist/tzdig_py.nir
    (cd "$NITRO" && NIRVM_BINARY_STDIO=1 NIRVM_HEAP=512 NITRO_LIB=lib "$NIRVM" run toolgen/ut_py.nitro "$ROOT/dist/tzdig_py.nir") \
        > dist/tzdig.py 2>> dist/transpile_py.log || bad "transpile to Python (dist/transpile_py.log)" || return 1
    "$PY" dist/tzdig.py --vectors < "$VEC" > dist/out_py.txt 2>&1
    same "Python dist/tzdig.py" dist/out_py.txt
}
b_aot() {
    nitro build "$ROOT/src/tzdig.nitro" -o "$ROOT/dist/tzdig_aot$EXE" > dist/aot.log 2>&1 || bad "nitro AOT (dist/aot.log)" || return 1
    "./dist/tzdig_aot$EXE" --vectors < "$VEC" > dist/out_aot.txt 2>&1
    same "AOT dist/tzdig_aot$EXE ($(wc -c < "dist/tzdig_aot$EXE") bytes, no C compiler)" dist/out_aot.txt
}

BUILDS="nirvm native"; [ $FAST = 0 ] && BUILDS="$BUILDS web cpp rust js aot"; [ $PYTHON = 1 ] && BUILDS="$BUILDS py"
echo "tzdig: building with $NIRVM"
PIDS=""
for b in $BUILDS; do
    ( s=$(ms); "b_$b" > "dist/log_$b.txt" 2>&1; rc=$?; echo "  ($b: $(( $(ms) - s )) ms)" >> "dist/log_$b.txt"; exit $rc ) &
    PIDS="$PIDS $!"
done
FAILED=""
set -- $PIDS
for b in $BUILDS; do
    wait "$1" || FAILED="$FAILED $b"
    cat "dist/log_$b.txt"
    shift
done
[ -z "$FAILED" ] || { echo "FAIL:$FAILED"; exit 1; }
echo "PASS: tzdig built and checked in $(( $(ms) - T0 )) ms"
