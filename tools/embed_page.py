#!/usr/bin/env python3
"""embed_page.py -- a page template with the wasm build embedded in it: one file that works from disk.

    python tools/embed_page.py <template> <tzdig.wasm> <IANA version> <out> [--doctype]

{{WASM_BASE64}} becomes the wasm, base64; {{IANA}} the zone database's version. --doctype puts
`<!doctype html>` in front, for a template written without one: the phone page is, because the
place it is published wraps the page in its own document and wants none of ours.
"""
import base64
import sys

template, wasm, iana, out = sys.argv[1:5]
page = open(template, encoding="utf-8").read()
page = page.replace("{{WASM_BASE64}}", base64.b64encode(open(wasm, "rb").read()).decode()).replace("{{IANA}}", iana)
if "{{" in page:
    sys.exit("embed_page: %s still has a {{placeholder}} after embedding" % template)
if "--doctype" in sys.argv[5:]:
    page = '<!doctype html>\n<html lang="en">\n' + page
open(out, "w", encoding="utf-8", newline="\n").write(page)
