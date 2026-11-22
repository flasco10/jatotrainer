"""Marathon maker page: pick charts in order, set rate/break per chart and arrange the collage background."""
import math
import os
import threading
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

import marathon_backend as mb
from pack_backend import background_path, validate_settings
from pack_maker import PackMaker, Popover

BG_SIZES = ['Auto', '1', '2', '3', '4']
ROWS = ['Auto', '1', '2', '3', '4', '5', '6']
BITRATES = ['128 kbps', '192 kbps', '256 kbps', '320 kbps']
ONE_ROW = 'All in one row'
PER_ROW = ['3', '4', '5', '6', ONE_ROW]
PREVIEW = (448, 252)
EXPANDED = (896, 504)
HINT = 'Drag the top bar to move a song · drag the picture to pan · scroll to zoom · double-click to reset · Delete removes · right-click for more'
HINT_SHORT = 'Top bar: move · Picture: pan · Scroll: zoom · Right-click: more'
IMAGE_TYPES = [('Images', '*.jpg *.jpeg *.png *.bmp *.webp'), ('All files', '*.*')]


def load_thumb(path):
    """Downscaled copy of a background for the live preview; None if it can't be read."""
    try:
        with Image.open(path) as image:
            thumb = image.convert('RGB')
        thumb.thumbnail((1280, 1280))
        return thumb
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def clock(ms):
    seconds = max(0, round(ms / 1000))
    return f'{seconds // 60}:{seconds % 60:02d}'


class MarathonSetup(Popover):
    def __init__(self, app):
        super().__init__(app, app.marathon_btn, 'New marathon', width=500, height=440)
        self.name = tk.StringVar(); self.creator = tk.StringVar(value=app.cfg.get('pack_creator', ''))
        self.od = tk.StringVar(value='8'); self.hp = tk.StringVar(value='8')
        ctk.CTkLabel(self.body, text='Create a marathon', font=ctk.CTkFont(size=24, weight='bold')).pack(pady=(20, 10))
        for label, var in [('Marathon name', self.name), ('Creator', self.creator)]:
            ctk.CTkLabel(self.body, text=label, anchor='w').pack(fill='x', padx=24)
            ctk.CTkEntry(self.body, textvariable=var).pack(fill='x', padx=24, pady=(0, 8))
        ctk.CTkLabel(self.body, text='Folder: Various Artists - <marathon name>', text_color='#94a3b8').pack()
        row = ctk.CTkFrame(self.body, fg_color='transparent'); row.pack(pady=8)
        for label, var in [('OD (0–10)', self.od), ('HP (0–10)', self.hp)]:
            ctk.CTkLabel(row, text=label).pack(side='left', padx=6)
            ctk.CTkEntry(row, textvariable=var, width=60).pack(side='left', padx=6)
        self.error = ctk.CTkLabel(self.body, text='', text_color='#fb7185', wraplength=470); self.error.pack(padx=20)
        ctk.CTkButton(self.body, text='Open Marathon maker', command=self.submit).pack(pady=8)

    def submit(self):
        import sys
        core = sys.modules[self.app.__class__.__module__]
        try:
            name, creator, od, hp, folder = validate_settings(core, self.name.get(), self.creator.get(), self.od.get(), self.hp.get())
            if self.app.songs_dir and os.path.exists(os.path.join(self.app.songs_dir, folder)):
                raise ValueError('That folder already exists. Choose another name.')
        except ValueError as e:
            self.error.configure(text=str(e)); return
        self.destroy()
        self.app.marathon_window = MarathonMaker(self.app, core, name, creator, od, hp)
        self.app.show_pack_page(self.app.marathon_window)


