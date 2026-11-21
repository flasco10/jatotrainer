"""Embedded chart conversion page with anchored source/output pickers."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
import customtkinter as ctk
from pack_maker import Popover, FolderPicker
from chart_conversion import catalog, convert


class SourcePicker(Popover):
    def __init__(self, page, anchor):
        super().__init__(page.app, anchor, 'Choose chart or pack', width=540, height=470)
        self.page = page
        initial = Path(page.source.get()).expanduser()
        self.path = tk.StringVar(value=str(initial.parent if initial.is_file() else initial if initial.is_dir() else Path.home()))
        path_entry=ctk.CTkEntry(self.body, textvariable=self.path)
        path_entry.pack(fill='x', padx=10, pady=6)
        path_entry.bind('<Return>', lambda _: self.refresh())
        bar = ctk.CTkFrame(self.body, fg_color='transparent');bar.pack(fill='x', padx=10)
        ctk.CTkButton(bar, text='↑ Up', width=65, command=self.up).pack(side='left')
        ctk.CTkButton(bar, text='Browse pack…', width=130, command=self.browse_pack).pack(side='right')
        self.tree = ttk.Treeview(self.body, show='tree', height=10, style='Maps.Treeview');self.tree.pack(fill='x', padx=10, pady=10)
        self.tree.bind('<Double-1>', lambda _: self.open_selected())
        ctk.CTkLabel(self.body, text='Choose a .sm / .ssc / .osu file, or use this folder as a pack.').pack(padx=10)
        ctk.CTkButton(self.body, text='Use selected chart / folder', command=self.choose).pack(fill='x', padx=10, pady=8)
        self.error = ctk.CTkLabel(self.body, text='', text_color='#fb7185');self.error.pack()
        self.refresh()

    def browse_pack(self):
        initial=Path(self.path.get()).expanduser()
        folder=filedialog.askdirectory(parent=self.page.app, title='Choose a chart pack folder',
            initialdir=str(initial if initial.is_dir() else Path.home()), mustexist=True)
        if folder:self.finish(Path(folder))

    def refresh(self):
        path = Path(self.path.get()).expanduser()
        if path.is_file(): self.path.set(str(path.parent));path=path.parent
        try:
            self.items = sorted((p for p in path.iterdir() if p.is_dir() or p.suffix.lower() in ('.sm','.ssc','.osu')), key=lambda p:(not p.is_dir(),p.name.casefold()))
        except OSError as e: self.error.configure(text=str(e));return
        self.tree.delete(*self.tree.get_children())
        for i,p in enumerate(self.items):self.tree.insert('', 'end', iid=str(i), text=('▸ ' if p.is_dir() else '')+p.name)

    def up(self):self.path.set(str(Path(self.path.get()).parent));self.refresh()
    def open_selected(self):
        selection=self.tree.selection()
        if selection:
            path=self.items[int(selection[0])]
            if path.is_dir():self.path.set(str(path));self.refresh()
            else:self.finish(path)
    def choose(self):
        selection=self.tree.selection()
        self.finish(self.items[int(selection[0])] if selection else Path(self.path.get()))
    def finish(self,path):
        if not path.exists():self.error.configure(text='Choose an existing file or folder');return
        self.page.source.set(str(path));self.destroy();self.page.scan()


class ConversionPage(ctk.CTkFrame):
    def __init__(self, app, core):
        super().__init__(app, fg_color=core.BG_MAIN, corner_radius=0)
        self.app,self.core=app,core;self.active=True;self.busy=False;self.q=queue.Queue();self.items=[];self.visible=[]
        self.source=tk.StringVar();self.output=tk.StringVar(value=self.osu_export_folder());self.import_paths=[]
        self.direction=tk.StringVar(value='StepMania → osu!mania');self.search=tk.StringVar()
        self.rate=tk.StringVar(value='1');self.pitch=tk.BooleanVar(value=True);self.od=tk.StringVar(value='8');self.hp=tk.StringVar(value='5');self.meter=tk.StringVar(value='12')
        self.strict=tk.BooleanVar(value=True);self.approximate=tk.BooleanVar(value=False);self.all=tk.BooleanVar(value=False)
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(2,weight=1)
        header=ctk.CTkFrame(self,fg_color='#0c101b',corner_radius=22);header.grid(row=0,column=0,sticky='ew',padx=18,pady=(16,10))
        ctk.CTkButton(header,text='← Back',width=85,corner_radius=16,command=app.back_from_conversion).pack(side='left',padx=12,pady=12)
        ctk.CTkLabel(header,text='StepMania conversion',font=('Poppins',20,'bold')).pack(side='left',padx=10)
        self.direction_selector=ctk.CTkSegmentedButton(header,values=['StepMania → osu!mania','osu!mania → StepMania'],variable=self.direction,command=self.change_direction)
        self.direction_selector.pack(side='right',padx=12)
        paths=ctk.CTkFrame(self,fg_color=core.BG_PANEL,corner_radius=18);paths.grid(row=1,column=0,sticky='ew',padx=18,pady=(0,10));paths.grid_columnconfigure(1,weight=1)
        for row,label,var in ((0,'Chart / pack',self.source),(1,'Output folder',self.output)):
            ctk.CTkLabel(paths,text=label,width=110,anchor='w').grid(row=row,column=0,padx=14,pady=8)
            ctk.CTkEntry(paths,textvariable=var,height=32,corner_radius=14).grid(row=row,column=1,sticky='ew',pady=8)
        self.source_button=ctk.CTkButton(paths,text='Browse…',width=100,command=lambda:SourcePicker(self,self.source_button));self.source_button.grid(row=0,column=2,padx=12)
        self.output_button=ctk.CTkButton(paths,text='Browse…',width=100,command=self.browse_output);self.output_button.grid(row=1,column=2,padx=12)
        ctk.CTkLabel(paths,text='osu!: export .osz files, then open them in osu!. StepMania: select the Songs folder or a pack folder.',text_color='#94a3b8',font=('Poppins',11)).grid(row=2,column=0,columnspan=3,sticky='w',padx=14,pady=(0,10))
        middle=ctk.CTkFrame(self,fg_color='transparent');middle.grid(row=2,column=0,sticky='nsew',padx=18);middle.grid_columnconfigure(0,weight=1);middle.grid_columnconfigure(1,weight=0,minsize=360);middle.grid_rowconfigure(0,weight=1)
        left=ctk.CTkFrame(middle,fg_color=core.BG_PANEL,corner_radius=18);left.grid(row=0,column=0,sticky='nsew',padx=(0,10));left.grid_columnconfigure(0,weight=1);left.grid_rowconfigure(1,weight=1)
        bar=ctk.CTkFrame(left,fg_color='transparent');bar.grid(row=0,column=0,sticky='ew',padx=12,pady=12)
        ctk.CTkEntry(bar,textvariable=self.search,placeholder_text='Search songs, authors or difficulties').pack(side='left',fill='x',expand=True,padx=(0,8))
        self.scan_button=ctk.CTkButton(bar,text='Scan',width=65,command=self.scan);self.scan_button.pack(side='right')
        self.search.trace_add('write',lambda *_:self.refresh())
        self.tree=ttk.Treeview(left,columns=('song','diff','keys','author'),show='headings',selectmode='extended',style='Maps.Treeview')
        for column,title,width in (('song','Song',230),('diff','Difficulty',180),('keys','Lanes',55),('author','Charter',110)):
            self.tree.heading(column,text=title);self.tree.column(column,width=width,minwidth=40)
        self.tree.grid(row=1,column=0,sticky='nsew',padx=12,pady=(0,10));self.tree.bind('<<TreeviewSelect>>',lambda _:self.update_selection())
        scrollbar=ctk.CTkScrollbar(left,command=self.tree.yview);scrollbar.grid(row=1,column=1,sticky='ns',pady=(0,10));self.tree.configure(yscrollcommand=scrollbar.set)
        self.count=ctk.CTkLabel(left,text='Choose a chart file or pack folder.',anchor='w');self.count.grid(row=2,column=0,sticky='ew',padx=14,pady=(0,8))
        right=ctk.CTkScrollableFrame(middle,fg_color=core.BG_PANEL,corner_radius=18,width=340);right.grid(row=0,column=1,sticky='nsew')
        ctk.CTkLabel(right,text='CONVERSION SETTINGS',font=('Poppins',13,'bold'),text_color='#8eb6ff').pack(anchor='w',padx=14,pady=(14,8))
        ctk.CTkCheckBox(right,text='Convert entire scanned pack',variable=self.all,command=self.update_selection).pack(anchor='w',padx=14,pady=8)
        self.input_field(right,'Rate (1 = original)',self.rate)
        ctk.CTkSwitch(right,text='Pitch changes with rate',variable=self.pitch).pack(anchor='w',padx=14,pady=8)
        self.od_input=self.input_field(right,'osu!mania OD (0–10)',self.od);self.hp_input=self.input_field(right,'osu!mania HP (0–10)',self.hp)
        self.meter_input=self.input_field(right,'StepMania difficulty meter (1–99)',self.meter)
        self.meter_input.configure(state='disabled')
        ctk.CTkCheckBox(right,text='Strict sync: maximum 2 ms deviation',variable=self.strict).pack(anchor='w',padx=14,pady=10)
        ctk.CTkCheckBox(right,text='Allow gameplay approximations',variable=self.approximate).pack(anchor='w',padx=14,pady=8)
        ctk.CTkLabel(right,text='Approximations: omit mines, convert rolls to holds and lifts to taps. Pauses/warps keep judgment times in mania, but their scrolling is not identical.\n\nStepMania exports use SSC with per-chart timing. Supported output layouts: 4/5/6/7/8/10K. Other layouts are reported, not merged into fewer lanes.',wraplength=300,justify='left',text_color='#94a3b8',font=('Poppins',11)).pack(fill='x',padx=14,pady=10)
        self.logs_toggle=ctk.CTkButton(right,text='Expand conversion logs ▾',fg_color='#202b40',command=self.toggle_logs);self.logs_toggle.pack(fill='x',padx=14,pady=8)
        self.log=ctk.CTkTextbox(right,height=200,wrap='word',state='disabled');self.logs_open=False
        footer=ctk.CTkFrame(self,fg_color=core.BG_PANEL,corner_radius=18);footer.grid(row=3,column=0,sticky='ew',padx=18,pady=14)
        self.status=ctk.CTkLabel(footer,text='Select one difficulty, Ctrl-click several, or convert the entire pack.',anchor='w',wraplength=950,justify='left');self.status.pack(fill='x',padx=14,pady=(10,4))
        self.progress=ctk.CTkProgressBar(footer,height=8);self.progress.pack(fill='x',padx=14,pady=6);self.progress.set(0)
        self.build_button=ctk.CTkButton(footer,text='Convert charts',height=42,corner_radius=18,command=self.build,state='disabled');self.build_button.pack(fill='x',padx=14,pady=(6,12))
        self.import_button=ctk.CTkButton(footer,text='Open osu! export',command=self.open_osu_export)
        self._job=self.after(100,self.poll)

    @staticmethod
    def osu_export_folder():
        downloads=Path.home()/'Downloads'
        return str(downloads if downloads.is_dir() else Path.home())

    def open_osu_export(self):
        if not self.import_paths:return
        paths=[Path(name) for name in self.import_paths if Path(name).is_file()]
        if not paths:
            self.status.configure(text='The .osz files have moved or already been imported.')
            return
        try:
            os.startfile(str(paths[0] if len(paths)==1 else paths[0].parent))
            if len(paths)>1:self.status.configure(text='Drag the exported .osz files from this folder into osu!.')
        except OSError as error:
            self.status.configure(text=f'Open the .osz files from the output folder in osu!: {error}')

    def input_field(self,parent,label,var):
        row=ctk.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',padx=14,pady=6)
        ctk.CTkLabel(row,text=label,anchor='w').pack(side='left')
        entry=ctk.CTkEntry(row,textvariable=var,width=65);entry.pack(side='right')
        return entry
    def kind(self):return 'sm_to_osu' if self.direction.get().startswith('StepMania') else 'osu_to_sm'
    def change_direction(self,*_):
        if self.busy:return
        self.od_input.configure(state='normal' if self.kind()=='sm_to_osu' else 'disabled')
        self.hp_input.configure(state='normal' if self.kind()=='sm_to_osu' else 'disabled')
        self.meter_input.configure(state='disabled' if self.kind()=='sm_to_osu' else 'normal')
        self.items=[];self.refresh()
        self.import_button.pack_forget();self.import_paths=[]
        self.output.set(self.osu_export_folder() if self.kind()=='sm_to_osu' else '')
        self.status.configure(text='Choose the source chart / pack and destination folder, then Scan.')
    def browse_output(self):FolderPicker(self.app,self.output_button,self.output.get(),self.output.set)
    def scan(self):
        if self.busy:return
        self.busy=True;self.controls();self.status.configure(text='Scanning charts…')
        path=self.source.get();direction=self.kind()
        def work():
            try:self.q.put(('scan',*catalog(self.core,path,direction)))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def refresh(self):
        text=self.search.get().casefold();self.visible=[m for m in self.items if text in ' '.join(str(m.get(k,'')) for k in ('title','artist','creator','version')).casefold()]
        self.tree.delete(*self.tree.get_children())
        for i,m in enumerate(self.visible):self.tree.insert('','end',iid=str(i),values=(f"{m['artist']} - {m['title']}",m['version'],m['keys'],m['creator']))
        self.count.configure(text=f'{len(self.items)} difficulties scanned · {len(self.visible)} shown')
        self.update_selection()
    def selected(self):return list(self.items) if self.all.get() else [self.visible[int(i)] for i in self.tree.selection()]
    def update_selection(self):
        selected=self.selected()
        self.build_button.configure(text=f'Convert {len(selected)} chart(s)' if selected else 'Convert charts',state='normal' if selected and not self.busy else 'disabled')
    def controls(self):
        self.direction_selector.configure(state='disabled' if self.busy else 'normal')
        self.scan_button.configure(state='disabled' if self.busy else 'normal');self.source_button.configure(state='disabled' if self.busy else 'normal')
        self.update_selection()
    def append_log(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def toggle_logs(self):
        self.logs_open=not self.logs_open
        if self.logs_open:self.log.pack(fill='x',padx=14,pady=(0,12))
        else:self.log.pack_forget()
        self.logs_toggle.configure(text='Collapse conversion logs ▴' if self.logs_open else 'Expand conversion logs ▾')
    def build(self):
        if self.busy:return
        try:
            values=dict(rate=float(self.rate.get()),pitch=self.pitch.get(),od=float(self.od.get()),hp=float(self.hp.get()),meter=int(self.meter.get()),strict=self.strict.get(),approximate=self.approximate.get(),ffmpeg=self.app.ffmpeg)
        except ValueError:self.status.configure(text='Rate, OD, HP and meter must be valid numbers.');return
        entries=self.selected();direction=self.kind();output=self.output.get()
        self.busy=True;self.controls();self.progress.set(0);self.progress.configure(progress_color=self.core.ACCENT)
        self.import_button.pack_forget();self.import_paths=[]
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled')
        def work():
            try:self.q.put(('done',convert(self.core,entries,output,direction,report=lambda p,s:self.q.put(('progress',p,s)),**values)))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                msg=self.q.get_nowait();kind=msg[0]
                if kind=='scan':
                    self.items=msg[1];self.busy=False;self.refresh();self.controls()
                    for error in msg[2]:self.append_log('Scan error: '+error)
                    self.status.configure(text=f'{len(self.items)} difficulties found; {len(msg[2])} file(s) could not be read.')
                elif kind=='progress':self.progress.set(msg[1]);self.status.configure(text=msg[2]);self.append_log(msg[2])
                elif kind=='done':
                    result=msg[1];self.busy=False;self.controls();self.progress.set(1);self.progress.configure(progress_color='#34d399' if result['charts'] else '#fb7185')
                    for path in result['paths']:self.append_log('Output: '+path)
                    for warning in result['warnings']:self.append_log('Note: '+warning)
                    for failure in result['failures']:self.append_log('Rejected: '+failure)
                    self.status.configure(text=f"Converted {result['charts']} chart(s) into {len(result['paths'])} export(s); {len(result['failures'])} rejected.")
                    if self.kind()=='sm_to_osu' and result['paths']:
                        self.import_paths=result['paths']
                        if os.name=='nt':
                            self.import_button.configure(text='Open in osu!' if len(self.import_paths)==1 else 'Open export folder')
                            self.import_button.pack(fill='x',padx=14,pady=(0,12))
                        self.status.configure(text=self.status.cget('text')+' Open the .osz files in osu! to import them.')
                    if (result['warnings'] or result['failures']) and not self.logs_open:self.toggle_logs()
                elif kind=='error':
                    self.busy=False;self.controls();self.progress.configure(progress_color='#fb7185');self.status.configure(text=msg[1]);self.append_log('Error: '+msg[1])
                    if not self.logs_open:self.toggle_logs()
        except queue.Empty:pass
        self._job=self.after(100,self.poll)
    def destroy(self):
        if getattr(self,'_job',None):self.after_cancel(self._job)
        super().destroy()
