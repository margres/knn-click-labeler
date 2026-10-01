"""
Shared logic for the KNN click labeler (no GUI imports).

Used by both the desktop app (knn_click_labeler.py, Tkinter) and the
JupyterLab widget (knn_labeler_jupyter.py, ipywidgets).
"""
import os
import json
import csv
from datetime import datetime, timezone

import numpy as np
from PIL import Image


# ============================================================
# GRADES — edit here to change what each click assigns
# ============================================================
# Clicking a tile walks through this list: 1st click -> CLICK_GRADES[0],
# 2nd click -> CLICK_GRADES[1], ... One more click after the last clears it.
# You can reorder, rename, add or remove grades; just keep GRADE_COLORS in sync.
CLICK_GRADES = ["C", "B", "A"]

GRADE_COLORS = {
    "A": "#2ecc71",  # green
    "B": "#f39c12",  # orange
    "C": "#e74c3c",  # red
}

# Grade given to rows of old selected_neighbors.csv files that have no grade column
LEGACY_GRADE = "A"


def next_grade(current):
    """Grade after one more click on a tile currently graded `current` (None = ungraded)."""
    if current not in CLICK_GRADES:
        return CLICK_GRADES[0]
    i = CLICK_GRADES.index(current) + 1
    return CLICK_GRADES[i] if i < len(CLICK_GRADES) else None


def legend_lines():
    """['1 click -> C', '2 clicks -> B', ...] for display."""
    out = []
    for i, g in enumerate(CLICK_GRADES, start=1):
        out.append(f"{i} click{'s' if i > 1 else ''} → {g}")
    n = len(CLICK_GRADES) + 1
    out.append(f"{n} clicks → clear")
    return out


# ============================================================
# Data files (all relative to one data folder)
# ============================================================
IMAGES_SUBDIR = "knn_cutouts"                        # contains <ID>.png
NEIGHBORS_FILES = ("neighbors_A.json", "neighbors_B_C.json")
SELECTED_FILE = "selected_neighbors.csv"             # output: graded neighbors
REVIEWED_FILE = "reviewed_queries.csv"               # output: queries marked Done
QUERIES_FILE = "final_grade.csv"                     # optional query ordering
METADATA_FILE = "final_grade.csv"                    # per-object metadata
METADATA_ID_COL = "ID"

DEFAULT_VMIN = -10
DEFAULT_VMAX = 160


class DataPaths:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(os.path.expanduser(data_dir))
        self.images = os.path.join(self.data_dir, IMAGES_SUBDIR)
        self.neighbors = tuple(os.path.join(self.data_dir, p) for p in NEIGHBORS_FILES)
        self.selected = os.path.join(self.data_dir, SELECTED_FILE)
        self.reviewed = os.path.join(self.data_dir, REVIEWED_FILE)
        self.queries = os.path.join(self.data_dir, QUERIES_FILE)
        self.metadata = os.path.join(self.data_dir, METADATA_FILE)

    def check(self):
        """Return a list of human-readable problems (empty if all good)."""
        problems = []
        if not any(os.path.exists(p) for p in self.neighbors):
            problems.append("No neighbors JSON found (looked for: "
                            + ", ".join(self.neighbors) + ")")
        if not os.path.isdir(self.images):
            problems.append(f"Could not find cutouts folder: {self.images}")
        return problems


# ----------------------------
# Persistence
# ----------------------------
def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def load_selected(path):
    """
    Returns dict[query_id] -> dict[neighbor_id] -> grade.
    Backward compatible with old files that only had neighbor_id (treated as LEGACY_GRADE).
    """
    selected = {}
    if os.path.exists(path):
        with open(path, "r", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                q = (r.get("query_id") or "").strip()
                n = (r.get("neighbor_id") or "").strip()
                g = (r.get("grade") or "").strip().upper()
                if not q or not n:
                    continue
                if g not in GRADE_COLORS:
                    g = LEGACY_GRADE
                selected.setdefault(q, {})[n] = g
    return selected


def save_selected(path, selected):
    ts = _now()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["query_id", "neighbor_id", "grade", "timestamp_utc"])
        for q, neigh_map in selected.items():
            for n in sorted(neigh_map.keys()):
                w.writerow([q, n, neigh_map[n], ts])


def load_reviewed(path):
    reviewed = set()
    if os.path.exists(path):
        with open(path, "r", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                q = (r.get("query_id") or "").strip()
                if q:
                    reviewed.add(q)
    return reviewed


def save_reviewed(path, reviewed):
    ts = _now()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["query_id", "timestamp_utc"])
        for q in sorted(reviewed):
            w.writerow([q, ts])


