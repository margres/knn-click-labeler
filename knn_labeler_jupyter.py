"""
KNN Click Labeler — JupyterLab (ipywidgets) version.

Usage in a notebook cell:

    from knn_labeler_jupyter import JupyterLabeler
    JupyterLabeler("path/to/data_dir")

Grade mapping (which grade each click gives) lives in labeler_core.py: CLICK_GRADES.
Progress is saved to the data folder after every click.
"""
import io

import ipywidgets as W
from IPython.display import display

import labeler_core as core
from labeler_core import GRADE_COLORS, LabelingSession, meta_str


class JupyterLabeler:
    def __init__(self, data_dir=".", cols=6, rows=4, tile_size=120, query_size=180,
                 hide_reviewed=True):
        problems = core.DataPaths(data_dir).check()
        if problems:
            raise FileNotFoundError("\n".join(problems))

        self.s = LabelingSession(data_dir)
        self.tile_size = tile_size
        self.query_size = query_size
        self._png_cache = {}
        self.index = 0
        self.page_by_query = {}
        self._tiles = {}  # nid -> (box, image, button)

        # --- controls ---
        btn = lambda d, **kw: W.Button(description=d, layout=W.Layout(width="auto"), **kw)
        self.status = W.HTML()
        self.cols_w = W.BoundedIntText(value=cols, min=1, max=50, description="Cols",
                                       layout=W.Layout(width="130px"))
        self.rows_w = W.BoundedIntText(value=rows, min=1, max=50, description="Rows",
                                       layout=W.Layout(width="130px"))
        self.hide_w = W.Checkbox(value=hide_reviewed, description="Hide reviewed", indent=False)
        self.save_b = btn("Save", icon="save")

        self.title = W.HTML()
        self.prev_q_b = btn("← Prev query")
        self.next_q_b = btn("Next query →")
        self.done_b = btn("Done", button_style="success", icon="check")

        self.auto_w = W.Checkbox(value=True, indent=False,
                                 description=f"Auto ({core.DEFAULT_VMIN}..{core.DEFAULT_VMAX})")
        self.range_w = W.IntRangeSlider(value=(core.DEFAULT_VMIN, core.DEFAULT_VMAX),
                                        min=-50, max=200, description="vmin/vmax",
                                        disabled=True, continuous_update=False)
        self.query_img = W.Image(format="png", width=query_size, height=query_size)

        self.prev_p_b = btn("◀ Prev page")
        self.next_p_b = btn("Next page ▶")
        self.page_lbl = W.Label()
        self.grid = W.GridBox()
        self.msg = W.HTML()

        legend = " &nbsp; ".join(
            f"<span style='background:{GRADE_COLORS.get(g, '#999')};color:white;"
            f"padding:1px 6px;border-radius:3px'>{line}</span>"
            for g, line in zip(core.CLICK_GRADES, core.legend_lines())
        ) + f" &nbsp; {core.legend_lines()[-1]}"
        self.legend = W.HTML(f"<b>Legend:</b> {legend}")

        # --- wiring ---
        self.cols_w.observe(self._on_layout, "value")
        self.rows_w.observe(self._on_layout, "value")
        self.hide_w.observe(lambda _: self.render(), "value")
        self.save_b.on_click(lambda _: self._save(notify=True))
        self.prev_q_b.on_click(lambda _: self.prev_query())
        self.next_q_b.on_click(lambda _: self.next_query())
        self.done_b.on_click(lambda _: self.mark_done())
        self.auto_w.observe(self._on_scale, "value")
        self.range_w.observe(self._on_scale, "value")
        self.prev_p_b.on_click(lambda _: self._change_page(-1))
        self.next_p_b.on_click(lambda _: self._change_page(+1))

        left = W.VBox([self.auto_w, self.range_w, self.query_img])
        right = W.VBox([self.legend, W.HBox([self.prev_p_b, self.page_lbl, self.next_p_b]),
                        self.grid])
        self.body = W.HBox([left, right])
        self.ui = W.VBox([
            W.HBox([self.status, self.cols_w, self.rows_w, self.hide_w, self.save_b]),
            W.HBox([self.title, self.done_b, self.prev_q_b, self.next_q_b]),
            self.msg,
            self.body,
        ])

        if self.hide_w.value:
            self.index = self.s.first_unfinished_index()
        self.render()

    def _ipython_display_(self):
        display(self.ui)

    # ----------------------------
    # helpers
    # ----------------------------
    @property
    def page_size(self):
        return self.cols_w.value * self.rows_w.value

    def _vmin_vmax(self):
        if self.auto_w.value:
            return core.DEFAULT_VMIN, core.DEFAULT_VMAX
        return self.range_w.value

    def _png(self, id_, size):
        vmin, vmax = self._vmin_vmax()
        key = (id_, size, vmin, vmax)
        if key not in self._png_cache:
            buf = io.BytesIO()
            core.load_scaled_pil(self.s.paths.images, id_, size, vmin, vmax).save(buf, format="PNG")
            self._png_cache[key] = buf.getvalue()
        return self._png_cache[key]

    def _save(self, notify=False):
        self.s.save()
        if notify:
            self.msg.value = f"<i>Saved to {self.s.paths.selected}</i>"

    def _update_status(self):
        self.status.value = (
            f"<b>Query {self.index + 1}/{len(self.s.queries)}</b> | "
            f"Remaining: {self.s.remaining_count()} | Graded: {self.s.total_graded()} &nbsp;"
        )

    def _style_tile(self, nid, grade):
        box, _, button = self._tiles[nid]
        color = GRADE_COLORS.get(grade)
        box.layout.border = f"4px solid {color}" if color else "4px solid transparent"
        button.style.button_color = color or None
        button.description = f"{nid}" + (f" [{grade}]" if grade else "")

    # ----------------------------
    # events
    # ----------------------------
    def _on_layout(self, _):
        if self.s.queries:
            self.page_by_query[self.s.queries[self.index]] = 0
        self.render()

    def _on_scale(self, _):
        self.range_w.disabled = self.auto_w.value
        if self.s.queries:
            self.query_img.value = self._png(self.s.queries[self.index], self.query_size)
        for nid, (_, img, _) in self._tiles.items():
            img.value = self._png(nid, self.tile_size)

    def _on_tile_click(self, q, nid):
        g = self.s.cycle(q, nid)
        self._style_tile(nid, g)
        self._update_status()
        self._save()

    def _change_page(self, delta):
        q = self.s.queries[self.index]
        total_pages = max(1, -(-len(self.s.neighbors.get(q, [])) // self.page_size))
        page = self.page_by_query.get(q, 0) + delta
        if page >= total_pages:  # past the last page -> next query
            self.next_query(skip_to_unreviewed=self.hide_w.value)
            return
        self.page_by_query[q] = max(0, page)
        self._render_page(q)

    # ----------------------------
    # navigation
    # ----------------------------
    def mark_done(self):
        if not self.s.queries:
            return
        self.s.reviewed.add(self.s.queries[self.index])
        self._save()
        self.next_query(skip_to_unreviewed=self.hide_w.value)

    def next_query(self, skip_to_unreviewed=False):
        if not self.s.queries:
            return
        i = min(self.index + 1, len(self.s.queries) - 1)
        if skip_to_unreviewed:
            while i < len(self.s.queries) and self.s.queries[i] in self.s.reviewed:
                i += 1
            if i >= len(self.s.queries):
                i = self.s.first_unfinished_index()
        self.index = i
        self.render()

    def prev_query(self):
        if not self.s.queries:
            return
        i = max(self.index - 1, 0)
        if self.hide_w.value:
            while i > 0 and self.s.queries[i] in self.s.reviewed:
                i -= 1
            if self.s.queries[i] in self.s.reviewed and self.s.remaining_count() > 0:
                i = self.s.first_unfinished_index()
        self.index = i
        self.render()

    # ----------------------------
    # rendering
    # ----------------------------
    def render(self):
        self.msg.value = ""
        if not self.s.queries:
            self.title.value = "<h3>No queries found.</h3>"
            self.body.layout.display = "none"
            return

        if self.hide_w.value:
            if self.s.remaining_count() == 0:
                self.title.value = "<h3>All queries are reviewed ✅</h3>"
                self.body.layout.display = "none"
                self._update_status()
                return
            if self.s.queries[self.index] in self.s.reviewed:
                self.index = self.s.first_unfinished_index()

        self.body.layout.display = ""
        q = self.s.queries[self.index]
        reviewed = " ✅" if q in self.s.reviewed else ""
        self.title.value = (
            f"<h3 style='margin:4px 12px 4px 0'>QUERY: {q}{reviewed} "
            f"<small>({meta_str(self.s.meta, q)}) "
            f"(neighbors: {len(self.s.neighbors.get(q, []))})</small></h3>"
        )
        self.query_img.value = self._png(q, self.query_size)
        self._update_status()
        self._render_page(q)

    def _render_page(self, q):
        neighs = self.s.neighbors.get(q, [])
        grades = self.s.selected.setdefault(q, {})
        total = len(neighs)
        total_pages = max(1, -(-total // self.page_size))
        page = max(0, min(self.page_by_query.get(q, 0), total_pages - 1))
        self.page_by_query[q] = page

        start = page * self.page_size
        end = min(start + self.page_size, total)
        self.page_lbl.value = f"Page {page + 1}/{total_pages}   ({start + 1}-{end} of {total})"
        self.prev_p_b.disabled = page == 0

        self._tiles = {}
        children = []
        for nid in neighs[start:end]:
            m = self.s.meta.get(nid, {})
            info = W.HTML(
                f"<div style='font-size:11px;color:red;text-align:center'>{meta_str(self.s.meta, nid)}</div>"
                if (m.get("final_score") or m.get("origin")) else ""
            )
            img = W.Image(value=self._png(nid, self.tile_size), format="png",
                          width=self.tile_size, height=self.tile_size)
            button = W.Button(layout=W.Layout(width=f"{self.tile_size}px"),
                              tooltip="Click to cycle grade")
            button.on_click(lambda _, n=nid: self._on_tile_click(q, n))
            box = W.VBox([info, img, button], layout=W.Layout(padding="2px"))
            self._tiles[nid] = (box, img, button)
            self._style_tile(nid, grades.get(nid))
            children.append(box)

        self.grid.layout.grid_template_columns = f"repeat({self.cols_w.value}, auto)"
        self.grid.children = children
