"""
Unturned Workshop Asset Catalog Generator
-----------------------------------------
Scans local Unturned Workshop mod folders (each folder named after its
numeric Workshop ID), parses every .dat asset file, and produces a
single consolidated `data.json` catalog.

Usage:
    python build_catalog.py

Reads:
    ./mods.txt          (optional, one Workshop ID per line)
    ./<workshop_id>/    (one folder per mod, name = workshop ID)

Writes:
    ./data.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HERE        = Path.cwd()          # the directory the script is launched from
MODS_FILE   = HERE / "mods.txt"
OUTPUT_FILE = HERE / "data.json"

# Fallback list used only when mods.txt is missing/empty AND no numbered
# folders are found. Folder-name IDs are detected automatically, so this
# can normally stay empty.
HARDCODED_MOD_IDS: List[str] = [
    # "2969995088",
]

# ---------------------------------------------------------------------------
# Type -> Category classification
# ---------------------------------------------------------------------------

ITEM_TYPES = {
    "Gun", "Magazine", "Melee", "Food", "Water", "Medical", "Clothing",
    "Backpack", "Sight", "Barrel", "Grip", "Tactical", "Ammo", "Fuel",
    "Tool", "Map", "Key", "Box", "Throwable", "Cloud", "Compass",
    "Fisher", "Grower", "Refill", "Repair", "Task", "Filter", "Charge",
    "Detonator", "Oil", "Paint", "Parachute", "Sentry",
}
VEHICLE_TYPES   = {"Vehicle"}
BARRICADE_TYPES = {
    "Barricade", "Storage", "Structure", "Door", "Bed", "Sign", "Farm",
    "Generator", "Beacon", "Library", "StereoTrack", "Tank", "Trap",
}
OBJECT_TYPES    = {"Object", "Resource", "NPC", "Spawn"}


def categorize(type_str: str) -> str:
    t = (type_str or "").strip()
    if not t:
        return "Other"
    if t in VEHICLE_TYPES:
        return "Vehicles"
    if t in ITEM_TYPES:
        return "Items"
    if t in BARRICADE_TYPES:
        return "Barricades"
    if t in OBJECT_TYPES:
        return "Objects"
    low = t.lower()
    if "vehicle" in low:
        return "Vehicles"
    if low.startswith(("object", "resource", "npc", "spawn")):
        return "Objects"
    if low in {"barricade", "structure", "storage", "door", "sign",
               "bed", "farm", "generator", "beacon", "library", "trap"}:
        return "Barricades"
    return "Other"


# ---------------------------------------------------------------------------
# .dat parser (handles flat keys and Metadata { ... } blocks)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "{}":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 1
            tokens.append(text[i + 1:j])
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in '{}"':
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def _parse_block(tokens: List[str], i: int):
    result: Dict[str, Any] = {}
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "}":
            return result, i + 1
        if i + 1 < n and tokens[i + 1] == "{":
            sub, i = _parse_block(tokens, i + 2)
            result[tok] = sub
        elif i + 1 < n:
            result[tok] = tokens[i + 1]
            i += 2
        else:
            result[tok] = ""
            i += 1
    return result, i


def parse_dat(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    tokens = _tokenize(text)
    flat, _ = _parse_block(tokens, 0)

    merged: Dict[str, Any] = {}
    for k, v in flat.items():
        if isinstance(v, dict):
            # Unturned wraps most fields inside a `Metadata { }` block.
            if k.lower() == "metadata":
                for mk, mv in v.items():
                    if not isinstance(mv, dict):
                        merged[mk] = mv
            # other nested blocks (Blueprints, etc.) are intentionally skipped
        else:
            merged[k] = v
    return merged


def get_field(data: Dict[str, Any], *names: str, default: str = "") -> Any:
    for name in names:
        if name in data:
            return data[name]
    lower = {k.lower(): v for k, v in data.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return default


# ---------------------------------------------------------------------------
# Asset extraction
# ---------------------------------------------------------------------------

# These are pulled out to the top level of the asset object and therefore
# excluded from `properties`. Note: Health is intentionally NOT excluded so
# that it also appears under `properties`, matching the example schema.
TOP_LEVEL_EXCLUDE = {"Type", "ID", "GUID", "Name", "Rarity", "Useable",
                     "Build", "Icon"}


def extract_asset(dat_path: Path, mod_root: Path, mod_name: str,
                  mod_id: str, translations: Dict[str, str]) -> Dict[str, Any]:
    data = parse_dat(dat_path)

    type_str = str(get_field(data, "Type", default="") or "").strip()
    guid     = str(get_field(data, "GUID", default="") or "").strip()

    # Human-readable name: .dat `Name` field -> English.dat -> filename stem
    name = str(get_field(data, "Name", default="") or "").strip()
    if not name and guid:
        name = translations.get(guid.lower(), "")
    if not name:
        name = dat_path.stem

    rel_path = dat_path.relative_to(mod_root).as_posix()

    properties: Dict[str, str] = {}
    for k, v in data.items():
        if k in TOP_LEVEL_EXCLUDE:
            continue
        if isinstance(v, (dict, list)):
            continue
        v = str(v).strip()
        if v == "":
            continue
        properties[k] = v

    return {
        "name":          name,
        "type":          type_str,
        "category":      categorize(type_str),
        "guid":          guid,
        "id":            str(get_field(data, "ID", default="") or ""),
        "rarity":        str(get_field(data, "Rarity", default="Common") or "Common"),
        "useable":       str(get_field(data, "Useable", default=type_str) or type_str),
        "build":         str(get_field(data, "Build", default="") or ""),
        "health":        str(get_field(data, "Health", default="") or ""),
        "icon":          str(get_field(data, "Icon", default="") or ""),
        "datPath":       rel_path,
        "mod":           mod_name,
        "modWorkshopId": mod_id,
        "properties":    properties,
    }


# ---------------------------------------------------------------------------
# Mod metadata helpers
# ---------------------------------------------------------------------------

def load_translations(mod_root: Path) -> Dict[str, str]:
    """Return {guid_lower: display_name} parsed from English.dat if present."""
    translations: Dict[str, str] = {}
    for fname in ("English.dat", "english.dat", "English.translation"):
        path = mod_root / fname
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            line = re.sub(r"//.*$", "", line).strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([0-9a-fA-F\-]+)\.Name\s+"?(.+?)"?\s*$', line)
            if m:
                translations[m.group(1).lower()] = m.group(2)
        break
    return translations


def get_mod_name(mod_root: Path) -> str:
    """Best-effort lookup of the mod's display name."""
    for meta_name in ("mod.meta", "mod.info", ".meta"):
        p = mod_root / meta_name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("Name", "name", "Title", "title"):
                    if key in data:
                        return str(data[key])
        except Exception:
            pass
        for line in text.splitlines():
            m = re.match(r'\s*"?(?:Name|name|Title|title)"?\s*[:=]?\s*(.+?)\s*,?\s*$',
                         line)
            if m:
                return m.group(1).strip().strip('"').strip(",").strip()
    return mod_root.name