class MarathonMaker(PackMaker):
    TITLE = 'Marathon maker'; CARDS_LABEL = 'Songs in play order'; BUILD_TEXT = 'Create marathon'
    RATES_DEFAULT = '1'; RATES_HINT = 'Rate for this song (1 = original). Add the same chart again for another rate.'
    ADD_TEXT = 'Add song'; ARTIST_OPTIONS = False; SETTINGS_PREFIX = 'Marathon'

    def __init__(self, app, core, name, creator, od, hp):
        super().__init__(app, core, name, creator, od, hp)
        self.bitrate = tk.StringVar(value=f"{app.cfg.get('bitrate', core.DEFAULT_BITRATE)} kbps")
        if self.bitrate.get() not in BITRATES:
            self.bitrate.set('192 kbps')
        self.version = tk.StringVar(value='Marathon')
        # Every marathon needs a name and bitrate, so they live on the page, not behind a gear button.
        self.compression_button.pack_forget()
        row = self.settings_row
        ctk.CTkLabel(row, text='Difficulty name').pack(side='left', padx=(16, 6))
        ctk.CTkEntry(row, textvariable=self.version, width=170).pack(side='left')
        ctk.CTkLabel(row, text='Bitrate').pack(side='left', padx=(16, 6))
        ctk.CTkOptionMenu(row, variable=self.bitrate, values=BITRATES, width=110).pack(side='left')
        self.default_break = tk.StringVar(value=str(app.cfg.get('marathon_break', '3')))
        self.bitrate_warning = ctk.CTkLabel(row, text='', text_color='#f5a524')
        self.bitrate_warning.pack(side='left', padx=10)
        self.bitrate.trace_add('write', lambda *_: self.update_bitrate_warning())
        self.update_bitrate_warning()
        # Replace the pack's chart list with the collage preview plus an ordered song list.
        self.cards.destroy()
        right = ctk.CTkFrame(self, fg_color=core.BG_PANEL)
        right.grid(row=2, column=1, sticky='nsew', padx=(8, 16), pady=12)
        right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(right, fg_color='transparent'); top.grid(row=0, column=0, sticky='ew', padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text='Background', font=ctk.CTkFont(size=14, weight='bold')).pack(side='left')
        ctk.CTkButton(top, text='Auto layout', width=100, command=self.auto_layout).pack(side='right')
        saved = str(app.cfg.get('marathon_per_row', '4'))
        self.per_row = tk.StringVar(value=saved if saved in PER_ROW else '4')
        self.per_row.trace_add('write', lambda *_: self.schedule_preview())
        ctk.CTkOptionMenu(top, variable=self.per_row, values=PER_ROW, width=130).pack(side='right', padx=(0, 8))
        ctk.CTkLabel(top, text='Max per row').pack(side='right', padx=(12, 6))
        self.total_label = ctk.CTkLabel(top, text='', text_color='#94a3b8'); self.total_label.pack(side='right', padx=12)
        right.grid_rowconfigure(2, weight=0); right.grid_rowconfigure(4, weight=1)
        self._preview_job = None; self.selected_tile = None; self.editors = []
        self.preview_canvas = CollageEditor(right, self, PREVIEW)
        self.preview_canvas.grid(row=1, column=0, padx=12, pady=(8, 2))
        hint = ctk.CTkFrame(right, fg_color='transparent'); hint.grid(row=2, column=0, sticky='ew', padx=12)
        ctk.CTkLabel(hint, text=HINT_SHORT, text_color='#94a3b8', font=ctk.CTkFont(size=11)).pack(side='left')
        self.expand_button = ctk.CTkButton(hint, text='Expand ⤢', width=90, height=26, fg_color='#30394d', command=self.open_editor)
        self.expand_button.pack(side='right')
        # One break length for every gap; each song's own box still allows exceptions.
        gaps = ctk.CTkFrame(right, fg_color='transparent'); gaps.grid(row=3, column=0, sticky='ew', padx=12, pady=(6, 0))
        ctk.CTkLabel(gaps, text='Break between songs (s)').pack(side='left', padx=(0, 6))
        break_entry = ctk.CTkEntry(gaps, textvariable=self.default_break, width=52)
        break_entry.pack(side='left')
        break_entry.bind('<Return>', lambda _: self.apply_break_to_all())
        ctk.CTkButton(gaps, text='Apply to all', width=100, height=28, command=self.apply_break_to_all).pack(side='left', padx=8)
        self.cards = ctk.CTkScrollableFrame(right, fg_color='transparent', label_text=self.CARDS_LABEL)
        self.cards.grid(row=4, column=0, sticky='nsew', padx=4, pady=(4, 8)); self.cards.grid_columnconfigure(0, weight=1)
        self.render_entries()

    # ---- songs ---- #
    def add(self):
        if self.busy or not self.selected:
            return
        try:
            rate = float(self.rates.get().strip().rstrip('xX'))
            if not math.isfinite(rate) or not .1 <= rate <= 5:
                raise ValueError
        except ValueError:
            self.status.configure(text='Enter one rate between 0.1 and 5 (1 = original).'); return
        info = dict(self.selected)
        try:
            length = mb.chart_length_ms(self.core, info['path'])
        except (OSError, ValueError) as e:
            self.status.configure(text=f"{info.get('title', 'Chart')}: {e}"); return
        try:
            thumb = load_thumb(background_path(self.core, info))
        except (OSError, ValueError):
            thumb = None
        entry = dict(info=info, length=length, thumb=thumb, map_thumb=thumb, image=None, pitch=True,
                     rate=tk.StringVar(value=format(rate, 'g')), brk=tk.StringVar(value=self.default_break.get()),
                     weight=tk.StringVar(value='Auto'), row=tk.StringVar(value='Auto'),
                     focus=tk.DoubleVar(value=0.5), focus_y=tk.DoubleVar(value=0.5), zoom=tk.DoubleVar(value=1.0))
        for var in ('rate', 'brk', 'weight', 'row', 'focus', 'focus_y', 'zoom'):
            entry[var].trace_add('write', lambda *_: self.schedule_preview())
        self.entries.append(entry); self.render_entries()
        self.status.configure(text=f"Added {info['title']} at {format(rate, 'g')}x.")

    def remove(self, entry):
        if not self.busy:
            self.selected_tile = None
            super().remove(entry)

    def move(self, entry, delta):
        i = self.entries.index(entry)
        self.move_tile(i, i + delta)

    def move_tile(self, i, j):
        """Move song i to position j (others shift over); its tile and play order move together."""
        if self.busy or i == j or not (0 <= i < len(self.entries) and 0 <= j < len(self.entries)):
            return
        self.entries.insert(j, self.entries.pop(i))
        self.selected_tile = j
        self.render_entries()

    def toggle_pitch(self, entry):
        if self.busy:
            return
        entry['pitch'] = not entry['pitch']
        entry['card'].pitch_button.configure(fg_color=self.core.ACCENT if entry['pitch'] else '#424752')

    def render_entries(self):
        # Reuse existing cards: building customtkinter dropdowns is slow (~1 s for 7 songs),
        # so a reorder only regrids and renumbers; only new songs get a new card.
        self.mark_added()
        keep = set()
        for i, entry in enumerate(self.entries):
            card = entry.get('card')
            if card is None or not card.winfo_exists():
                card = entry['card'] = MarathonCard(self.cards, self, entry, i)
            card.grid(row=i, column=0, sticky='ew', padx=6, pady=4)
            card.set_index(i)
            keep.add(card)
        for child in self.cards.winfo_children():
            if isinstance(child, MarathonCard) and child not in keep:
                child.destroy()
        self.select_tile(self.selected_tile, scroll=False)
        self.schedule_preview()

    def select_tile(self, index, scroll=True):
        """Highlight one song's tile and card, scrolling the list to its card."""
        self.selected_tile = index if index is not None and 0 <= index < len(self.entries) else None
        for i, entry in enumerate(self.entries):
            entry['card'].configure(border_width=2 if i == self.selected_tile else 0, border_color=self.core.ACCENT)
        if scroll and self.selected_tile is not None:
            self.update_idletasks()
            card, canvas = self.entries[self.selected_tile]['card'], self.cards._parent_canvas
            total = max(1, card.master.winfo_height())
            canvas.yview_moveto(max(0.0, card.winfo_y() / total - 0.02))
        for editor in self.live_editors():
            editor.draw_overlays()

    # ---- collage ---- #
    def entry_rate(self, entry):
        try:
            rate = float(entry['rate'].get())
            return rate if math.isfinite(rate) and .1 <= rate <= 5 else 1.0
        except ValueError:
            return 1.0

    def layout_inputs(self):
        lengths = [e['length'] / self.entry_rate(e) for e in self.entries]
        auto = mb.auto_weights(lengths)
        weights = [a if e['weight'].get() == 'Auto' else int(e['weight'].get()) for e, a in zip(self.entries, auto)]
        rows = [None if e['row'].get() == 'Auto' else int(e['row'].get()) for e in self.entries]
        return weights, rows

    def per_row_value(self):
        value = self.per_row.get()
        return None if value == ONE_ROW else int(value)

    def focus_values(self):
        """(horizontal focus, vertical focus, zoom) per song."""
        return [(e['focus'].get(), e['focus_y'].get(), e['zoom'].get()) for e in self.entries]

    def auto_layout(self):
        for entry in self.entries:
            entry['weight'].set('Auto'); entry['row'].set('Auto')
        self.schedule_preview()

    def reset_crop(self, index):
        entry = self.entries[index]
        entry['focus'].set(0.5); entry['focus_y'].set(0.5); entry['zoom'].set(1.0)

    def set_image(self, index, path):
        """Use another picture for this song's tile; None goes back to the map's own background."""
        entry = self.entries[index]
        if path is None:
            entry['image'], entry['thumb'] = None, entry['map_thumb']
        else:
            thumb = load_thumb(path)
            if thumb is None:
                self.status.configure(text=f'Could not open {os.path.basename(path)} as an image.'); return
            entry['image'], entry['thumb'] = path, thumb
        self.reset_crop(index)
        self.schedule_preview()

    def collage(self, size, order=None):
        """Rendered preview image and tile rectangles at `size`.

        order: song indexes in display order, to preview a reorder before it happens.
        """
        order = order or list(range(len(self.entries)))
        weights, rows = self.layout_inputs()
        focus = self.focus_values()
        gap = max(2, round(4 * size[0] / mb.SIZE[0]))
        rects = mb.collage_layout([weights[i] for i in order], [rows[i] for i in order], size, gap=gap,
                                  per_row=self.per_row_value())
        # Bilinear keeps dragging smooth; the saved background uses Lanczos.
        image = mb.render_collage([self.entries[i]['thumb'] for i in order], rects, size, [focus[i] for i in order],
                                  Image.Resampling.BILINEAR)
        return image, rects

    def render_tile(self, index, size):
        """Just one song's tile at `size`, for redrawing while it is panned."""
        entry = self.entries[index]
        w, h = size
        return mb.render_collage([entry['thumb']], [(0, 0, w, h)], (w, h), [self.focus_values()[index]],
                                 Image.Resampling.BILINEAR)

    def live_editors(self):
        self.editors = [e for e in self.editors if e.winfo_exists()]
        return [self.preview_canvas, *self.editors] if self.preview_canvas.winfo_exists() else self.editors

    def open_editor(self):
        window = Popover(self.app, self.expand_button, 'Background editor', width=960, height=640)
        editor = CollageEditor(window.body, self, EXPANDED)
        editor.pack(padx=8, pady=8)
        ctk.CTkLabel(window.body, text=HINT, text_color='#94a3b8').pack()
        self.editors.append(editor)
        editor.redraw()
        return editor

    def schedule_preview(self):
        if self._preview_job is not None:
            try: self.after_cancel(self._preview_job)
            except tk.TclError: pass
        self._preview_job = self.after(60, self.draw_preview)

    def draw_preview(self):
        self._preview_job = None
        total = 0.0
        for i, e in enumerate(self.entries):
            total += e['length'] / self.entry_rate(e)
            if i < len(self.entries) - 1:
                try: total += max(0.0, float(e['brk'].get())) * 1000
                except ValueError: pass
        self.total_label.configure(text=f'{len(self.entries)} songs · about {clock(total)}' if self.entries else '')
        for editor in self.live_editors():
            editor.redraw()

    # ---- audio settings ---- #
    def update_bitrate_warning(self):
        self.bitrate_warning.configure(text='Above 192 kbps: against ranking rules, bigger upload'
                                       if int(self.bitrate.get().split()[0]) > 192 else '')

    def apply_break_to_all(self):
        """Set every song's break to the global value; new songs start with it too."""
        if self.busy:
            return
        try:
            seconds = float(self.default_break.get())
            if not math.isfinite(seconds) or not 0 <= seconds <= 600:
                raise ValueError
        except ValueError:
            self.status.configure(text='Break between songs must be 0–600 seconds.'); return
        value = format(seconds, 'g')
        self.default_break.set(value)
        for entry in self.entries:
            entry['brk'].set(value)
        self.app.cfg['marathon_break'] = value
        self.core.save_json(self.core.CONFIG_PATH, self.app.cfg)
        self.status.configure(text=f'Break set to {value} s between all {len(self.entries)} songs.')

    def remove_selected(self):
        if self.selected_tile is not None and not self.busy:
            self.remove(self.entries[self.selected_tile])

    def compression_options(self):
        if self.busy:
            return
        window = Popover(self.app, self.compression_button, 'Audio', width=460, height=300)
        ctk.CTkLabel(window.body, text='Marathon audio', font=ctk.CTkFont(size=20, weight='bold')).pack(pady=12)
        ctk.CTkOptionMenu(window.body, variable=self.bitrate, values=BITRATES).pack(pady=6)
        warning = ctk.CTkLabel(window.body, text='', text_color='#f5a524', wraplength=400); warning.pack(pady=4)
        def update(*_):
            if not warning.winfo_exists():
                return
            warning.configure(text='Above 192 kbps breaks osu! ranking criteria and makes the upload bigger.'
                              if int(self.bitrate.get().split()[0]) > 192 else '')
        self.bitrate.trace_add('write', update); update()
        row = ctk.CTkFrame(window.body, fg_color='transparent'); row.pack(pady=6)
        ctk.CTkLabel(row, text='Difficulty name').pack(side='left', padx=6)
        ctk.CTkEntry(row, textvariable=self.version, width=180).pack(side='left')
        ctk.CTkButton(window.body, text='Done', command=window.destroy).pack(pady=8)

    # ---- build ---- #
    def done_message(self, path, count):
        return f'Created a {count}-song marathon in {path} · Refresh osu! with F5.'

    def build(self):
        if self.busy:
            return
        try:
            settings = validate_settings(self.core, self.name.get(), self.creator.get(), self.od.get(), self.hp.get())
            if len(self.entries) < 2:
                raise ValueError('Add at least two songs.')
            entries = []
            for i, e in enumerate(self.entries, 1):
                try:
                    rate = float(e['rate'].get()); brk = float(e['brk'].get())
                except ValueError:
                    raise ValueError(f'Song {i}: rate and break must be numbers.')
                if not math.isfinite(rate) or not .1 <= rate <= 5:
                    raise ValueError(f'Song {i}: rate must be between 0.1 and 5.')
                if not math.isfinite(brk) or not 0 <= brk <= 600:
                    raise ValueError(f'Song {i}: break must be between 0 and 600 seconds.')
                entries.append(dict(path=e['info']['path'], rate=rate, pitch=e['pitch'], break_after=brk, background=e['image']))
            songs = self.core.normalize_songs_dir(self.songs.get())
            if not songs:
                raise ValueError('Choose your Songs folder.')
            if not self.app.ffmpeg:
                raise ValueError('FFmpeg is required to join the songs. Use Set up FFmpeg on the main page.')
        except ValueError as e:
            self.status.configure(text=str(e)); return
        name, creator, od, hp, _ = settings
        weights, rows = self.layout_inputs()
        per_row, focus = self.per_row_value(), self.focus_values()
        bitrate = int(self.bitrate.get().split()[0]); version = self.version.get()
        self.app.cfg.update(pack_creator=creator, marathon_per_row=self.per_row.get())
        self.core.save_json(self.core.CONFIG_PATH, self.app.cfg)
        self.busy = True; self.build_button.configure(state='disabled')
        self.progress.configure(progress_color=self.core.ACCENT); self.progress.set(0)
        self.status.configure(text='Preparing marathon…')

        def work():
            try:
                path, offsets = mb.build_marathon(self.core, songs, name, creator, od, hp, entries, self.app.ffmpeg,
                                                  bitrate=bitrate, version=version, weights=weights, rows=rows,
                                                  per_row=per_row, focus=focus,
                                                  report=lambda p, s: self.q.put(('progress', p, s)))
                self.q.put(('done', path, len(offsets)))
            except Exception as e:
                self.q.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()


