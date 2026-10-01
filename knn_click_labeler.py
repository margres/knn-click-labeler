"""
KNN Click Labeler — desktop (Tkinter) version.

Grade mapping (which grade each click gives) lives in labeler_core.py: CLICK_GRADES.
"""
import os
import sys
import argparse
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk

import labeler_core as core
from labeler_core import GRADE_COLORS, LabelingSession, meta_str


# ----------------------------
# Path helper (PyInstaller-safe)
# ----------------------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = app_dir()

# ----------------------------
# CONFIG
# ----------------------------
DEFAULT_COLS = 10
DEFAULT_ROWS = 5

TILE_SIZE = 120
QUERY_SIZE = 180


# ----------------------------
# Image cache
# ----------------------------
class ImageCache:
    """
    Caches PhotoImage objects.
    Cache key includes (id, size, auto, vmin, vmax) so moving sliders refreshes images.
    """
    def __init__(self, folder):
        self.folder = folder
        self.cache = {}

    def get_photo(self, id_, size, auto_scale=True, vmin=0, vmax=255):
        if auto_scale:
            key = (id_, size, True)  # auto ignores vmin/vmax
            vmin, vmax = core.DEFAULT_VMIN, core.DEFAULT_VMAX
        else:
            key = (id_, size, False, int(vmin), int(vmax))

        if key in self.cache:
            return self.cache[key]

        photo = ImageTk.PhotoImage(core.load_scaled_pil(self.folder, id_, size, vmin, vmax))
        self.cache[key] = photo
        return photo

    def clear(self):
        self.cache.clear()


