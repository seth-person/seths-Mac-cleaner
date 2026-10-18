"""Builds a fake, messy home folder for tests and demos.

  python3 tests/fixture.py /tmp/fakehome   # then HOME=/tmp/fakehome python3 -m macclean
"""
from __future__ import annotations

import gzip
import os
import sys
import time
import zipfile
from pathlib import Path

DAY = 86400
ICLOUD = "Library/Mobile Documents/com~apple~CloudDocs"


def als_xml(refs, version="Ableton Live 12.1.5") -> bytes:
    """refs: list of (absolute path, relative path) for sample FileRefs."""
    parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<Ableton MajorVersion="5" Creator="{version}">'
             "<LiveSet><Tracks><AudioTrack><DeviceChain><MainSequencer><Sample><ArrangerAutomation><Events>"]
    for abs_path, rel in refs:
        parts.append(
            "<AudioClip><SampleRef><FileRef>"
            '<RelativePathType Value="3" />'
            f'<RelativePath Value="{rel}" />'
            f'<Path Value="{abs_path}" />'
            '<Type Value="1" /><LivePackName Value="" /><LivePackId Value="" />'
            "</FileRef>"
            # Where the sample originally came from - must be ignored.
            '<SourceContext><Value><BranchSourceContext><OriginalFileRef><FileRef>'
            '<RelativePath Value="" /><Path Value="/Users/nobody/Splice/never-there.wav" />'
            "</FileRef></OriginalFileRef></BranchSourceContext></Value></SourceContext>"
            "</SampleRef></AudioClip>")
    parts.append("</Events></ArrangerAutomation></Sample></MainSequencer></DeviceChain></AudioTrack>"
                 "</Tracks></LiveSet></Ableton>")
    return gzip.compress("".join(parts).encode())


def _age(path: Path, days: float) -> None:
    t = time.time() - days * DAY
    os.utime(path, (t, t))


def write(path: Path, data: bytes = b"", size: int = 0, age_days: float = 0, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if size:
        block = bytes((i * 7 + seed) % 256 for i in range(4096))
        with open(path, "wb") as f:
            for _ in range(size // 4096):
                f.write(block)
    else:
        path.write_bytes(data)
    if age_days:
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))
    return path


def preset_xml(refs, version="Ableton Live 12.4.6") -> bytes:
    """A rack/preset (.adg/.adv): refs are dicts {path, rel?, pack?, pack_id?}."""
    parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<Ableton MajorVersion="5" Creator="{version}">'
             "<GroupDevicePreset><Device><DrumGroupDevice><Branches>"]
    for r in refs:
        parts.append(
            "<SampleRef><FileRef>"
            f'<RelativePath Value="{r.get("rel", "")}" /><Path Value="{r["path"]}" />'
            f'<LivePackName Value="{r.get("pack", "")}" /><LivePackId Value="{r.get("pack_id", "")}" />'
            "</FileRef>"
            '<SourceContext><Value><BranchSourceContext><OriginalFileRef><FileRef>'
            '<Path Value="/Users/nobody/Downloads/where-it-came-from.wav" />'
            "</FileRef></OriginalFileRef></BranchSourceContext></Value></SourceContext></SampleRef>")
    parts.append("</Branches></DrumGroupDevice></Device></GroupDevicePreset></Ableton>")
    return gzip.compress("".join(parts).encode())


def library_cfg(home: Path, user_library_parent: Path, packs: list, places: list, template: str) -> bytes:
    slices = "".join(f'<LibrarySliceInfo Id="{i}" Path="{p}" DisplayName="{n}" UniqueId="[{u}](https://{u})" />'
                     for i, (n, p, u) in enumerate(packs))
    folders = "".join(f'<UserFolderInfo Id="{i}" Path="{p}" DisplayName="{os.path.basename(p)}" IconName="" />'
                      for i, p in enumerate(places))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Ableton MajorVersion="5" Creator="Ableton Live 12.4.6">'
            f'<ContentLibrary><UserLibrary><LibraryProject Id="2"><ProjectLocation />'
            f'<ProjectName Value="User Library" /><ProjectPath Value="{user_library_parent}" /></LibraryProject>'
            f'</UserLibrary><SliceInfoList>{slices}</SliceInfoList><UserFolderInfoList>{folders}</UserFolderInfoList>'
            f'<PreferredFactoryPacksInstallationPath Value="" /><DefaultTemplateSet Value="{template}" />'
            f'<SpliceDownloadFolderModeMember Value="UserLibrary" /><CustomSpliceDownloadPathMember Value="" />'
            f'</ContentLibrary></Ableton>').encode()


