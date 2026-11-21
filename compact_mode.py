"""Embedded compact rate changer; shares the full mode's chart and settings."""
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps, ImageEnhance, ImageTk
from ui_components import TextCanvas


class CompactMode(ctk.CTkFrame):
    def __init__(self, app):
        import jatotrainer as j
        super().__init__(app, fg_color=j.BG_MAIN, corner_radius=16)
        self.app = app
        rates = app.parse_rates(silent=True)
        self.rate_value = min(2, max(.5, rates[0] if rates else 1.0))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        body = ctk.CTkFrame(self, fg_color='transparent')
        body.grid(row=0, column=0, sticky='nsew', padx=12, pady=(8, 0))
        header = ctk.CTkFrame(body, fg_color='transparent')
        header.pack(fill='x', pady=(0, 6))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(header, text='←', width=30, height=28, corner_radius=12, fg_color='#202b40',
                      command=app.exit_compact).grid(row=0, column=0)
        ctk.CTkLabel(header, text='jatotrainer', width=120, anchor='w', font=('Poppins', 14, 'bold')).grid(row=0, column=1, sticky='w', padx=8)
        self.rescan = ctk.CTkButton(header, text='Rescan', width=66, height=28,
                                    corner_radius=12, fg_color='#202b40', command=app.start_scan)
        self.rescan.grid(row=0, column=2, sticky='e')
        self.card = TextCanvas(body, height=70, bg=j.BG_MAIN, highlightthickness=0)
        self.card.pack(fill='x')
        self.card.bind('<Configure>', lambda _: self.draw_card())
        self.bpm = ctk.CTkLabel(body, text='Base — BPM  →  New — BPM', font=('Poppins', 10, 'bold'), text_color='#e6bc59', height=36, wraplength=260)
        self.bpm.pack(fill='x', pady=(2, 0))
        rate_row = ctk.CTkFrame(body, fg_color='transparent')
        rate_row.pack(fill='x')
        ctk.CTkLabel(rate_row, text='Rates', width=42, anchor='w').pack(side='left')
        ctk.CTkEntry(rate_row, textvariable=app.rates_var, height=25, corner_radius=12).pack(side='left', fill='x', expand=True)
        presets = ctk.CTkFrame(body, fg_color='transparent')
        presets.pack(fill='x', pady=(4, 2))
        self.rate_buttons = {}
        for i, hundredths in enumerate(range(80, 141, 5)):
            value = hundredths / 100
            button = ctk.CTkButton(presets, text=f'{value:.2f}×', width=48, height=23,
                                   corner_radius=11, font=('Poppins', 10),
                                   command=lambda r=value: self.toggle_rate(r))
            button.grid(row=i//5, column=i%5, padx=2, pady=2, sticky='ew')
            presets.grid_columnconfigure(i%5, weight=1)
            self.rate_buttons[value] = button
        slider_row = ctk.CTkFrame(body, fg_color='transparent')
        slider_row.pack(fill='x', pady=(2, 1))
        self.rate = ctk.CTkSlider(slider_row, from_=0.5, to=2, number_of_steps=150,
                                  width=154, height=16, command=self.set_rate,
                                  progress_color='#b88925', button_color='#e6bc59')
        self.rate.pack(side='left', fill='x', expand=True, padx=(3, 4))
        self.rate.set(self.rate_value)
        self.rate_label = ctk.CTkLabel(slider_row, text=f'{self.rate_value:.2f}×', width=48,
                                      height=24, font=('Poppins', 11), text_color='#e6bc59')
        self.rate_label.pack(side='left')
        self.add_rate = ctk.CTkButton(slider_row, text='Add', width=43, height=24,
                                     corner_radius=12, command=self.add_slider_rate)
        self.add_rate.pack(side='left', padx=(3, 0))
        self.od_label, self.od = self.slider(body, 'OD', self.set_od)
        self.hp_label, self.hp = self.slider(body, 'HP', self.set_hp)
        self.hp_value = None
        self.hp_chart = None
        self.pitch = ctk.CTkButton(body, text='Pitch', height=26, corner_radius=13, command=self.toggle_pitch)
        self.pitch.pack(fill='x', pady=(5, 0))
        self.status = ctk.CTkLabel(body, text='', justify='left', anchor='w',
                                   font=('Poppins', 9), text_color='#94a3b8', height=22)
        self.status.pack(fill='x', pady=(3, 0))
        self.status.bind('<Button-1>', lambda _: self.show_details())
        self.status.configure(cursor='hand2')
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=1, column=0, sticky='ew', padx=12, pady=(4, 10))
        self.create = ctk.CTkButton(footer, text='Create map', height=40, corner_radius=18,
                                    font=('Poppins', 14, 'bold'), command=app.on_generate)
        self.create.pack(fill='x')
        self.progress = ctk.CTkProgressBar(footer, height=7, corner_radius=4)
        self.progress.pack(fill='x', pady=(7, 0)); self.progress.set(0)
        self._card_key = None
        self.refresh()

    def show_details(self):
        from pack_maker import Popover
        panel = Popover(self.app, self.status, 'Output details', width=276, height=340)
        text = self.app.status.cget('text') + '\n\n' + self.app.log.get('1.0', 'end').strip()
        box = ctk.CTkTextbox(panel.body, width=230, height=250, wrap='word', corner_radius=12)
        box.pack(fill='both', expand=True)
        box.insert('1.0', text)
        box.configure(state='disabled')
        return panel

    def slider(self, parent, name, command):
        label = ctk.CTkLabel(parent, text=name, anchor='w', height=20, font=('Poppins', 11))
        label.pack(fill='x')
        slider = ctk.CTkSlider(parent, from_=0, to=10, number_of_steps=100, height=14, command=command)
        slider.pack(fill='x', pady=(0, 1))
        return label, slider

    def set_rate(self, value):
        self.rate_value = round(value, 2)
        self.rate.set(self.rate_value)
        self.refresh()

    def add_slider_rate(self):
        import jatotrainer as j
        rates = self.app.parse_rates(silent=True)
        if not any(abs(r-self.rate_value) < 1e-9 for r in rates):
            rates.append(self.rate_value)
            self.app.rates_var.set(', '.join(j.fmt_rate(r) for r in rates))
        self.refresh()

    def toggle_rate(self, value):
        self.app.toggle_rate(str(value))
        self.refresh()

    def set_od(self, value):
        self.app.od_override_enabled.set(True)
        self.app.od_override_value.set(format(round(value, 1), 'g'))

    def set_hp(self, value):
        self.hp_value = round(value, 1)
        self.refresh()

    def toggle_pitch(self):
        self.app.pitch_var.set(not self.app.pitch_var.get())
        self.refresh()

    def draw_card(self):
        app = self.app; m = app.selected
        w = max(100, self.card.winfo_width())
        self.card.delete('all')
        if app.background_image is not None:
            im = ImageEnhance.Brightness(ImageOps.fit(app.background_image, (w, 70))).enhance(.28).convert('RGBA')
        else:
            im = Image.new('RGBA', (w, 70), '#111727')
        mask = Image.new('L', (w, 70), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, 69), radius=14, fill=255)
        im.putalpha(mask)
        self.photo = ImageTk.PhotoImage(im)
        self.card.create_image(0, 0, image=self.photo, anchor='nw')
        def line(text, y, color, size):
            # Limit text to the available width without expanding the small window.
            import tkinter.font as font
            f = font.Font(family='Poppins', size=size)
            while text and f.measure(text) > w-24:
                text = text[:-2].rstrip() + '…' if not text.endswith('…') else text[:-2] + '…'
            self.card.create_text(12, y, text=text, anchor='w', fill=color, font=f)
        line(m['title'] if m else 'Choose a chart in osu!', 16, '#ffffff', 10)
        line(m['version'] if m else 'Following song selection', 36, '#8eb6ff', 9)
        line(f"{m['artist']} · {m['creator']}" if m else 'Rate changer', 55, '#a8b2c5', 8)

    @staticmethod
    def configure_changed(widget, **values):
        changed = {key: value for key, value in values.items() if widget.cget(key) != value}
        if changed:
            widget.configure(**changed)

    def refresh(self):
        app = self.app; m = app.selected; rates = app.parse_rates(silent=True)
        key = (m.get('path') if m else None, id(app.background_image), self.card.winfo_width())
        if key != self._card_key:
            self._card_key = key; self.draw_card()
        bpm = float(m['bpm']) if m else None
        new = ', '.join(str(round(bpm*rate)) for rate in rates) if bpm is not None and rates else '—'
        self.configure_changed(self.bpm, text=f"Base {round(bpm) if bpm is not None else '—'} BPM  →  New {new} BPM")
        self.configure_changed(self.rate_label, text=f'{self.rate_value:.2f}×')
        for value, button in self.rate_buttons.items():
            selected = any(abs(r-value) < 1e-9 for r in rates)
            self.configure_changed(button, fg_color='#b88925' if selected else '#202b40',
                             hover_color='#d0a341' if selected else '#303f59')
        try: od = app._od_override()
        except ValueError: od = None
        if od is None:
            try: od = float((m or {}).get('od', 8))
            except ValueError: od = 8
        self.od.set(od); self.configure_changed(self.od_label, text=f'OD  {od:g}')
        path = m.get('path') if m else None
        if path != self.hp_chart:
            self.hp_chart = path
            try:
                import jatotrainer as j
                _, sections = j.parse_osu(path)
                self.hp_value = float(j.kv(j.sec(sections, 'Difficulty'), 'HPDrainRate') or 5)
            except (OSError, TypeError, ValueError): self.hp_value = 5
        hp = self.hp_value if self.hp_value is not None else 5
        self.hp.set(hp); self.configure_changed(self.hp_label, text=f'HP  {hp:g}')
        self.configure_changed(self.pitch, text='Pitch on' if app.pitch_var.get() else 'Pitch off',
                             fg_color='#5b8cff' if app.pitch_var.get() else '#424752')
        self.configure_changed(self.create, state=app.gen_btn.cget('state'), text='' if app.busy else 'Create map')
        self.configure_changed(self.rescan, state='disabled' if app.busy else 'normal')
        self.configure_changed(self.progress, progress_color=app.progress.cget('progress_color'))
        self.progress.set(app.progress.get())
        text = app.status.cget('text')
        if text.startswith('Following osu!') or text.startswith('Selected:'): text = 'Following osu! · ready to create'
        if text.startswith('All ') and 'already exist' in text: text = 'Already exists · click for details'
        elif text.startswith('Created '): text = text.split(';')[0] + ' · click for details'
        if text.startswith('No selected chart'): text = 'Choose a chart in osu!stable.'
        if app.busy: text = 'Creating maps…'
        self.configure_changed(self.status, text=text.split('\n')[0][:43])
