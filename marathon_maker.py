"""Marathon maker page: pick charts in order, set rate/break per chart and arrange the collage background."""
import math
import os
import threading
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import marathon_backend as mb
from pack_backend import background_path, validate_settings
from pack_maker import PackMaker, Popover

BG_SIZES = ['Auto', '1', '2', '3', '4']
ROWS = ['Auto', '1', '2', '3', '4', '5', '6']
BITRATES = ['128 kbps', '192 kbps', '256 kbps', '320 kbps']
PREVIEW = (448, 252)


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
        self.compression_button.configure(text='Audio ⚙')
        # Replace the pack's chart list with the collage preview plus an ordered song list.
        self.cards.destroy()
        right = ctk.CTkFrame(self, fg_color=core.BG_PANEL)
        right.grid(row=2, column=1, sticky='nsew', padx=(8, 16), pady=12)
        right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(right, fg_color='transparent'); top.grid(row=0, column=0, sticky='ew', padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text='Background', font=ctk.CTkFont(size=14, weight='bold')).pack(side='left')
        ctk.CTkButton(top, text='Auto layout', width=100, command=self.auto_layout).pack(side='right')
        self.total_label = ctk.CTkLabel(top, text='', text_color='#94a3b8'); self.total_label.pack(side='right', padx=12)
        self.preview_canvas = tk.Canvas(right, width=PREVIEW[0], height=PREVIEW[1], bg='#000000', highlightthickness=0)
        self.preview_canvas.grid(row=1, column=0, padx=12, pady=8)
        self.cards = ctk.CTkScrollableFrame(right, fg_color='transparent', label_text=self.CARDS_LABEL)
        self.cards.grid(row=2, column=0, sticky='nsew', padx=4, pady=(0, 8)); self.cards.grid_columnconfigure(0, weight=1)
        self._preview_job = None
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
        thumb = None
        try:
            path = background_path(self.core, info)
            if path:
                with Image.open(path) as image:
                    thumb = image.convert('RGB'); thumb.thumbnail((640, 640))
        except (OSError, ValueError):
            pass
        entry = dict(info=info, length=length, thumb=thumb, pitch=True,
                     rate=tk.StringVar(value=format(rate, 'g')), brk=tk.StringVar(value=self.app.cfg.get('marathon_break', '3')),
                     weight=tk.StringVar(value='Auto'), row=tk.StringVar(value='Auto'))
        for var in ('rate', 'brk', 'weight', 'row'):
            entry[var].trace_add('write', lambda *_: self.schedule_preview())
        self.entries.append(entry); self.render_entries()
        self.status.configure(text=f"Added {info['title']} at {format(rate, 'g')}x.")

    def move(self, entry, delta):
        if self.busy:
            return
        i = self.entries.index(entry); j = i + delta
        if 0 <= j < len(self.entries):
            self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
            self.render_entries()

    def toggle_pitch(self, entry):
        if self.busy:
            return
        entry['pitch'] = not entry['pitch']
        entry['card'].pitch_button.configure(fg_color=self.core.ACCENT if entry['pitch'] else '#424752')

    def render_entries(self):
        for child in self.cards.winfo_children():
            child.destroy()
        for i, entry in enumerate(self.entries):
            card = MarathonCard(self.cards, self, entry, i)
            card.grid(row=i, column=0, sticky='ew', padx=6, pady=4)
            entry['card'] = card
        self.schedule_preview()

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

    def auto_layout(self):
        for entry in self.entries:
            entry['weight'].set('Auto'); entry['row'].set('Auto')
        self.schedule_preview()

    def schedule_preview(self):
        if self._preview_job is not None:
            try: self.after_cancel(self._preview_job)
            except tk.TclError: pass
        self._preview_job = self.after(120, self.draw_preview)

    def draw_preview(self):
        self._preview_job = None
        c = self.preview_canvas; c.delete('all')
        total = 0.0
        for i, e in enumerate(self.entries):
            total += e['length'] / self.entry_rate(e)
            if i < len(self.entries) - 1:
                try: total += max(0.0, float(e['brk'].get())) * 1000
                except ValueError: pass
        self.total_label.configure(text=f'{len(self.entries)} songs · about {clock(total)}' if self.entries else '')
        if not self.entries:
            c.create_text(PREVIEW[0] / 2, PREVIEW[1] / 2, text='Add songs to build the background', fill='#94a3b8', font=('Poppins', 11))
            return
        weights, rows = self.layout_inputs()
        rects = mb.collage_layout(weights, rows, PREVIEW, gap=2)
        image = mb.render_collage([e['thumb'] for e in self.entries], rects, PREVIEW)
        draw = ImageDraw.Draw(image)
        for i, (x, y, w, h) in enumerate(rects):
            draw.rounded_rectangle((x + 4, y + 4, x + 26, y + 22), radius=5, fill='#111322')
            draw.text((x + 15, y + 13), str(i + 1), fill='white', anchor='mm')
        self.preview_image = ImageTk.PhotoImage(image)
        c.create_image(0, 0, image=self.preview_image, anchor='nw')

    # ---- audio settings ---- #
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
                entries.append(dict(path=e['info']['path'], rate=rate, pitch=e['pitch'], break_after=brk))
            songs = self.core.normalize_songs_dir(self.songs.get())
            if not songs:
                raise ValueError('Choose your Songs folder.')
            if not self.app.ffmpeg:
                raise ValueError('FFmpeg is required to join the songs. Use Set up FFmpeg on the main page.')
        except ValueError as e:
            self.status.configure(text=str(e)); return
        name, creator, od, hp, _ = settings
        weights, rows = self.layout_inputs()
        bitrate = int(self.bitrate.get().split()[0]); version = self.version.get()
        self.app.cfg['pack_creator'] = creator; self.core.save_json(self.core.CONFIG_PATH, self.app.cfg)
        self.busy = True; self.build_button.configure(state='disabled')
        self.progress.configure(progress_color=self.core.ACCENT); self.progress.set(0)
        self.status.configure(text='Preparing marathon…')

        def work():
            try:
                path, offsets = mb.build_marathon(self.core, songs, name, creator, od, hp, entries, self.app.ffmpeg,
                                                  bitrate=bitrate, version=version, weights=weights, rows=rows,
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
        ctk.CTkLabel(top, text=str(index + 1), width=26, height=22, fg_color='#111322', corner_radius=6).grid(row=0, column=0, padx=(0, 8))
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
