#!/usr/bin/env python3
"""embed_page.py -- the page template with the wasm build embedded in it: one file that works from disk.

    python tools/embed_page.py <template> <tzdig.wasm> <IANA version> <out> [--doctype | --fragment]

{{WASM_BASE64}} becomes the wasm, base64; {{IANA}} the zone database's version. --doctype puts
`<!doctype html>` in front, for a template written without one. --fragment takes the page's own
<!doctype>, <html>, <head> and <body> tags out, for a host that wraps a page in its own document
(a claude.ai artifact); everything between them is kept, in order.
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
if "--fragment" in sys.argv[5:]:
    for tag in ("<!doctype html>", '<html lang="en">', "<head>", "</head>", "<body>", "</body>", "</html>"):
        if page.count(tag + "\n") != 1:
            sys.exit("embed_page: --fragment expects one %s line in %s" % (tag, template))
        page = page.replace(tag + "\n", "", 1)
open(out, "w", encoding="utf-8", newline="\n").write(page)