# ----------------------------
# CSV loaders
# ----------------------------
def load_queries_to_plot(csv_path, neighbors_dict, col_candidates=("ID",)):
    if not os.path.exists(csv_path):
        return None

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return None

        norm_fieldnames = [("" if fn is None else str(fn).strip()) for fn in reader.fieldnames]
        reader.fieldnames = norm_fieldnames

        col = None
        for c in col_candidates:
            c = str(c).strip()
            if c in norm_fieldnames:
                col = c
                break
        if col is None:
            return None

        neighbors_keys = set(str(k).strip() for k in neighbors_dict.keys())
        queries, seen = [], set()

        for row in reader:
            q = (row.get(col) or "").strip()
            if not q:
                continue
            q = q.replace(";", " ")
            if q in neighbors_keys and q not in seen:
                queries.append(q)
                seen.add(q)

    return queries


def load_metadata(csv_path, id_col=METADATA_ID_COL):
    meta = {}
    if not os.path.exists(csv_path):
        return meta

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return meta

        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            r = {k.strip(): (v.strip() if isinstance(v, str) else v)
                 for k, v in row.items()}
            oid = r.get(id_col, "")
            if not oid:
                continue

            meta[str(oid)] = {
                "final_grade": r.get("final_grade", ""),
                "origin": r.get("origin", ""),
                "final_score": r.get("final_score", ""),
            }
    return meta


def meta_str(meta_dict, oid):
    m = meta_dict.get(oid)
    if not m:
        return "final_grade=? | origin=?"
    fs = m.get("final_grade") or "?"
    org = m.get("origin") or "?"
    return f"final_grade={fs} | origin={org}"


# ----------------------------
# Neighbors JSON loader (merge)
# ----------------------------
def load_neighbors_json(*json_paths):
    neighbors = {}
    for path in json_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for k, v in data.items():
            k = str(k).strip()
            v = [str(x).strip() for x in v]
            if k in neighbors:
                neighbors[k] = list(dict.fromkeys(neighbors[k] + v))
            else:
                neighbors[k] = v
    return neighbors


# ----------------------------
# Image loading + scaling
# ----------------------------
def scale_image(img, vmin=None, vmax=None):
    """Linearly map [vmin, vmax] to [0, 1] (clipped). Works with 2D or 3D arrays."""
    img = np.asarray(img).astype(float)
    if vmin is None:
        vmin = img.min()
    if vmax is None:
        vmax = img.max()
    return np.clip((img - vmin) / (vmax - vmin + 1e-12), 0, 1)


def load_scaled_pil(images_dir, id_, size, vmin=DEFAULT_VMIN, vmax=DEFAULT_VMAX):
    """Load <images_dir>/<id_>.png, resize to size x size, apply vmin/vmax scaling."""
    path = os.path.join(images_dir, f"{id_}.png")
    if not os.path.exists(path):
        return Image.new("RGB", (size, size), (40, 40, 40))
    img = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    norm = scale_image(img, vmin=float(vmin), vmax=float(vmax))
    return Image.fromarray((norm * 255.0).clip(0, 255).astype(np.uint8), mode="RGB")


# ----------------------------
# Session state shared by both front-ends
# ----------------------------
class LabelingSession:
    """Loads all inputs + saved progress for one data folder."""

    def __init__(self, data_dir):
        self.paths = DataPaths(data_dir)
        self.neighbors = load_neighbors_json(*self.paths.neighbors)
        self.meta = load_metadata(self.paths.metadata)
        override = load_queries_to_plot(self.paths.queries, self.neighbors)
        self.queries = override if override else list(self.neighbors.keys())
        self.selected = load_selected(self.paths.selected)   # dict[q][nid] = grade
        self.reviewed = load_reviewed(self.paths.reviewed)

    def save(self):
        save_selected(self.paths.selected, self.selected)
        save_reviewed(self.paths.reviewed, self.reviewed)

    def first_unfinished_index(self):
        for i, q in enumerate(self.queries):
            if q not in self.reviewed:
                return i
        return 0

    def remaining_count(self):
        return sum(1 for q in self.queries if q not in self.reviewed)

    def total_graded(self):
        return sum(len(v) for v in self.selected.values())

    def cycle(self, q, nid):
        """Advance the grade of neighbor `nid` of query `q` by one click; return new grade."""
        grades = self.selected.setdefault(q, {})
        g = next_grade(grades.get(nid))
        if g is None:
            grades.pop(nid, None)
        else:
            grades[nid] = g
        return g
