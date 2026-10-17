"""Work out what kind of thing a file or folder is."""
from __future__ import annotations

import os
from pathlib import Path

# Display order is also the chart colour order (see static/app.js CATEGORY_COLORS).
CATEGORIES = ["audio", "ableton", "video", "image", "document", "app", "archive", "code",
              "installer", "plugin", "other"]

_EXT = {
    "audio": "wav aif aiff mp3 flac m4a aac ogg opus alac caf mid midi rx rex rx2 wma",
    "ableton": "als alc adg adv alp ams agr asd amxd",
    "video": "mov mp4 m4v mkv avi webm mts wmv flv prproj fcpbundle",
    "image": "png jpg jpeg gif heic heif webp tif tiff bmp raw cr2 cr3 nef arw dng svg psd ai sketch fig xcf ico icns",
    "document": "pdf doc docx pages rtf txt md odt xls xlsx numbers csv key ppt pptx epub mobi tex",
    "archive": "zip rar 7z tar gz tgz bz2 xz zst sit sitx",
    "installer": "dmg pkg mpkg iso",
    "code": "py js ts tsx jsx json yaml yml toml sh c h cpp swift go rs java rb php html css ipynb sql",
    "plugin": "vst vst3 component aaxplugin clap",
    "app": "app",
}
EXT_CATEGORY = {"." + e: cat for cat, exts in _EXT.items() for e in exts.split()}

# Directory suffixes macOS treats as a single item ("packages"). We size them
# but never descend into them for the explorer.
PACKAGE_SUFFIXES = {
    ".app", ".bundle", ".framework", ".plugin", ".kext", ".photoslibrary", ".musiclibrary",
    ".logicx", ".band", ".fcpbundle", ".imovielibrary", ".tvlibrary", ".xcodeproj",
    ".xcworkspace", ".vst", ".vst3", ".component", ".aaxplugin", ".clap", ".pages",
    ".numbers", ".key", ".rtfd", ".sparsebundle", ".xcarchive", ".lrdata", ".lrlibrary",
    ".prproj", ".sketch", ".playground", ".mdimporter", ".qlgenerator", ".saver", ".prefPane",
}

PARTIAL_DOWNLOAD_EXTS = {".crdownload", ".download", ".part", ".partial", ".opdownload"}

_MAGIC = [
    (b"%PDF", "document"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"PK\x03\x04", "archive"),
    (b"\x1f\x8b", "archive"),
    (b"7z\xbc\xaf", "archive"),
    (b"Rar!", "archive"),
    (b"ID3", "audio"),
    (b"fLaC", "audio"),
    (b"OggS", "audio"),
    (b"MThd", "audio"),
    (b"\xcf\xfa\xed\xfe", "app"),  # Mach-O 64-bit executable
    (b"xar!", "installer"),        # .pkg
]


def category_for_name(name: str, is_dir: bool = False) -> str:
    ext = Path(name).suffix.lower()
    if is_dir and ext not in PACKAGE_SUFFIXES:
        return "folder"
    return EXT_CATEGORY.get(ext, "other")


def sniff(path: str) -> str:
    """Guess a category from the first bytes of a file (for odd/missing extensions)."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "other"
    for magic, cat in _MAGIC:
        if head.startswith(magic):
            return cat
    if head[:4] == b"RIFF" and head[8:12] in (b"WAVE", b"AVI "):
        return "audio" if head[8:12] == b"WAVE" else "video"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "audio"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand.startswith(b"M4A"):
            return "audio"
        if brand.startswith((b"heic", b"heix", b"mif1")):
            return "image"
        return "video"
    if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3":
        return "audio"
    return "other"


def classify_file(path: str) -> str:
    cat = category_for_name(path)
    if cat == "other":
        cat = sniff(path)
    return cat


def is_ableton_project(path: str) -> bool:
    return os.path.isdir(os.path.join(path, "Ableton Project Info"))


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000.0
    return f"{n:.1f} TB"
