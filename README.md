# KNN Click Labeler

A small tool for visually grading the nearest neighbours (KNN) of a set of query objects.
For each query image it shows a grid of its neighbours as cutouts. You click a cutout to give it a grade (A/B/C), and the grades are written to a CSV.

It comes in two versions that share the same data files and logic:

| Version | File | Use it when |
|---|---|---|
| Desktop app (Tkinter) | `knn_click_labeler.py` | You're working on your own machine (macOS/Linux/Windows) |
| JupyterLab widget (ipywidgets) | `knn_labeler_jupyter.py` / `labeler.ipynb` | You're in JupyterLab, including on a remote server or cluster |

## Grading

Click a tile repeatedly to cycle through the grades:

| Clicks | Grade | Colour |
|---|---|---|
| 1 | **C** | red |
| 2 | **B** | orange |
| 3 | **A** | green |
| 4 | *(cleared)* | — |

### Changing the grades

Everything is set at the top of **`labeler_core.py`**:

```python
CLICK_GRADES = ["C", "B", "A"]     # 1st click, 2nd click, 3rd click, ...

GRADE_COLORS = {
    "A": "#2ecc71",  # green
    "B": "#f39c12",  # orange
    "C": "#e74c3c",  # red
}
```

- To reverse the order (1 click = A), use `CLICK_GRADES = ["A", "B", "C"]`.
- To add a grade, add it to `CLICK_GRADES` and give it a colour in `GRADE_COLORS`.
- The on-screen legend in both versions is built from these settings, so it updates automatically.

## Input data

Put these in one folder (the *data folder*):

```
data_folder/
├── knn_cutouts/            # one PNG per object: <ID>.png
├── neighbors_A.json        # {"<query ID>": ["<neighbor ID>", ...], ...}
├── neighbors_B_C.json      # same format; merged with the file above
└── final_grade.csv         # optional: sets the query order and the metadata shown
                            # (columns used: ID, final_grade, origin, final_score)
```

At least one of the two neighbour JSON files is required. Missing cutouts show up as grey squares.
The file names are set in `labeler_core.py` (section *Data files*).

## Output

Both files are written to the data folder:

- **`selected_neighbors.csv`**: `query_id, neighbor_id, grade, timestamp_utc`, one row per graded neighbour.
- **`reviewed_queries.csv`**: `query_id, timestamp_utc`, the queries you've marked **Done**.

Your progress is reloaded the next time you start, so you can stop and resume whenever you like.

## Installation

```bash
git clone https://github.com/margres/knn-click-labeler.git
cd knn-click-labeler
pip install -r requirements.txt
```

The desktop version also needs Tkinter, which ships with most Python installs. On Linux you may need `sudo apt install python3-tk`; with conda, run `conda install tk`.

## Usage: desktop app

```bash
python knn_click_labeler.py --data-dir /path/to/data_folder
```

| Option | Default | Meaning |
|---|---|---|
| `--data-dir` | folder of the script | where the input data is and the output CSVs go |
| `--cols` | 10 | grid columns |
| `--rows` | 5 | grid rows |

Click directly on a cutout to grade it. Shortcuts: `←` / `→` move to the previous/next query, `Ctrl+S` saves, and `Ctrl+Q` saves and quits.
Progress is saved when you press **Done**, **Save** or **Quit**.

## Usage: JupyterLab

Open `labeler.ipynb`, set `DATA_DIR`, and run the cell. Or, in any notebook:

```python
import sys; sys.path.append("/path/to/knn-click-labeler")   # if the notebook is elsewhere
from knn_labeler_jupyter import JupyterLabeler

app = JupyterLabeler("/path/to/data_folder", cols=6, rows=4)
app
```

Click the **button under each cutout** to cycle its grade. The button and the tile border take the grade's colour.
In this version, progress is **saved automatically after every click**.

Optional arguments: `cols`, `rows`, `tile_size` (default 120 px), `query_size` (180 px), `hide_reviewed` (True).

After grading, you can inspect the results with pandas:

```python
import pandas as pd
pd.read_csv(app.s.paths.selected).groupby("grade").size()
```

## Controls (both versions)

- **Done**: marks the current query as reviewed and moves to the next unreviewed one.
- **Prev / Next query**: move between queries without marking them as done.
- **Prev / Next page**: page through the neighbours. Pressing *Next page* on the last page moves on to the next query.
- **Cols / Rows**: change the grid size.
- **Hide reviewed**: skip queries already marked Done.
- **Scaling**: *Auto* uses a fixed stretch of vmin = -10 and vmax = 160 (set by `DEFAULT_VMIN` / `DEFAULT_VMAX` in `labeler_core.py`). Untick it to set vmin/vmax by hand with the sliders.

## Building a standalone macOS app (optional)

```bash
pip install pyinstaller
pyinstaller --windowed --name KNNSelector knn_click_labeler.py
```

Copy the data files next to the executable in `dist/`. When `--data-dir` is not given, the app looks for them in its own folder.

## Project layout

```
labeler_core.py          # grade settings, file names, loading/saving, image scaling (no GUI)
knn_click_labeler.py     # Tkinter desktop app
knn_labeler_jupyter.py   # ipywidgets JupyterLab app
labeler.ipynb            # example notebook
requirements.txt
```
