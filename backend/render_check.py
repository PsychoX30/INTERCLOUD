import sys, os
base = "/home/support/INTERCLOUD/backend"
sys.path.insert(0, base)
os.chdir(base)

import portal.routes.business as biz

samples = "/tmp/doc_preview_samples"
results = {}

with open(f"{samples}/sample.docx","rb") as f:
    results["docx"] = biz._preview_docx_html(f.read())
with open(f"{samples}/sample.pptx","rb") as f:
    results["pptx"] = biz._preview_pptx_html(f.read())
with open(f"{samples}/sample.xlsx","rb") as f:
    results["xlsx"] = biz._preview_xlsx_html(f.read())
with open(f"{samples}/sample.odt","rb") as f:
    results["odt"] = biz._preview_odf_html(f.read(), "odt")

for k, v in results.items():
    print(f"===== {k.upper()} preview ({len(v)} chars) =====")
    print(v[:1500])
    print()

# also exercise the import-guard fallback behavior by monkeypatching import
import builtins
real_import = builtins.__import__
def no_docx_import(name, *a, **kw):
    if name == "docx":
        raise ImportError("No module named 'docx'")
    return real_import(name, *a, **kw)
builtins.__import__ = no_docx_import
with open(f"{samples}/sample.docx","rb") as f:
    fallback = biz._preview_docx_html(f.read())
builtins.__import__ = real_import
print("===== DOCX ImportError fallback =====")
print(fallback)
