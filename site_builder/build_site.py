"""Rebuild the one-file website (docs/site/explorer.html) from the pipeline outputs.

Run after `make all`:   python site_builder/build_site.py
Needs: pillow (pip install pillow).  Everything is embedded in one HTML file.
"""
import base64, glob, os, re, subprocess, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(HERE)
os.makedirs("project", exist_ok=True)
os.makedirs("img", exist_ok=True)

# 1. charts -> compressed jpg
for f in sorted(glob.glob(os.path.join(ROOT, "outputs", "figures", "*.png"))):
    im = Image.open(f).convert("RGB")
    if im.width > 1400:
        im = im.resize((1400, int(im.height * 1400 / im.width)))
    im.save("img/" + os.path.basename(f)[:-4] + ".jpg", quality=86, optimize=True)

# 2. tables -> data.json / vars.json, then the page
for step in ("export_site.py", "gen2.py", "gen3.py", "build_standalone.py"):
    subprocess.run([sys.executable, step], check=True)

# 3. embed the images so the page is a single file
html = open("standalone/index.html").read()
def emb(m):
    return "data:image/jpeg;base64," + base64.b64encode(open("standalone/" + m.group(0), "rb").read()).decode()
html = re.sub(r"img/[0-9a-z_]+\.jpg", emb, html)
out = os.path.join(ROOT, "docs", "site", "explorer.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w").write(html)
print("wrote", out, len(html), "bytes")
