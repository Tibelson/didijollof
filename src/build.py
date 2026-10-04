#!/usr/bin/env python3
"""
Rebuild prototype/didi-jollof.html from didi.template.html.

The template carries placeholders instead of the actual binary payloads so it
stays readable and diffable. This script inlines them:

    __GABARITO__ / __GEIST__      <- fonts.json   (base64 woff2, latin subset)
    __PHOTO_JOLLOF__ etc.         <- photos.json  (base64 jpeg, 300x300)

Everything ends up inside one HTML file with no external requests, which is
what lets it run offline and be published as an artifact.

    python3 build.py

To swap in better photography: replace the files in ../photos/, then run
    python3 build.py --rebuild-photos
which re-encodes photos.json from those jpgs before building.
"""
import base64, json, pathlib, re, sys

HERE = pathlib.Path(__file__).parent
OUT = HERE.parent / "prototype" / "didi-jollof.html"
DISHES = ["jollof", "fried", "waakye", "chicken"]


def rebuild_photos():
    photos = {}
    for dish in DISHES:
        jpg = HERE.parent / "photos" / f"{dish}.jpg"
        if not jpg.exists():
            sys.exit(f"missing {jpg} — every dish needs a photo")
        photos[dish] = base64.b64encode(jpg.read_bytes()).decode()
        print(f"  encoded {dish}.jpg  {jpg.stat().st_size // 1024} KB")
    (HERE / "photos.json").write_text(json.dumps(photos))
    return photos


def main():
    if "--rebuild-photos" in sys.argv:
        photos = rebuild_photos()
    else:
        photos = json.loads((HERE / "photos.json").read_text())

    html = (HERE / "didi.template.html").read_text(encoding="utf-8")
    fonts = json.loads((HERE / "fonts.json").read_text())

    html = html.replace("__GABARITO__", fonts["gabarito"]).replace("__GEIST__", fonts["geist"])
    for dish, b64 in photos.items():
        html = html.replace(f"__PHOTO_{dish.upper()}__", b64)

    leftover = re.findall(r"__[A-Z_]+__", html)
    if leftover:
        sys.exit(f"unsubstituted placeholders: {sorted(set(leftover))}")
    if re.search(r'(?:src|href)\s*=\s*["\']https?://', html):
        sys.exit("external reference found — the page must stay self-contained")

    OUT.write_text(html, encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(HERE.parent)}  {len(html.encode()) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
