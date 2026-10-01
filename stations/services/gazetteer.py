import csv
import io
import re
import zipfile

# Census place names end in a type word ("Big Cabin town", "Tulsa city"); the CSV doesn't have it.
TYPE_SUFFIX = re.compile(
    r"\s+(city and borough|consolidated government|metropolitan government|unified government|"
    r"urban county|municipality|city|town|village|borough|cdp|township|plantation|comunidad|zona urbana)"
    r"(\s*\(balance\))?$",
    re.I,
)
ABBREVIATIONS = [(r"\bst\b", "saint"), (r"\bste\b", "sainte"), (r"\bft\b", "fort"), (r"\bmt\b", "mount")]


def normalize(name):
    name = re.sub(r"[.'’]", "", name.lower().strip()).replace("-", " ")
    for pattern, full in ABBREVIATIONS:
        name = re.sub(pattern, full, name)
    return re.sub(r"\s+", " ", name)


def clean_place_name(raw):
    name = raw.strip()
    previous = None
    while previous != name:  # some names carry two suffixes
        previous, name = name, TYPE_SUFFIX.sub("", name)
    return normalize(name)


def load_gazetteer(zip_bytes=None, path=None):
    """{(state, normalized name): (lat, lon)} from the Census places zip.

    If two places in a state share a name, the one with more land area wins.
    """
    if path:
        with open(path, "rb") as fh:
            zip_bytes = fh.read()
    if zip_bytes is None:
        raise ValueError("need zip_bytes or path")

    best, aliases = {}, {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        reader = csv.DictReader(io.TextIOWrapper(zf.open(member), encoding="utf-8"), delimiter="\t")
        for row in reader:
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}  # header/trailing spaces
            state = row["USPS"]
            area = float(row.get("ALAND") or 0)
            value = (area, float(row["INTPTLAT"]), float(row["INTPTLONG"]))
            key = (state, clean_place_name(row["NAME"]))
            if key not in best or area > best[key][0]:
                best[key] = value
            # Consolidated cities are listed as "Nashville-Davidson ..." or "Louisville/Jefferson
            # County ...", but fuel lists just say "Nashville". Remember the first part too.
            first = re.split(r"[-/]", row["NAME"], maxsplit=1)[0]
            if first != row["NAME"]:
                alias = (state, clean_place_name(first))
                if alias not in aliases or area > aliases[alias][0]:
                    aliases[alias] = value
    for key, value in aliases.items():
        best.setdefault(key, value)  # a real place with that exact name always wins
    return {k: (lat, lon) for k, (_, lat, lon) in best.items()}