class MarathonCard(ctk.CTkFrame):
    """One song: order, rate, pitch, break after it, and its background slot."""
    def __init__(self, parent, maker, entry, index):
        super().__init__(parent, fg_color='#171d30', corner_radius=12)
        self.grid_columnconfigure(0, weight=1)
        info = entry['info']
        top = ctk.CTkFrame(self, fg_color='transparent'); top.grid(row=0, column=0, sticky='ew', padx=10, pady=(8, 2))
        top.grid_columnconfigure(1, weight=1)
        self.number = ctk.CTkLabel(top, text=str(index + 1), width=26, height=22, fg_color='#111322', corner_radius=6)
        self.number.grid(row=0, column=0, padx=(0, 8))
        ctk.CTkLabel(top, text=f"{info['title']} [{info.get('version', '')}]", anchor='w',
                     font=ctk.CTkFont(size=13, weight='bold')).grid(row=0, column=1, sticky='ew')
        ctk.CTkLabel(top, text=clock(entry['length']), text_color='#94a3b8').grid(row=0, column=2, padx=6)
        for col, (text, command) in enumerate([('↑', lambda: maker.move(entry, -1)), ('↓', lambda: maker.move(entry, 1)),
                                               ('✕', lambda: maker.remove(entry))], 3):
            ctk.CTkButton(top, text=text, width=28, height=24, fg_color='#30394d', command=command).grid(row=0, column=col, padx=1)
        opts = ctk.CTkFrame(self, fg_color='transparent'); opts.grid(row=1, column=0, sticky='w', padx=10, pady=(2, 8))
        ctk.CTkLabel(opts, text='Rate').pack(side='left', padx=(0, 4))
        ctk.CTkEntry(opts, textvariable=entry['rate'], width=52).pack(side='left')
        self.pitch_button = ctk.CTkButton(opts, text='Pitch', width=52, height=26,
                                          fg_color=maker.core.ACCENT if entry['pitch'] else '#424752',
                                          command=lambda: maker.toggle_pitch(entry))
        self.pitch_button.pack(side='left', padx=6)
        ctk.CTkLabel(opts, text='Break after (s)').pack(side='left', padx=(6, 4))
        ctk.CTkEntry(opts, textvariable=entry['brk'], width=44).pack(side='left')
        ctk.CTkLabel(opts, text='BG size').pack(side='left', padx=(10, 4))
        ctk.CTkOptionMenu(opts, variable=entry['weight'], values=BG_SIZES, width=84).pack(side='left')
        ctk.CTkLabel(opts, text='Row').pack(side='left', padx=(10, 4))
        ctk.CTkOptionMenu(opts, variable=entry['row'], values=ROWS, width=84).pack(side='left')
        # Clicking a card highlights its tile in the preview.
        # Look the position up on click: cards are reused when songs are reordered.
        for widget in (self, top, opts):
            widget.bind('<Button-1>', lambda _: maker.select_tile(maker.entries.index(entry), scroll=False), add='+')

    def set_index(self, index):
        if self.number.cget('text') != str(index + 1):
            self.number.configure(text=str(index + 1))