# ----------------------------
# Main Tkinter app
# ----------------------------
class KNNClickLabelerApp:
    def __init__(self, root, data_dir=BASE_DIR, cols=DEFAULT_COLS, rows=DEFAULT_ROWS):
        self.root = root
        root.title("KNN Click Labeler — click to assign grades")

        # Validate files/folders
        problems = core.DataPaths(data_dir).check()
        if problems:
            messagebox.showerror("Missing input data", "\n".join(problems))
            root.destroy()
            return

        self._q_img_label = None
        self._tile_labels = {}   # nid -> tk.Label

        self.session = LabelingSession(data_dir)
        self.neighbors = self.session.neighbors
        self.meta = self.session.meta
        self.queries = self.session.queries
        self.selected = self.session.selected    # dict[q][nid] = grade
        self.reviewed = self.session.reviewed

        self.cache = ImageCache(self.session.paths.images)

        # UI state
        self.index = 0
        self.page_by_query = {}

        # layout state (user adjustable)
        self.cols_var = tk.IntVar(value=max(1, int(cols)))
        self.rows_var = tk.IntVar(value=max(1, int(rows)))

        # hide reviewed toggle
        self.hide_reviewed_var = tk.BooleanVar(value=True)

        # scaling controls
        self.auto_scale_var = tk.BooleanVar(value=True)
        self.vmin_var = tk.IntVar(value=core.DEFAULT_VMIN)
        self.vmax_var = tk.IntVar(value=core.DEFAULT_VMAX)
        self._scale_debounce = None

        self._vmin_scale = None
        self._vmax_scale = None

        # --- Top bar ---
        top = ttk.Frame(root)
        top.pack(fill="x", padx=10, pady=8)

        self.status_var = tk.StringVar()
        ttk.Label(top, textvariable=self.status_var).pack(side="left")

        # Layout controls
        layout_box = ttk.Frame(top)
        layout_box.pack(side="left", padx=12)

        ttk.Label(layout_box, text="Cols").pack(side="left")
        self.cols_spin = ttk.Spinbox(
            layout_box, from_=1, to=50, width=4, textvariable=self.cols_var,
            command=self.on_layout_change
        )
        self.cols_spin.pack(side="left", padx=(4, 10))

        ttk.Label(layout_box, text="Rows").pack(side="left")
        self.rows_spin = ttk.Spinbox(
            layout_box, from_=1, to=50, width=4, textvariable=self.rows_var,
            command=self.on_layout_change
        )
        self.rows_spin.pack(side="left", padx=(4, 10))

        ttk.Checkbutton(
            top, text="Hide reviewed", variable=self.hide_reviewed_var,
            command=self.render_current_query
        ).pack(side="left", padx=6)

        ttk.Button(top, text="Save", command=self.save_all).pack(side="right", padx=5)
        ttk.Button(top, text="Quit", command=self.on_quit).pack(side="right", padx=5)

        # Keyboard shortcuts
        root.bind("<Control-s>", lambda e: self.save_all())
        root.bind("<Control-q>", lambda e: self.on_quit())
        root.bind("<Left>", lambda e: self.prev_query())
        root.bind("<Right>", lambda e: self.next_query())

        # Main content
        self.main = ttk.Frame(root)
        self.main.pack(fill="both", expand=True, padx=10, pady=8)

        # Start at first unreviewed if hiding reviewed
        if self.hide_reviewed_var.get():
            self.index = self.first_unfinished_index()
        self.render_current_query()

    @property
    def COLS(self):
        return max(1, int(self.cols_var.get()))

    @property
    def ROWS(self):
        return max(1, int(self.rows_var.get()))

    @property
    def PAGE_SIZE(self):
        return self.COLS * self.ROWS

    def on_layout_change(self):
        q = self.queries[self.index] if self.queries else None
        if q is not None:
            self.page_by_query[q] = 0
        self.render_current_query()

    def first_unfinished_index(self):
        return self.session.first_unfinished_index()

    def _remaining_count(self):
        return self.session.remaining_count()

    def _update_status(self):
        self.status_var.set(
            f"Query {self.index+1}/{len(self.queries)} | "
            f"Remaining: {self._remaining_count()} | "
            f"Graded: {self.session.total_graded()} | "
            f"Grid: {self.COLS}x{self.ROWS} (page={self.PAGE_SIZE})"
        )

    def _debounced_rerender(self, fn, ms=120):
        if self._scale_debounce is not None:
            try:
                self.root.after_cancel(self._scale_debounce)
            except Exception:
                pass
        self._scale_debounce = self.root.after(ms, fn)

    def refresh_visible_images(self):
        if not self.queries:
            return
        q = self.queries[self.index]

        # refresh query image
        if self._q_img_label is not None:
            q_photo = self.cache.get_photo(
                q, QUERY_SIZE,
                auto_scale=self.auto_scale_var.get(),
                vmin=self.vmin_var.get(),
                vmax=self.vmax_var.get(),
            )
            self._q_img_label.configure(image=q_photo)
            self._q_img_label.image = q_photo

        # refresh currently visible tiles
        for nid, lbl in list(self._tile_labels.items()):
            try:
                photo = self.cache.get_photo(
                    nid, TILE_SIZE,
                    auto_scale=self.auto_scale_var.get(),
                    vmin=self.vmin_var.get(),
                    vmax=self.vmax_var.get(),
                )
                lbl.configure(image=photo)
                lbl.image = photo
            except tk.TclError:
                # label was destroyed (query/page change)
                self._tile_labels.pop(nid, None)

    def on_auto_toggle(self):
        # enable/disable sliders immediately (no full rebuild)
        if self._vmin_scale is not None and self._vmax_scale is not None:
            if self.auto_scale_var.get():
                self._vmin_scale.state(["disabled"])
                self._vmax_scale.state(["disabled"])
            else:
                self._vmin_scale.state(["!disabled"])
                self._vmax_scale.state(["!disabled"])

        self._debounced_rerender(self.refresh_visible_images, 50)

    def render_current_query(self):

        for child in self.main.winfo_children():
            child.destroy()

        if not self.queries:
            ttk.Label(self.main, text="No queries found.", font=("Arial", 16, "bold")).pack(pady=20)
            return

        hide_reviewed = self.hide_reviewed_var.get()

        # If hiding reviewed, ensure current isn't reviewed
        if hide_reviewed and self.queries[self.index] in self.reviewed:
            self.index = self.first_unfinished_index()

        # All reviewed
        if hide_reviewed and self._remaining_count() == 0:
            ttk.Label(self.main, text="All queries are reviewed ✅", font=("Arial", 16, "bold")).pack(pady=20)
            self._update_status()
            return

        q = self.queries[self.index]
        neighs = self.neighbors.get(q, [])

        self.selected.setdefault(q, {})
        self.page_by_query.setdefault(q, 0)

        # Header
        header = ttk.Frame(self.main)
        header.pack(fill="x", pady=(0, 6))

        ttk.Label(
            header,
            text=f"QUERY: {q}   ({meta_str(self.meta, q)})   (neighbors: {len(neighs)})",
            font=("Arial", 16, "bold")
        ).pack(side="left")

        ttk.Button(header, text="← Prev query", command=self.prev_query).pack(side="right", padx=5)
        ttk.Button(header, text="Next query →", command=self.next_query).pack(side="right", padx=5)
        ttk.Button(header, text="Done", command=lambda qq=q: self.mark_done(qq)).pack(side="right", padx=5)

        # Body
        body = ttk.Frame(self.main)
        body.pack(fill="both", expand=True)

        # Left column: query image
        q_frame = ttk.Frame(body)
        q_frame.grid(row=0, column=0, padx=(0, 12), sticky="n")

        # Scaling controls (above query image)
        scale_box = ttk.LabelFrame(q_frame, text="Scaling (vmin/vmax)")
        vmin_val_var = tk.StringVar(value=f"{self.vmin_var.get()}")
        vmax_val_var = tk.StringVar(value=f"{self.vmax_var.get()}")

        scale_box.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(
            scale_box, text=f"Auto ({core.DEFAULT_VMIN}..{core.DEFAULT_VMAX})",
            variable=self.auto_scale_var, command=self.on_auto_toggle
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))

        ttk.Label(scale_box, text=f"Auto: vmin={core.DEFAULT_VMIN}  vmax={core.DEFAULT_VMAX}").grid(
            row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6)
        )

        ttk.Label(scale_box, text="vmin").grid(row=1, column=0, sticky="w", padx=6)
        ttk.Label(scale_box, textvariable=vmin_val_var, width=5).grid(row=1, column=2, sticky="e", padx=(0, 6))

        def on_vmin_move(v):
            self.vmin_var.set(int(float(v)))
            vmin_val_var.set(str(self.vmin_var.get()))
            if self.vmin_var.get() > self.vmax_var.get():
                self.vmax_var.set(self.vmin_var.get())
                vmax_scale.set(self.vmax_var.get())
                vmax_val_var.set(str(self.vmax_var.get()))
            self._debounced_rerender(self.refresh_visible_images, 50)

        def on_vmax_move(v):
            self.vmax_var.set(int(float(v)))
            vmax_val_var.set(str(self.vmax_var.get()))
            if self.vmax_var.get() < self.vmin_var.get():
                self.vmin_var.set(self.vmax_var.get())
                vmin_scale.set(self.vmin_var.get())
                vmin_val_var.set(str(self.vmin_var.get()))
            self._debounced_rerender(self.refresh_visible_images, 50)

        vmin_scale = ttk.Scale(scale_box, from_=-50, to=200, orient="horizontal", command=on_vmin_move)
        vmin_scale.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        vmin_scale.set(self.vmin_var.get())

        vmax_scale = ttk.Scale(scale_box, from_=-50, to=200, orient="horizontal", command=on_vmax_move)
        vmax_scale.grid(row=2, column=1, sticky="ew", padx=6, pady=(2, 6))
        vmax_scale.set(self.vmax_var.get())

        if self.auto_scale_var.get():
            vmin_scale.state(["disabled"])
            vmax_scale.state(["disabled"])
        else:
            vmin_scale.state(["!disabled"])
            vmax_scale.state(["!disabled"])

        self._vmin_scale = vmin_scale
        self._vmax_scale = vmax_scale

        ttk.Label(scale_box, text="vmax").grid(row=2, column=0, sticky="w", padx=6)
        ttk.Label(scale_box, textvariable=vmax_val_var, width=5).grid(row=2, column=2, sticky="e", padx=(0, 6))

        scale_box.columnconfigure(1, weight=1)

        # Query image (scaled)
        q_photo = self.cache.get_photo(
            q, QUERY_SIZE,
            auto_scale=self.auto_scale_var.get(),
            vmin=self.vmin_var.get(),
            vmax=self.vmax_var.get(),
        )

        self._q_img_label = tk.Label(q_frame, image=q_photo, bd=2, relief="solid")
        self._q_img_label.image = q_photo
        self._q_img_label.pack()

        # Right column
        right = tk.Frame(body)
        right.grid(row=0, column=1, sticky="nw")

        # Legend (built from CLICK_GRADES in labeler_core.py)
        legend = ttk.LabelFrame(right, text="Legend (clicks)")
        legend.pack(fill="x", pady=(0, 6))
        lines = core.legend_lines()
        for i, line in enumerate(lines):
            ttk.Label(legend, text=line).grid(row=i, column=0, sticky="w", padx=8)

        # small color swatches
        sw = ttk.Frame(legend)
        sw.grid(row=0, column=1, rowspan=len(lines), sticky="e", padx=8)
        for i, g in enumerate(core.CLICK_GRADES):
            box = tk.Frame(sw, width=18, height=10, bg=GRADE_COLORS[g])
            box.grid(row=i, column=0, pady=2, sticky="e")
            box.grid_propagate(False)

        pager = tk.Frame(right)
        pager.pack(fill="x", pady=(0, 6))

        prev_page_btn = ttk.Button(pager, text="◀ Prev page")
        prev_page_btn.pack(side="left")

        page_label_var = tk.StringVar()
        ttk.Label(pager, textvariable=page_label_var).pack(side="left", padx=10)

        next_page_btn = ttk.Button(pager, text="Next page ▶")
        next_page_btn.pack(side="left")

        grid_container = tk.Frame(right)
        grid_container.pack(fill="both", expand=True)

        def apply_grade_style(inner_label, grade_or_none):
            outer = inner_label.master
            if grade_or_none in GRADE_COLORS:
                outer.configure(bg=GRADE_COLORS[grade_or_none])
            else:
                outer.configure(bg=self.root.cget("bg"))

        footers = {}  # nid -> footer label

        def cycle_grade(neighbor_id, widget):
            g = self.session.cycle(q, neighbor_id)
            apply_grade_style(widget, g)
            footers[neighbor_id].configure(text=f"{neighbor_id}" + (f"  [{g}]" if g else ""))
            self._update_status()

        def render_page():
            self._tile_labels = {}
            footers.clear()

            for child in grid_container.winfo_children():
                child.destroy()

            page = self.page_by_query[q]
            total = len(neighs)
            total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

            page = max(0, min(page, total_pages - 1))
            self.page_by_query[q] = page

            start = page * self.PAGE_SIZE
            end = min(start + self.PAGE_SIZE, total)
            page_neighbors = neighs[start:end]

            page_label_var.set(f"Page {page+1}/{total_pages}   ({start+1}-{end} of {total})")
            prev_page_btn.configure(state=("normal" if page > 0 else "disabled"))
            next_page_btn.configure(state="normal")  # on last page it jumps to next query

            for i, nid in enumerate(page_neighbors):
                r = i // self.COLS
                c = i % self.COLS
                base_row = r * 3

                meta_info = self.meta.get(nid, {})
                fs = meta_info.get("final_score", "")
                org = meta_info.get("origin", "")

                if (fs or org):
                    text_color = "red" if (org and org != "?") else "white"
                    tk.Label(
                        grid_container,
                        text=meta_str(self.meta, nid),
                        font=("Arial", 12),
                        fg=text_color,
                        bg=self.root.cget("bg")
                    ).grid(row=base_row, column=c, pady=(0, 2))

                photo = self.cache.get_photo(
                    nid, TILE_SIZE,
                    auto_scale=self.auto_scale_var.get(),
                    vmin=self.vmin_var.get(),
                    vmax=self.vmax_var.get(),
                )

                outer = tk.Frame(grid_container, bd=0, bg=self.root.cget("bg"))
                outer.grid(row=base_row + 1, column=c, padx=4, pady=(2, 0))

                lbl = tk.Label(outer, image=photo, bd=2, relief="solid", cursor="hand2")
                lbl.pack(padx=3, pady=3)
                lbl.image = photo
                self._tile_labels[nid] = lbl

                current_grade = self.selected[q].get(nid)
                apply_grade_style(lbl, current_grade)

                lbl.bind("<Button-1>", lambda e, n=nid, w=lbl: cycle_grade(n, w))

                # show grade next to ID
                footer = f"{nid}" + (f"  [{current_grade}]" if current_grade else "")
                footers[nid] = ttk.Label(grid_container, text=footer, font=("Arial", 7))
                footers[nid].grid(row=base_row + 2, column=c, pady=(0, 6))

        def prev_page():
            self.page_by_query[q] -= 1
            render_page()

        def next_page():
            # If we're already at the last page for this query, go to next query
            page = self.page_by_query[q]
            total = len(neighs)
            total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
            if page >= total_pages - 1:
                self.next_query(skip_to_unreviewed=self.hide_reviewed_var.get())
                return
            self.page_by_query[q] += 1
            render_page()

        prev_page_btn.configure(command=prev_page)
        next_page_btn.configure(command=next_page)

        self._update_status()
        render_page()

    def save_all(self):
        self.session.save()
        messagebox.showinfo("Saved", "Progress saved.")

    def mark_done(self, query_id):
        self.reviewed.add(query_id)
        self.session.save()

        self.next_query(skip_to_unreviewed=self.hide_reviewed_var.get())

        if self._remaining_count() == 0:
            messagebox.showinfo("Done", "All queries reviewed")

    def next_query(self, skip_to_unreviewed=False):
        if not self.queries:
            return

        i = min(self.index + 1, len(self.queries) - 1)
        if skip_to_unreviewed:
            while i < len(self.queries) and self.queries[i] in self.reviewed:
                i += 1
            if i >= len(self.queries):
                i = self.first_unfinished_index()

        self.index = i
        self.render_current_query()

    def prev_query(self):
        if not self.queries:
            return

        i = max(self.index - 1, 0)
        if self.hide_reviewed_var.get():
            while i > 0 and self.queries[i] in self.reviewed:
                i -= 1
            if self.queries[i] in self.reviewed and self._remaining_count() > 0:
                i = self.first_unfinished_index()

        self.index = i
        self.render_current_query()

    def on_quit(self):
        self.session.save()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=BASE_DIR,
                        help="Folder with knn_cutouts/, neighbors_*.json, final_grade.csv "
                             "(default: folder of this script/app)")
    parser.add_argument("--cols", type=int, default=DEFAULT_COLS, help="Initial grid columns")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="Initial grid rows")
    args = parser.parse_args()

    root = tk.Tk()
    KNNClickLabelerApp(root, data_dir=args.data_dir, cols=args.cols, rows=args.rows)
    root.mainloop()


if __name__ == "__main__":
    main()
