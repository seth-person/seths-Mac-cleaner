"""Build the release files into dist/ (used by the Release workflow).

  python3 scripts/build_release.py [outdir]

Produces mac-cleaner-<version>.tar.gz, SHA256SUMS, install.sh and notes.md
(this version's section of CHANGELOG.md).
"""
import hashlib
import re
import shutil
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import macclean  # noqa: E402

INCLUDE = ["macclean", "install.sh", "README.md", "CHANGELOG.md"]


def notes(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no '## {version}' section")
    return m.group(1).strip() + "\n"


def build(out: Path) -> Path:
    version = macclean.__version__
    out.mkdir(parents=True, exist_ok=True)
    name = f"mac-cleaner-{version}.tar.gz"

    def clean(ti):
        if "__pycache__" in ti.name or ti.name.endswith(".pyc"):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    with tarfile.open(out / name, "w:gz") as tf:
        for item in INCLUDE:
            tf.add(ROOT / item, arcname=item, filter=clean)
    digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(f"{digest}  {name}\n")
    shutil.copy(ROOT / "install.sh", out / "install.sh")
    (out / "notes.md").write_text(notes(version))
    return out / name


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist")))