def project(root: Path, name: str, samples=(), external=(), missing=(), age_days=0, backups=0) -> Path:
    p = root / name
    (p / "Ableton Project Info").mkdir(parents=True, exist_ok=True)
    write(p / "Ableton Project Info" / "Project8_1.cfg", b"cfg")
    refs = []
    for s in samples:
        f = write(p / "Samples" / "Imported" / s, size=200_000, seed=hash(name + s) % 200)
        write(f.with_suffix(f.suffix + ".asd"), size=40_000, seed=3)
        refs.append((str(f), f"Samples/Imported/{s}"))
    for e in external:
        refs.append((str(e), ""))
    for m in missing:
        refs.append((f"/Users/seth/Old Samples/{m}", f"Samples/Imported/{m}"))
    set_name = name.replace(" Project", "")
    write(p / f"{set_name}.als", als_xml(refs), age_days=age_days)
    for i in range(backups):
        write(p / "Backup" / f"{set_name} [2026-0{i + 1}-01 120000].als", als_xml(refs), age_days=age_days + 10)
        write(p / "Backup" / f"pad{i}.bin", size=3_000_000, seed=i)
    return p


def build(home: Path) -> Path:
    home = Path(home)
    dl, desk, cloud = home / "Downloads", home / "Desktop", home / ICLOUD
    for d in (dl, desk, cloud, home / "Documents", home / "Music"):
        d.mkdir(parents=True, exist_ok=True)

    # Downloads: the usual pile.
    write(dl / "Serum_x64_installer.dmg", size=3_000_000, age_days=40, seed=1)
    write(dl / "Ozone 11.pkg", size=2_000_000, age_days=1, seed=2)
    for i in range(4):
        write(dl / "Drum Pack Vol 2" / f"kick_{i}.wav", size=120_000, age_days=20, seed=10 + i)
    # The zip it came from: identical contents, so it's provably redundant.
    with zipfile.ZipFile(dl / "Drum Pack Vol 2.zip", "w") as zf:
        for i in range(4):
            zf.write(dl / "Drum Pack Vol 2" / f"kick_{i}.wav", f"Drum Pack Vol 2/kick_{i}.wav")
    _age(dl / "Drum Pack Vol 2.zip", 20)
    write(dl / "SomeApp-2.1.dmg", size=2_500_000, age_days=40, seed=3)
    # An installer folder that also holds a license key: never trash the folder.
    write(dl / "Installer Bundle" / "Setup.pkg", size=3_000_000, age_days=40, seed=14)
    write(dl / "Installer Bundle" / "LICENSE KEY.txt", b"ABCD-1234", age_days=40)
    write(dl / "report copy.pdf", b"%PDF-1.7 " + bytes(1_200_000), age_days=10)
    write(dl / "final mix v3.wav", size=1_200_000, age_days=5, seed=5)
    write(dl / "Screenshot 2026-07-01 at 10.00.00.png", size=200_000, age_days=90, seed=6)
    write(dl / "lease agreement.pdf", b"%PDF-1.7 fake", age_days=60)
    write(dl / "mystery_file", b"%PDF-1.4 no extension", age_days=8)
    write(dl / "big-video.crdownload", size=500_000, age_days=6, seed=7)
    write(dl / "Beat idea.als", als_xml([]), age_days=12)
    shared = write(dl / "vocal chop.wav", size=1_100_000, age_days=30, seed=8)
    project(dl, "Old Song Project", samples=["pad.wav"], external=[shared], age_days=100)

    # Factory Packs, and Live's settings listing them (like a real Library.cfg).
    packs_dir = home / "Music" / "Ableton" / "Factory Packs"
    glow = write(packs_dir / "Drive and Glow" / "Samples" / "Glow Hit.wav", size=50_000, seed=20)
    saw = write(packs_dir / "Synth Essentials" / "Samples" / "Saw.wav", size=50_000, seed=21)
    lfo = write(packs_dir / "Max for Live Essentials" / "Devices" / "LFO.amxd", b"ampf\x00fake max device")
    c3 = write(packs_dir / "Grand Piano" / "Samples" / "C3.wav", size=50_000, seed=22)
    kick = write(packs_dir / "Drum Booth" / "Samples" / "Kick.wav", size=50_000, seed=23)
    # A preset inside a Pack only uses that Pack: it says nothing about whether *you* use it.
    write(packs_dir / "Grand Piano" / "Presets" / "Grand Piano.adv", preset_xml([{"path": str(c3), "pack": "Grand Piano"}]))
    # Racks in the User Library (in iCloud, like yours) that load Pack samples and a Max device.
    ul = cloud / "Active Storage" / "User Library"
    write(ul / "Presets" / "Instruments" / "Drum Rack" / "[dnksaus] Stock Drum Selecta (Suite).adg",
          preset_xml([{"path": str(glow), "pack": "Drive and Glow", "pack_id": "www.ableton.com/253"},
                      {"path": str(lfo), "pack": "Max for Live Essentials"}]))
    oneshot = write(dl / "bass one-shot.wav", size=60_000, age_days=40, seed=24)
    write(ul / "Presets" / "Instruments" / "Instrument Rack" / "{dnksaus} Bass Preset Selecta (CPU INTENSIVE).adg",
          preset_xml([{"path": str(saw), "pack": "Synth Essentials"}, {"path": str(oneshot)},
                      {"path": str(packs_dir / "Lost Pack" / "Samples" / "Gone.wav"), "pack": "Lost Pack"}]))
    write(cloud / "Active Storage" / "rekordbox" / "master.db", b"rekordbox database")
    listed = ["Drive and Glow", "Synth Essentials", "Max for Live Essentials", "Grand Piano", "Drum Booth", "Lost Pack"]
    write(home / "Library" / "Preferences" / "Ableton" / "Live 12.4.6" / "Library.cfg",
          library_cfg(home, cloud / "Active Storage",
                      [(n, packs_dir / n, f"www.ableton.com/{i}") for i, n in enumerate(listed)],
                      [cloud / "Active Storage", desk / "ASYM Music"],
                      str(home / "Active Storage" / "User Library" / "Templates" / "Default.als")))
    write(home / "Library" / "Preferences" / "Ableton" / "Live 11.3.13" / "Library.cfg", b"<Ableton />")  # older Live

    # Desktop: what's active right now.
    project(desk, "Current Song Project", samples=["bass.wav", "vox.wav"], external=[kick], age_days=1, backups=2)
    write(desk / "notes.txt", b"todo", age_days=2)
    write(desk / "cover art.png", size=300_000, age_days=3, seed=9)

    # iCloud: the organised side.
    abl = cloud / "Ableton Projects"
    project(abl / "Finished", "Song A Project", samples=["lead.wav"], age_days=400)
    project(abl, "Song B Project", samples=["drums.wav"], missing=["gone.wav"], age_days=200)
    write(cloud / "Documents" / "taxes 2025.pdf", b"%PDF-1.7 taxes", age_days=200)
    write(cloud / "Documents" / "report.pdf", b"%PDF-1.7 " + bytes(1_200_000), age_days=30)
    write(cloud / "Music" / "Bounces" / "2025" / "song a master.wav", size=1_100_000, age_days=300, seed=8)

    # Elsewhere: a stray copy of a project and a big old file.
    project(home / "Music" / "Ableton" / "Projects", "Song A Project", samples=["lead.wav"], age_days=420)
    write(home / "Documents" / "old export.mov", size=2_000_000, age_days=400, seed=12)

    # Library: caches.
    write(home / "Library" / "Caches" / "com.spotify.client" / "Data" / "blob", size=21_000_000, seed=13)
    write(home / "Library" / "Caches" / "com.google.Chrome" / "Cache_Data" / "blob", size=21_000_000, seed=15)
    write(home / "Library" / "Caches" / "tiny" / "x", b"x")
    # A sound library that duplicates a sample on purpose: never a "duplicate".
    write(home / "Music" / "Ableton" / "User Library" / "Samples" / "chop.wav", size=1_100_000, seed=8)
    return home


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
