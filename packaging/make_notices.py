"""Write THIRD_PARTY_NOTICES.txt for the Racecraft download: every Python distribution whose code is in the
frozen app (dist/Racecraft/_internal), and every npm package in the built interface (production
dependencies and their own dependencies), each with its licence text where the package ships one.
Run by build_app.ps1 after PyInstaller, from the repo root with the project venv's python. Reads only
installed package metadata; writes THIRD_PARTY_NOTICES.txt at the repo root.

    .venv\Scripts\python packaging\make_notices.py
"""
import importlib.metadata as md
import json
import re
from pathlib import Path

internal = Path("dist/Racecraft/_internal")
top_level = {p.name.split(".")[0] for p in internal.iterdir()} | {p.stem.split(".")[0] for p in internal.glob("*.pyd")}
mapping = md.packages_distributions()
dists = set()
for name in top_level:
    for d in mapping.get(name, []) + mapping.get(name.lstrip("_"), []):
        dists.add(d)
# Distribution folders PyInstaller copied as metadata name packages too.
for p in internal.glob("*.dist-info"):
    dists.add(re.sub(r"-[^-]+\.dist-info$", "", p.name))
# Pure-Python packages are packed inside Racecraft.exe, not as folders: add racecraft's whole runtime
# dependency tree (its own requirements plus the "app" extra), followed through each package's requirements.
from packaging.requirements import Requirement
todo = []
for spec in md.distribution("racecraft").requires or []:
    req = Requirement(spec)
    if req.marker is None or req.marker.evaluate({"extra": "app"}):
        todo.append(req.name)
todo += sorted(dists)       # the folder-found ones' own requirements count too
explored = set()
while todo:
    name = todo.pop()
    if name.lower().replace("_", "-") in explored:
        continue
    explored.add(name.lower().replace("_", "-"))
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        continue
    dists.add(dist.metadata["Name"])
    for spec in dist.requires or []:
        req = Requirement(spec)
        if req.marker is None or req.marker.evaluate({"extra": ""}):
            todo.append(req.name)
SKIP = {"racecraft", "pyinstaller", "pyinstaller-hooks-contrib", "pip", "setuptools", "wheel", "pytest", "pyflakes", "altgraph", "pefile"}

def licence_text(dist):
    texts = []
    for f in (dist.files or []):
        name = f.name.lower()
        if any(k in name for k in ("license", "licence", "copying", "notice")) and not name.endswith((".py", ".pyc")):
            try:
                texts.append(f"--- {f.name} ---\n" + Path(f.locate()).read_text(encoding="utf-8", errors="replace").strip())
            except (FileNotFoundError, OSError):
                pass
    return "\n\n".join(texts)

out = ["Racecraft: third-party notices",
       "",
       "The Racecraft download contains the third-party software listed below, each under its own licence.",
       "Where a package ships its licence text, the text follows its entry. Racecraft's own licence is in",
       "LICENSE. No race data is included in the download.",
       "",
       "=" * 78, "PART 1: Python packages in the app", "=" * 78, ""]
seen = set()
python_rows = []
for name in sorted(dists, key=str.lower):
    if name.lower() in SKIP or name.lower() in seen:
        continue
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        continue
    seen.add(name.lower())
    meta = dist.metadata
    lic = meta.get("License-Expression") or meta.get("License") or ""
    if not lic or len(lic) > 80:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = ", ".join(classifiers) or (lic[:80] + "..." if lic else "see the text below")
    python_rows.append((meta["Name"], dist.version, lic))
    out += [f"{meta['Name']} {dist.version}  ({lic})", meta.get("Home-page") or "", licence_text(dist), ""]

out += ["=" * 78, "PART 2: JavaScript packages in the interface", "=" * 78, ""]
lock = json.loads(Path("web/node_modules/.package-lock.json").read_text(encoding="utf-8"))
js_rows = []
for path, info in sorted(lock["packages"].items()):
    if not path or info.get("dev") or info.get("devOptional"):
        continue
    folder = Path("web") / path
    name = path.split("node_modules/")[-1]
    texts = []
    for f in sorted(folder.glob("*")):
        if f.is_file() and re.match(r"(?i)(licen[cs]e|copying|notice)", f.name):
            texts.append(f"--- {f.name} ---\n" + f.read_text(encoding="utf-8", errors="replace").strip())
    js_rows.append((name, info.get("version", ""), info.get("license", "")))
    out += [f"{name} {info.get('version', '')}  ({info.get('license', 'see the text below')})", "\n\n".join(texts), ""]

out += ["=" * 78, "PART 3: other", "=" * 78, "",
        "Python 3.11 runtime and its standard library: Python Software Foundation License.",
        "Microsoft Visual C++ runtime DLLs (VCRUNTIME140*.dll, api-ms-win-*.dll): redistributable under Microsoft's terms",
        "for the Visual C++ Redistributable.",
        "Fonts Titillium Web, Inter and JetBrains Mono (via Fontsource): SIL Open Font License 1.1, texts above.",
        ""]
Path("THIRD_PARTY_NOTICES.txt").write_text("\n".join(out).replace("\r\n", "\n"), encoding="utf-8")
print(len(python_rows), "Python packages;", len(js_rows), "JavaScript packages")
missing = [r for r in python_rows if r[2] in ("", "see the text below")]
print("Python without a stated licence:", missing)
print("JS without a stated licence:", [r for r in js_rows if not r[2]])
