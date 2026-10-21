#!/bin/bash
# Remote build for the DigitalOcean Python runtime: dependencies go into a
# virtualenv named "virtualenv" (the runtime adds it to sys.path), and a
# static QuickJS binary is fetched for yt-dlp's YouTube JavaScript challenges.
set -euo pipefail

virtualenv --without-pip virtualenv
pip install -r requirements.txt --target virtualenv/lib/python3.12/site-packages

python3 - <<'EOF'
import hashlib, os, urllib.request

URL = "https://github.com/quickjs-ng/quickjs/releases/download/v0.17.0/qjs-linux-x86_64"
SHA256 = "0bfc02511a9f549c28b53880d988fc7cd5d361e90c5e8afdfcd7dc6774ceace5"

data = urllib.request.urlopen(URL, timeout=60).read()
digest = hashlib.sha256(data).hexdigest()
if digest != SHA256:
    raise SystemExit(f"qjs checksum mismatch: {digest}")
os.makedirs("bin", exist_ok=True)
with open("bin/qjs", "wb") as f:
    f.write(data)
os.chmod("bin/qjs", 0o755)
EOF