class CollageEditor(tk.Canvas):
    """Live background preview you edit with the mouse.

    Each tile has a handle bar on top (drag it to move the song to another position in
    play order) and a pan area below (drag to pan the picture; it never reorders).
    Scroll to zoom, double-click to reset, Delete removes the selected song, and
    right-click opens size, row and image options.
    """

    def __init__(self, parent, maker, size):
        super().__init__(parent, width=size[0], height=size[1], bg='#000000', highlightthickness=0)
        self.maker, self.size = maker, size
        self.handle_h = 22 if size[0] < 600 else 30
        self.rects, self.drag, self.hover, self.hover_zone, self.target = [], None, None, None, None
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<B1-Motion>', self.motion)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<Double-Button-1>', self.double)
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-4>', lambda e: self.wheel(e, 120))  # X11 scroll up
        self.bind('<Button-5>', lambda e: self.wheel(e, -120))
        self.bind('<Button-3>', self.menu)
        self.bind('<Motion>', self.hover_move)
        self.bind('<Leave>', lambda _: self.set_hover(None, None))
        self.bind('<Delete>', lambda _: self.maker.remove_selected())

    # ---- drawing ---- #
    def redraw(self):
        self.delete('all')
        self.image_item = None
        if not self.maker.entries:
            self.rects = []
            self.create_text(self.size[0] / 2, self.size[1] / 2, text='Add songs to build the background',
                             fill='#94a3b8', font=('Poppins', 11))
            return
        self.base, self.rects = self.maker.collage(self.size)
        self.handles = self.handle_layer(self.rects)
        self.show(self.base, self.handles)

    def handle_layer(self, rects):
        """Handle bars as a see-through layer; editor-only, the saved background never has them."""
        layer = Image.new('RGBA', self.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = ImageFont.load_default(size=max(11, round(self.handle_h * 0.55)))
        hh = self.handle_h
        for i, (x, y, w, h) in enumerate(rects):
            draw.rectangle((x, y, x + w - 1, y + hh - 1), fill=(17, 19, 34, 190))
            for row in range(3):  # grip dots
                for col in range(2):
                    cx, cy = x + 8 + col * 5, y + hh / 2 - 5 + row * 5
                    draw.ellipse((cx - 1.2, cy - 1.2, cx + 1.2, cy + 1.2), fill=(200, 210, 230, 255))
            draw.text((x + 22, y + hh / 2), str(i + 1), fill='white', anchor='lm', font=font)
        return layer

    def show(self, image, handles):
        """Put a frame on screen by swapping the picture in place (no canvas rebuild)."""
        self.photo = ImageTk.PhotoImage(Image.alpha_composite(image.convert('RGBA'), handles))
        if self.image_item is None:
            self.image_item = self.create_image(0, 0, image=self.photo, anchor='nw')
            self.tag_lower(self.image_item)
        else:
            self.itemconfigure(self.image_item, image=self.photo)
        self.draw_overlays()

    def redraw_tile(self, i):
        """Repaint only tile i (panning), reusing the rest of the cached collage."""
        x, y, w, h = self.rects[i]
        self.base.paste(self.maker.render_tile(i, (w, h)), (x, y))
        self.show(self.base, self.handles)

    def preview_order(self, i, target):
        """While a song's bar is dragged, show the collage as it will look after the drop."""
        if target is None or target == i:
            self.preview_rects = None
            self.show(self.base, self.handles)
            return
        order = list(range(len(self.maker.entries)))
        order.insert(target, order.pop(i))
        image, self.preview_rects = self.maker.collage(self.size, order)
        self.show(image, self.handle_layer(self.preview_rects))

    def label(self, x, y, text, anchor='sw', width=None, fill='#111322'):
        item = self.create_text(x, y, text=text, fill='white', anchor=anchor, width=width,
                                font=('Poppins', 9), tags='overlay')
        bx0, by0, bx1, by1 = self.bbox(item)
        back = self.create_rectangle(bx0 - 4, by0 - 2, bx1 + 4, by1 + 2, fill=fill, outline='', tags='overlay')
        self.tag_lower(back, item)

    def draw_overlays(self):
        self.delete('overlay')
        if not self.rects:
            return
        accent, hh = self.maker.core.ACCENT, self.handle_h
        drag = self.drag
        if drag and drag[0] == 'move':
            if getattr(self, 'preview_rects', None) and self.target is not None:
                # The picture already shows the new order; outline where the song lands.
                x, y, w, h = self.preview_rects[self.target]
                self.create_rectangle(x + 1, y + 1, x + w - 2, y + h - 2, outline='#f5a524', width=3, dash=(6, 3), tags='overlay')
                self.label(x + w / 2, y + h / 2, f'Drop: song {drag[1] + 1} → {self.target + 1}', anchor='center', fill='#7c4a03')
            else:
                x, y, w, h = self.rects[drag[1]]
                self.create_rectangle(x + 1, y + 1, x + w - 2, y + h - 2, outline='#f5a524', width=3, dash=(6, 3), tags='overlay')
            return
        selected = self.maker.selected_tile
        if selected is not None and selected < len(self.rects):
            x, y, w, h = self.rects[selected]
            self.create_rectangle(x + 1, y + 1, x + w - 2, y + h - 2, outline=accent, width=3, tags='overlay')
        if drag and drag[0] == 'pan':
            i = drag[1]; x, y, w, h = self.rects[i]
            fx, fy, zoom = self.maker.focus_values()[i]
            self.label(x + 6, y + h - 6, f'Pan {round(fx * 100)}% · {zoom:.1f}x', width=max(40, w - 12))
            return
        if self.hover is None or self.hover >= len(self.rects):
            return
        x, y, w, h = self.rects[self.hover]
        if self.hover_zone == 'handle':
            self.create_rectangle(x, y, x + w, y + hh, fill=accent, outline='', tags='overlay')
            self.create_text(x + 8, y + hh / 2, text=f'≡ {self.hover + 1}  move' if w > 70 else f'≡ {self.hover + 1}',
                             fill='white', anchor='w', font=('Poppins', 9, 'bold'), tags='overlay')
        else:
            over_x, over_y = self.overflow(self.hover)
            arrows = '⟷' if over_x > 1 and over_y <= 1 else '↕' if over_y > 1 and over_x <= 1 else '✥' if over_x > 1 else ''
            if arrows:
                self.label(x + w / 2, y + hh + (h - hh) / 2, f'{arrows} drag to pan', anchor='center')
            entry = self.maker.entries[self.hover]
            text = f"{self.hover + 1}. {entry['info']['title']} · {clock(entry['length'] / self.maker.entry_rate(entry))}"
            self.label(x + 6, y + h - 6, text, width=max(40, w - 12))

    # ---- hit testing ---- #
    def tile_at(self, x, y):
        for i, (rx, ry, w, h) in enumerate(self.rects):
            if rx <= x < rx + w and ry <= y < ry + h:
                return i
        return None

    def zone_at(self, x, y):
        """(tile index, 'handle' or 'pan'), or (None, None) outside every tile."""
        i = self.tile_at(x, y)
        if i is None:
            return None, None
        return i, 'handle' if y < self.rects[i][1] + self.handle_h else 'pan'

    def overflow(self, i):
        """How many tile pixels the image extends past the tile horizontally and vertically."""
        entry = self.maker.entries[i]
        _, _, w, h = self.rects[i]
        if entry['thumb'] is None:
            return 0, 0
        iw, ih = entry['thumb'].size
        scale = max(w / iw, h / ih) * max(1.0, entry['zoom'].get())
        return iw * scale - w, ih * scale - h

    def pan_cursor(self, i):
        over_x, over_y = self.overflow(i)
        if over_x > 1 and over_y > 1:
            return 'fleur'
        return 'sb_h_double_arrow' if over_x > 1 else 'sb_v_double_arrow' if over_y > 1 else 'arrow'

    # ---- mouse ---- #
    def press(self, event):
        self.focus_set()  # so Delete reaches this editor
        i, zone = self.zone_at(event.x, event.y)
        if i is None or self.maker.busy:
            return
        self.maker.select_tile(i)
        entry = self.maker.entries[i]
        if zone == 'handle':
            self.drag = ('move', i); self.configure(cursor='hand2')
        else:
            self.drag = ('pan', i, event.x, event.y, entry['focus'].get(), entry['focus_y'].get())
        self.draw_overlays()

    def motion(self, event):
        if not self.drag:
            return
        if self.drag[0] == 'move':
            # Hit-test against the layout from when the drag began, so the live preview
            # reshuffling under the mouse can't make the target flicker.
            target = self.tile_at(event.x, event.y)
            if target != self.target:
                self.target = target
                self.preview_order(self.drag[1], target)
            return
        # Panning stays with its tile even if the mouse wanders onto a neighbour.
        _, i, x0, y0, fx0, fy0 = self.drag
        over_x, over_y = self.overflow(i)
        entry = self.maker.entries[i]
        # Moving the mouse right drags the picture right, showing more of its left side.
        if over_x > 1:
            entry['focus'].set(min(1.0, max(0.0, fx0 - (event.x - x0) / over_x)))
        if over_y > 1:
            entry['focus_y'].set(min(1.0, max(0.0, fy0 - (event.y - y0) / over_y)))
        self.redraw_tile(i)

    def release(self, event):
        drag, target = self.drag, self.target
        self.drag, self.target, self.preview_rects = None, None, None
        if drag and drag[0] == 'move' and target is not None and target != drag[1]:
            self.maker.move_tile(drag[1], target)
            self.maker.draw_preview()  # show the new order now, not after the redraw timer
        elif drag and drag[0] == 'move':
            self.show(self.base, self.handles)
        self.hover_move(event)
        self.draw_overlays()

    def double(self, event):
        i, zone = self.zone_at(event.x, event.y)
        if i is not None and zone == 'pan' and not self.maker.busy:
            self.maker.reset_crop(i)

    def wheel(self, event, delta=None):
        i = self.tile_at(event.x, event.y)
        if i is None or self.maker.busy:
            return
        zoom = self.maker.entries[i]['zoom']
        step = 1.1 if (delta if delta is not None else event.delta) > 0 else 1 / 1.1
        zoom.set(round(min(4.0, max(1.0, zoom.get() * step)), 3))
        self.redraw()

    def hover_move(self, event):
        i, zone = self.zone_at(event.x, event.y)
        if not self.drag:
            self.configure(cursor='hand2' if zone == 'handle' else self.pan_cursor(i) if zone == 'pan' else 'arrow')
        self.set_hover(i, zone)

    def set_hover(self, index, zone=None):
        if (index, zone) != (self.hover, self.hover_zone):
            self.hover, self.hover_zone = index, zone
            self.draw_overlays()

    def menu(self, event):
        i = self.tile_at(event.x, event.y)
        if i is None or self.maker.busy:
            return
        self.maker.select_tile(i)
        entry = self.maker.entries[i]
        menu = tk.Menu(self, tearoff=0)
        size = tk.Menu(menu, tearoff=0)
        for value in BG_SIZES:
            size.add_radiobutton(label=value, value=value, variable=entry['weight'])
        row = tk.Menu(menu, tearoff=0)
        for value in ROWS:
            row.add_radiobutton(label=value, value=value, variable=entry['row'])
        menu.add_cascade(label='BG size', menu=size)
        menu.add_cascade(label='Row', menu=row)
        menu.add_command(label='Reset pan and zoom', command=lambda: self.maker.reset_crop(i))
        menu.add_separator()
        menu.add_command(label='Change image…', command=lambda: self.choose_image(i))
        if entry['image']:
            menu.add_command(label="Use the map's background", command=lambda: self.maker.set_image(i, None))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def choose_image(self, i):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='Choose a background image', filetypes=IMAGE_TYPES)
        if path:
            self.maker.set_image(i, path)