# ---------------------------------------------------------------------------
# Mod scanning
# ---------------------------------------------------------------------------

def scan_mod(mod_dir: Path) -> Dict[str, Any]:
    mod_id   = mod_dir.name
    mod_name = get_mod_name(mod_dir)
    translations = load_translations(mod_dir)

    print(f"[scan] {mod_id} ({mod_name})")

    assets: List[Dict[str, Any]] = []
    counts = {"Items": 0, "Vehicles": 0, "Barricades": 0, "Objects": 0, "Other": 0}
    skipped: List[tuple] = []

    for dat_path in sorted(mod_dir.rglob("*.dat")):
        if dat_path.name.lower() in {"english.dat", "mod.dat"}:
            continue
        try:
            asset = extract_asset(dat_path, mod_dir, mod_name, mod_id, translations)
        except Exception as e:
            skipped.append((dat_path.relative_to(mod_dir).as_posix(),
                            f"parse error: {e}"))
            continue
        if not asset["type"]:
            skipped.append((dat_path.relative_to(mod_dir).as_posix(),
                            "missing Type field"))
            continue
        assets.append(asset)
        counts[asset["category"]] = counts.get(asset["category"], 0) + 1

    print(f"[scan]   -> {len(assets)} assets ({counts})")
    if skipped:
        for path, reason in skipped[:5]:
            print(f"[scan]   skipped: {path} ({reason})")
        if len(skipped) > 5:
            print(f"[scan]   ... and {len(skipped) - 5} more skipped")

    return {
        "name":       mod_name,
        "workshopId": mod_id,
        "steamUrl":   f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}",
        "counts":     counts,
        "assets":     assets,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def read_mod_ids() -> List[str]:
    ids: List[str] = []

    if MODS_FILE.exists():
        for line in MODS_FILE.read_text(encoding="utf-8-sig",
                                        errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r"(\d+)", line)
            if m:
                ids.append(m.group(1))

    if not ids:
        ids.extend(HARDCODED_MOD_IDS)

    # Auto-detect folders whose name is a numeric Workshop ID
    for entry in HERE.iterdir():
        if entry.is_dir() and entry.name.isdigit() and entry.name not in ids:
            ids.append(entry.name)

    return ids


def main() -> None:
    print("[main] Unturned Workshop asset catalog builder")
    print(f"[main] Working directory: {HERE}")

    mod_ids = read_mod_ids()
    if not mod_ids:
        print("[main] No mod IDs found. Create a mods.txt with one ID per line,")
        print("[main] or place workshop folders (named by ID) next to this script.")
        sys.exit(1)

    print(f"[main] Discovered {len(mod_ids)} mod ID(s): {', '.join(mod_ids)}")

    catalog: List[Dict[str, Any]] = []
    for mid in mod_ids:
        mod_dir = HERE / mid
        if not mod_dir.is_dir():
            print(f"[scan] {mid}: folder not found, skipping")
            continue
        try:
            catalog.append(scan_mod(mod_dir))
        except Exception as e:
            print(f"[scan] {mid}: unexpected error: {e}")

    OUTPUT_FILE.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    total = sum(len(m["assets"]) for m in catalog)
    print(f"[main] Wrote {OUTPUT_FILE.name}: "
          f"{len(catalog)} mod(s), {total} asset(s).")


if __name__ == "__main__":
    main()
