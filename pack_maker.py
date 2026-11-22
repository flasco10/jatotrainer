"""Separate Pack maker window; shares jatotrainer's selection/detection backend."""
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from pack_backend import build_pack, parse_rates, validate_settings, background_path, audio_bitrate
from PIL import Image, ImageDraw, ImageOps, ImageTk


class Popover(ctk.CTkFrame):
    """In-app panel beside its trigger, flipped left when the right edge is full."""
    def __init__(self,app,anchor,title,width=500,height=460):
        previous=getattr(app,'_active_popover',None)
        if previous is not None and previous.winfo_exists():previous.destroy()
        super().__init__(app,fg_color='#151c2e',border_width=1,border_color='#46516c',corner_radius=16)
        self.app,self.anchor=app,anchor
        app._active_popover=self
        app.update_idletasks()
        scale=self._get_widget_scaling()
        available_w=app.winfo_width();available_h=app.winfo_height()
        actual_w=min(int(width*scale),available_w-24);actual_h=min(int(height*scale),available_h-24)
        self.configure(width=actual_w/scale,height=actual_h/scale)
        self.pack_propagate(False)
        bar=ctk.CTkFrame(self,fg_color='transparent');bar.pack(fill='x',padx=12,pady=(10,4))
        ctk.CTkLabel(bar,text=title,font=ctk.CTkFont(size=16,weight='bold')).pack(side='left')
        ctk.CTkButton(bar,text='×',width=30,height=28,fg_color='#30394d',command=self.destroy).pack(side='right')
        self.body=ctk.CTkScrollableFrame(self,fg_color='transparent',corner_radius=0)
        self.body.pack(fill='both',expand=True,padx=6,pady=(0,10))
        ax=anchor.winfo_rootx()-app.winfo_rootx();ay=anchor.winfo_rooty()-app.winfo_rooty()
        x=ax+anchor.winfo_width()+8
        if x+actual_w>available_w-12:x=ax-actual_w-8
        x=max(12,min(x,available_w-actual_w-12));y=max(12,min(ay,available_h-actual_h-12))
        self.place(x=x/scale,y=y/scale)
        self.lift()

    def destroy(self):
        if getattr(self.app,'_active_popover',None) is self:self.app._active_popover=None
        super().destroy()


class FolderPicker(Popover):
    """Folder selection stays inside the app instead of opening an OS dialog."""
    def __init__(self,app,anchor,initial,callback):
        super().__init__(app,anchor,'Choose Songs folder',width=500,height=470)
        self.callback=callback
        self.path=tk.StringVar(value=initial if initial and os.path.isdir(initial) else os.path.expanduser('~'))
        self.path_entry=ctk.CTkEntry(self.body,textvariable=self.path)
        self.path_entry.pack(fill='x',padx=10,pady=6)
        self.path_entry.bind('<Return>',lambda _:self.refresh())
        bar=ctk.CTkFrame(self.body,fg_color='transparent');bar.pack(fill='x',padx=10)
        ctk.CTkButton(bar,text='↑ Up',width=70,command=self.up).pack(side='left')
        ctk.CTkButton(bar,text='Open path',width=110,command=self.refresh).pack(side='right')
        if os.name=='nt':
            drives=[f'{chr(letter)}:/'+'' for letter in range(65,91) if os.path.isdir(f'{chr(letter)}:/')]
            if drives:ctk.CTkOptionMenu(bar,values=drives,width=90,command=self.drive).pack(side='left',padx=8)
        self.list=ttk.Treeview(self.body,show='tree',height=8,style='Maps.Treeview',selectmode='browse')
        self.list.pack(fill='x',padx=10,pady=10)
        self.list.bind('<Double-1>',lambda _:self.open_selected())
        self.list.bind('<Return>',lambda _:self.open_selected())
        self.error=ctk.CTkLabel(self.body,text='',text_color='#fb7185',wraplength=430);self.error.pack()
        ctk.CTkLabel(self.body,text='Double-click a folder to open it, or enter its path.',text_color='#94a3b8',wraplength=430).pack()
        ctk.CTkButton(self.body,text='Use this folder',command=self.choose).pack(pady=8)
        self.refresh()

    def refresh(self):
        folder=os.path.abspath(os.path.expanduser(self.path.get().strip()))
        try:
            children=sorted((entry.name for entry in os.scandir(folder) if entry.is_dir()),key=str.casefold)
        except OSError as e:self.error.configure(text=str(e));return
        self.path.set(folder);self.error.configure(text='')
        self.list.delete(*self.list.get_children())
        for i,name in enumerate(children):self.list.insert('','end',iid=str(i),text=name,values=(os.path.join(folder,name),))

    def up(self):self.path.set(os.path.dirname(self.path.get()));self.refresh()
    def drive(self,path):self.path.set(path);self.refresh()
    def open_selected(self):
        selected=self.list.selection()
        if selected:self.path.set(self.list.item(selected[0],'values')[0]);self.refresh()
    def choose(self):
        folder=os.path.abspath(os.path.expanduser(self.path.get().strip()))
        if not os.path.isdir(folder):self.error.configure(text='Choose an existing folder.');return
        self.destroy();self.callback(folder)


class PackSetup(Popover):
    def __init__(self,app):
        super().__init__(app,app.pack_btn,'New pack',width=500,height=440)
        self.name=tk.StringVar();self.creator=tk.StringVar(value=app.cfg.get('pack_creator',''))
        self.od=tk.StringVar(value='8');self.hp=tk.StringVar(value='8')
        ctk.CTkLabel(self.body,text='Create a chart pack',font=ctk.CTkFont(size=24,weight='bold')).pack(pady=(20,10))
        for label,var in [('Pack name',self.name),('Pack creator',self.creator)]:
            ctk.CTkLabel(self.body,text=label,anchor='w').pack(fill='x',padx=24)
            ctk.CTkEntry(self.body,textvariable=var).pack(fill='x',padx=24,pady=(0,8))
        ctk.CTkLabel(self.body,text='Folder: Various Artists - <pack name>',text_color='#94a3b8').pack()
        row=ctk.CTkFrame(self.body,fg_color='transparent');row.pack(pady=8)
        for label,var in [('OD (0–10)',self.od),('HP (0–10)',self.hp)]:
            ctk.CTkLabel(row,text=label).pack(side='left',padx=6)
            ctk.CTkEntry(row,textvariable=var,width=60).pack(side='left',padx=6)
        self.error=ctk.CTkLabel(self.body,text='',text_color='#fb7185',wraplength=470);self.error.pack(padx=20)
        ctk.CTkButton(self.body,text='Open Pack maker',command=self.submit).pack(pady=8)

    def submit(self):
        import sys
        core=sys.modules[self.app.__class__.__module__]
        try:
            name,creator,od,hp,folder=validate_settings(core,self.name.get(),self.creator.get(),self.od.get(),self.hp.get())
            if self.app.songs_dir and os.path.exists(os.path.join(self.app.songs_dir,folder)):
                raise ValueError('That pack folder already exists. Choose another name.')
        except ValueError as e:self.error.configure(text=str(e));return
        self.destroy()
        self.app.pack_window=PackMaker(self.app,core,name,creator,od,hp)
        self.app.show_pack_page(self.app.pack_window)


class PackMaker(ctk.CTkFrame):
    # Overridden by the marathon maker, which reuses this page's chart browser.
    TITLE='Pack maker';CARDS_LABEL='Charts in pack · edit rates per chart';BUILD_TEXT='Create pack'
    RATES_DEFAULT='1';RATES_HINT='Rates: 1 = original; e.g. 1, 1.1, 1.25';ADD_TEXT='Add chart';ARTIST_OPTIONS=True;SETTINGS_PREFIX='Pack'

    def __init__(self,app,core,name,creator,od,hp):
        super().__init__(app, fg_color=core.BG_MAIN)
        self.app,self.core=app,core
        self.active=True
        self.configure(fg_color=core.BG_MAIN)
        self.q=queue.Queue();self.busy=False;self.detecting=False;self.maps=list(app.maps);self.entries=[];self.selected=None
        self.grid_columnconfigure(0,weight=1);self.grid_columnconfigure(1,weight=1);self.grid_rowconfigure(2,weight=1)
        header=ctk.CTkFrame(self,fg_color=core.BG_PANEL);header.grid(row=0,column=0,columnspan=2,sticky='ew',padx=16,pady=12)
        self.back_button=ctk.CTkButton(header,text='‹ Back',width=80,command=app.back_from_pack)
        self.back_button.pack(side='left',padx=(12,0))
        ctk.CTkLabel(header,text=self.TITLE,font=ctk.CTkFont(size=24,weight='bold')).pack(side='left',padx=16,pady=12)
        self.name=tk.StringVar(value=name);self.creator=tk.StringVar(value=creator)
        for label,var in [('Name',self.name),('Creator',self.creator)]:
            ctk.CTkLabel(header,text=label).pack(side='left',padx=8)
            ctk.CTkEntry(header,textvariable=var,width=180).pack(side='left')
        settings=ctk.CTkFrame(self,fg_color='transparent');settings.grid(row=1,column=0,columnspan=2,sticky='ew',padx=16)
        self.settings_row=settings
        self.od=tk.StringVar(value=format(od,'g'));self.hp=tk.StringVar(value=format(hp,'g'))
        self.various=tk.BooleanVar(value=False);self.include_artist=tk.BooleanVar(value=False);self.quality=tk.StringVar(value='Original');self.backgrounds_8bit=tk.BooleanVar(value=False)
        for label,var in [(self.SETTINGS_PREFIX+' OD',self.od),(self.SETTINGS_PREFIX+' HP',self.hp)]:
            ctk.CTkLabel(settings,text=label).pack(side='left',padx=8)
            ctk.CTkEntry(settings,textvariable=var,width=60).pack(side='left')
        if self.ARTIST_OPTIONS:ctk.CTkSwitch(settings,text='Various Artists',variable=self.various).pack(side='left',padx=16)
        self.compression_button=ctk.CTkButton(settings,text='Compression ⚙',width=150,command=self.compression_options)
        self.compression_button.pack(side='right',padx=8)
        self.include_artist_switch=ctk.CTkSwitch(settings,text='Include artist in diffname',variable=self.include_artist)
        self.various.trace_add('write',lambda *_:self.artist_options_visibility())
        self.artist_options_visibility()
        self.left=ctk.CTkFrame(self,fg_color=core.BG_PANEL);self.left.grid(row=2,column=0,sticky='nsew',padx=(16,8),pady=12)
        self.left.grid_columnconfigure(0,weight=1);self.left.grid_rowconfigure(3,weight=1)
        browse=ctk.CTkFrame(self.left,fg_color='transparent');browse.grid(row=0,column=0,sticky='ew',padx=12,pady=10)
        self.songs=tk.StringVar(value=app.songs_dir or '')
        ctk.CTkEntry(browse,textvariable=self.songs,width=250).pack(side='left',fill='x',expand=True)
        self.songs_button=ctk.CTkButton(browse,text='Songs…',width=75,command=self.browse)
        self.songs_button.pack(side='left',padx=4)
        ctk.CTkButton(browse,text='Scan',width=55,command=self.scan).pack(side='left')
        self.search=tk.StringVar();self.search.trace_add('write',lambda *_:self.refresh())
        ctk.CTkEntry(self.left,textvariable=self.search,placeholder_text='Search artist, title, difficulty, charter').grid(row=1,column=0,sticky='ew',padx=12)
        detect=ctk.CTkFrame(self.left,fg_color='transparent');detect.grid(row=2,column=0,sticky='ew',padx=12,pady=8)
        ctk.CTkButton(detect,text='Detect from osu!',command=self.detect).pack(side='left')
        self.follow=tk.BooleanVar(value=False)
        ctk.CTkSwitch(detect,text='Follow osu!',variable=self.follow).pack(side='left',padx=12)
        tf=ctk.CTkFrame(self.left,fg_color='transparent');tf.grid(row=3,column=0,sticky='nsew',padx=12,pady=4)
        self.tree=ttk.Treeview(tf,columns=('title','diff','charter'),show='headings',style='Maps.Treeview',selectmode='browse')
        for col,text in [('title','Song'),('diff','Difficulty'),('charter','Charter')]:self.tree.heading(col,text=text);self.tree.column(col,width=140)
        sb=ctk.CTkScrollbar(tf,command=self.tree.yview);self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left',fill='both',expand=True);sb.pack(side='right',fill='y')
        self.tree.bind('<<TreeviewSelect>>',self.choose)
        # Double-click or Enter adds the highlighted chart at the rate in the box.
        self.tree.bind('<Double-1>',lambda _:(self.choose(),self.add()))
        self.tree.bind('<Return>',lambda _:(self.choose(),self.add()))
        self.card=ChartCard(self.left,self,None,preview=True)
        self.card.grid(row=4,column=0,sticky='ew',padx=16,pady=6)
        addrow=ctk.CTkFrame(self.left,fg_color='transparent');addrow.grid(row=5,column=0,sticky='ew',padx=12,pady=(0,12))
        self.rates=tk.StringVar(value=self.RATES_DEFAULT)
        ctk.CTkEntry(addrow,textvariable=self.rates,width=170).pack(side='left')
        ctk.CTkButton(addrow,text=self.ADD_TEXT,command=self.add).pack(side='left',padx=8)
        ctk.CTkLabel(self.left,text=self.RATES_HINT,text_color='#94a3b8').grid(row=6,column=0,pady=(0,8))
        self.cards=ctk.CTkScrollableFrame(self,fg_color=core.BG_PANEL,label_text=self.CARDS_LABEL)
        self.cards.grid(row=2,column=1,sticky='nsew',padx=(8,16),pady=12);self.cards.grid_columnconfigure(0,weight=1)
        footer=ctk.CTkFrame(self,fg_color=core.BG_PANEL);footer.grid(row=3,column=0,columnspan=2,sticky='ew',padx=16,pady=(0,12))
        self.build_button=ctk.CTkButton(footer,text=self.BUILD_TEXT,height=40,command=self.build);self.build_button.pack(fill='x',padx=12,pady=10)
        self.progress=ctk.CTkProgressBar(footer,progress_color=core.ACCENT);self.progress.set(0);self.progress.pack(fill='x',padx=12)
        self.status=ctk.CTkLabel(footer,text='Output: Various Artists - '+name,wraplength=1050);self.status.pack(padx=12,pady=6)
        self.refresh();self._poll_job=self.after(100,self.poll);self._follow_job=self.after(1000,self.follow_tick)
        if not self.maps and self.songs.get():self.scan()

    def done_message(self,path,count):
        return f'Created {count} charts in {path} · Refresh osu! with F5.'

    def artist_options_visibility(self):
        if self.various.get():
            self.include_artist_switch.pack(side='left',padx=8,before=self.compression_button)
        else:
            self.include_artist_switch.pack_forget()

    def destroy(self):
        for name in ('_poll_job','_follow_job'):
            job=getattr(self,name,None)
            if job:
                try:self.after_cancel(job)
                except tk.TclError:pass
        super().destroy()

    def close(self):
        if self.busy:self.status.configure(text='Pack creation is running. Close this window after it finishes.');return
        self.destroy()

    def browse(self):
        def chosen(folder):
            self.songs.set(self.core.normalize_songs_dir(folder) or folder);self.scan()
        FolderPicker(self.app,self.songs_button,self.songs.get(),chosen)

    def scan(self):
        if self.busy:return
        songs=self.core.normalize_songs_dir(self.songs.get());self.songs.set(songs or '')
        if not songs:self.status.configure(text='Choose a valid Songs folder.');return
        self.busy=True;self.build_button.configure(state='disabled');self.status.configure(text='Scanning Songs…')
        def work():
            try:self.q.put(('maps',self.core.scan_songs(songs)[0]))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def refresh(self):
        words=self.search.get().lower().split()
        self.visible=[m for m in self.maps if not m.get('gen') and all(w in ' '.join(str(m.get(k,'')) for k in ('artist','title','version','creator')).lower() for w in words)][:self.core.LIST_LIMIT]
        self.tree.delete(*self.tree.get_children())
        added=self.added_paths()
        for i,m in enumerate(self.visible):self.tree.insert('','end',iid=str(i),values=(self.list_title(m,added),m['version'],m['creator']))

    def added_paths(self):
        return {e['info']['path'] for e in self.entries}

    @staticmethod
    def list_title(m,added):
        return ('✓ ' if m['path'] in added else '')+m['title']

    def mark_added(self):
        """Tick charts already in the list without rebuilding it (keeps the selection)."""
        added=self.added_paths()
        for i,m in enumerate(getattr(self,'visible',[])):
            if self.tree.exists(str(i)):self.tree.set(str(i),'title',self.list_title(m,added))

    def choose(self,_=None):
        selection=self.tree.selection()
        if selection:
            self.selected=self.visible[int(selection[0])]
            self.card.set_info(self.selected)

    def select(self,m):
        if not m:return False
        if m not in self.visible:self.search.set(m['title']);self.refresh()
        if m in self.visible:
            index=str(self.visible.index(m));self.tree.selection_set(index);self.tree.see(index);self.choose();return True
        return False

    def detect(self,quiet=False):
        if self.busy or self.detecting:return
        self.detecting=True
        def work():
            try:
                sel=self.core.current_selection();match=None
                if sel:match,_=self.core.match_selection(self.maps,sel,self.songs.get())
                self.q.put(('detect',match,quiet))
            except Exception:
                self.q.put(('detect',None,quiet))
        threading.Thread(target=work,daemon=True).start()

    def follow_tick(self):
        if self.active and self.follow.get():self.detect(True)
        self._follow_job=self.after(1500,self.follow_tick)

    def add(self):
        if self.busy or not self.selected:return
        try:parse_rates(self.rates.get())
        except ValueError as e:self.status.configure(text=str(e));return
        if any(e['info']['path']==self.selected['path'] for e in self.entries):self.status.configure(text='Already added. Edit its rates on the right.');return
        info=dict(self.selected)
        try:
            _,sections=self.core.parse_osu(info['path']);meta=self.core.sec(sections,'Metadata')
            artist=self.core.kv(meta,'Artist') or info.get('artist','?')
            original_unicode=self.core.kv(meta,'ArtistUnicode')
            artist_unicode=original_unicode if original_unicode is not None else artist
            tags=self.core.kv(meta,'Tags') or ''
        except OSError:
            artist=artist_unicode=info.get('artist','?');tags=''
        entry=dict(info=info,rates=tk.StringVar(value=self.rates.get()),pitch=True,options=dict(diffname=f"{info['title']} [{info['creator']}]",artist=artist,artist_unicode=artist_unicode,tags=tags))
        self.entries.append(entry);self.render_entries()

    def remove(self,entry):
        if not self.busy:self.entries.remove(entry);self.render_entries()

    def render_entries(self):
        self.mark_added()
        for child in self.cards.winfo_children():child.destroy()
        for i,entry in enumerate(self.entries):
            card=ChartCard(self.cards,self,entry)
            card.grid(row=i,column=0,sticky='ew',padx=6,pady=6)
            entry['card']=card

    def toggle_pitch(self,entry):
        if self.busy:return
        entry['pitch']=not entry['pitch']
        entry['card'].pitch_button.configure(fg_color=self.core.ACCENT if entry['pitch'] else '#424752')

    def edit_chart(self,entry):
        if self.busy:return
        ChartOptions(self,entry)

    def compression_options(self):
        if self.busy:return
        window=Popover(self.app,self.compression_button,'Compression',width=500,height=330)
        ctk.CTkLabel(window.body,text='Compression',font=ctk.CTkFont(size=22,weight='bold')).pack(pady=14)
        ctk.CTkLabel(window.body,text='Audio quality · bitrate capped at each source').pack()
        ctk.CTkOptionMenu(window.body,variable=self.quality,values=['Original','128 kbps','160 kbps','192 kbps','224 kbps','256 kbps','320 kbps']).pack(pady=10)
        ctk.CTkSwitch(window.body,text='Make backgrounds 8-bit color (256 colors)',variable=self.backgrounds_8bit).pack(pady=10)
        ctk.CTkLabel(window.body,text='Original copies audio unchanged at rate 1. Rate audio uses\nthe source bitrate up to MP3’s 320 kbps maximum.\n8-bit backgrounds use indexed PNG; file sizes may vary.',text_color='#94a3b8',wraplength=490).pack(pady=8)
        ctk.CTkButton(window.body,text='Done',command=window.destroy).pack()

    def build(self):
        if self.busy:return
        try:
            settings=validate_settings(self.core,self.name.get(),self.creator.get(),self.od.get(),self.hp.get())
            charts=[(dict(e['info']),parse_rates(e['rates'].get()),dict(e['options'],pitch=e['pitch'])) for e in self.entries]
            if not charts:raise ValueError('Add at least one chart.')
            songs=self.core.normalize_songs_dir(self.songs.get())
            if not songs:raise ValueError('Choose your Songs folder.')
            if os.path.exists(os.path.join(songs,settings[4])):raise ValueError('Pack folder already exists. Choose a different name.')
        except ValueError as e:self.status.configure(text=str(e));return
        name,creator,od,hp,_=settings
        various=self.various.get();include_artist=various and self.include_artist.get();quality=self.quality.get();eightbit=self.backgrounds_8bit.get()
        self.app.cfg['pack_creator']=creator;self.core.save_json(self.core.CONFIG_PATH,self.app.cfg)
        self.busy=True;self.build_button.configure(state='disabled');self.progress.configure(progress_color=self.core.ACCENT);self.progress.set(0)
        self.status.configure(text='Preparing pack…')
        def work():
            try:
                path,count=build_pack(self.core,songs,name,creator,od,hp,charts,self.app.ffmpeg,report=lambda p,s:self.q.put(('progress',p,s)),various_artists=various,audio_quality=quality,backgrounds_8bit=eightbit,include_artist_in_diffname=include_artist)
                self.q.put(('done',path,count))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            while True:
                msg=self.q.get_nowait()
                if msg[0]=='maps':self.maps=msg[1];self.busy=False;self.build_button.configure(state='normal');self.refresh();self.status.configure(text=f'{len(self.maps)} charts scanned.')
                elif msg[0]=='detect':
                    self.detecting=False
                    if msg[1] and not msg[1].get('gen'):self.select(msg[1])
                    elif not msg[2]:self.status.configure(text='No matching chart detected. Start osu!stable and select a chart. tosu also works as a fallback.')
                elif msg[0]=='bitrate':
                    if msg[1].winfo_exists():msg[1].bitrate_label.configure(text=f'Source audio: {msg[2]} kbps' if msg[2] else 'Source audio bitrate unavailable')
                elif msg[0]=='progress':self.progress.set(msg[1]);self.status.configure(text=msg[2])
                elif msg[0]=='done':
                    self.busy=False;self.build_button.configure(state='normal');self.progress.set(1);self.progress.configure(progress_color='#34d399')
                    self.status.configure(text=self.done_message(msg[1],msg[2]))
                elif msg[0]=='error':
                    self.busy=False;self.build_button.configure(state='normal');self.progress.configure(progress_color='#fb7185');self.status.configure(text=msg[1])
        except queue.Empty:pass
        self._poll_job=self.after(100,self.poll)


class CanvasButton:
    """A button painted directly over the card image, with no opaque Tk backing."""
    def __init__(self,card,text,color,command):
        self.card,self.text,self.color,self.command=card,text,color,command
        self.bounds=(0,0,0,0)
        self.tag='button'+str(id(self))

    def cget(self,key):
        if key=='fg_color':return self.color
        if key=='text':return self.text
        raise KeyError(key)

    def configure(self,**kwargs):
        self.color=kwargs.get('fg_color',self.color)
        self.text=kwargs.get('text',self.text)
        self.card.draw()

    def draw(self,x,y,width,height):
        c=self.card.canvas;r=7;x2=x+width;y2=y+height
        self.bounds=(x,y,width,height)
        self.shape=c.create_polygon(x+r,y,x2-r,y,x2,y,x2,y+r,x2,y2-r,x2,y2,x2-r,y2,
            x+r,y2,x,y2,x,y2-r,x,y+r,x,y,smooth=True,fill=self.color,outline='',tags=self.tag)
        c.create_text(x+width/2,y+height/2,text=self.text,fill='white',font=('Poppins',10),tags=self.tag)
        c.tag_bind(self.tag,'<Button-1>',lambda _:self.command())
        c.tag_bind(self.tag,'<Enter>',lambda _:(c.configure(cursor='hand2'),c.itemconfigure(self.shape,fill='#60718d' if self.color=='#424752' else '#619cff')))
        c.tag_bind(self.tag,'<Leave>',lambda _:(c.configure(cursor=''),c.itemconfigure(self.shape,fill=self.color)))

    def winfo_rootx(self):return self.card.canvas.winfo_rootx()+self.bounds[0]
    def winfo_rooty(self):return self.card.canvas.winfo_rooty()+self.bounds[1]
    def winfo_width(self):return self.bounds[2]
    def winfo_height(self):return self.bounds[3]
    def winfo_exists(self):return self.card.winfo_exists()


class ChartCard(ctk.CTkFrame):
    """Compact image card with buttons drawn over the background."""
    def __init__(self,parent,pack,entry,preview=False):
        super().__init__(parent,fg_color='#171d30',corner_radius=16)
        from ui_components import TextCanvas
        self.pack,self.entry,self.preview=pack,entry,preview
        self.info=entry['info'] if entry else None
        self.background=None
        self.canvas=TextCanvas(self,height=76 if preview else 118,bg='#171d30',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        if not preview:
            self.gear_button=CanvasButton(self,'⚙','#424752',lambda:pack.edit_chart(entry))
            self.pitch_button=CanvasButton(self,'Pitch',pack.core.ACCENT if entry['pitch'] else '#424752',lambda:pack.toggle_pitch(entry))
            self.remove_button=CanvasButton(self,'Remove','#424752',lambda:pack.remove(entry))
            self.rates_entry=ctk.CTkEntry(self.canvas,textvariable=entry['rates'],width=190,bg_color='#171d30')
        self.set_info(self.info)

    def set_info(self,info):
        self.info=info;self.background=None
        if info:
            try:
                path=background_path(self.pack.core,info)
                if path:
                    with Image.open(path) as image:self.background=image.convert('RGB')
            except (OSError,ValueError):pass
        self.draw()

    def short_title(self,text,width):
        from tkinter import font
        f=font.Font(family='Poppins',size=13,weight='bold')
        lines=['']
        for word in text.split():
            candidate=(lines[-1]+' '+word).strip()
            if f.measure(candidate)>width and lines[-1]:
                if len(lines)==2:
                    lines[-1]+='…';break
                lines.append(word)
            else:lines[-1]=candidate
        for i,line in enumerate(lines):
            if f.measure(line)>width:
                while line and f.measure(line+'…')>width:line=line[:-1]
                lines[i]=line+'…'
        return '\n'.join(lines)

    def draw(self):
        c=self.canvas;w=max(280,c.winfo_width());h=76 if self.preview else 118
        c.delete('all')
        image=Image.new('RGB',(w,h),'#171d30')
        if self.background is not None:
            image=ImageOps.fit(self.background,(w,h),method=Image.Resampling.LANCZOS)
            image=Image.blend(image,Image.new('RGB',(w,h),'#111322'),.6)
        mask=Image.new('L',(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=16,fill=255)
        image.putalpha(mask);self.image=ImageTk.PhotoImage(image)
        c.create_image(0,0,image=self.image,anchor='nw')
        info=self.info
        title=self.short_title(info['title'] if info else 'Choose a chart',w-(115 if not self.preview else 28))
        c.create_text(14,8,text=title,fill='white',anchor='nw',font=('Poppins',13,'bold'))
        c.create_text(14,49,text='By '+info['creator'] if info else '',fill='white',anchor='nw',font=('Poppins',10))
        if not self.preview:
            self.gear_button.draw(w-45,10,31,26)
            self.pitch_button.draw(w-92,47,78,26)
            self.remove_button.draw(w-92,85,78,26)
            c.create_text(14,98,text='Rates',fill='white',anchor='w',font=('Poppins',10))
            self.rates_entry.configure(width=max(100,min(190,w-175)))
            c.create_window(65,98,window=self.rates_entry,anchor='w')


class ChartOptions(Popover):
    def __init__(self,pack,entry):
        super().__init__(pack.app,entry['card'].gear_button,'Chart options',width=500,height=520)
        self.pack,self.entry=pack,entry
        ctk.CTkLabel(self.body,text=entry['info']['title'],font=ctk.CTkFont(size=18,weight='bold'),wraplength=560).pack(pady=12)
        self.vars={}
        for key,label in [('diffname','Diffname (rate suffix added automatically)'),('artist','Artist'),('artist_unicode','ArtistUnicode'),('tags','Tags')]:
            var=tk.StringVar(value=entry['options'].get(key,''));self.vars[key]=var
            ctk.CTkLabel(self.body,text=label,anchor='w').pack(fill='x',padx=20)
            ctk.CTkEntry(self.body,textvariable=var).pack(fill='x',padx=20,pady=(0,6))
        self.artist_mode=tk.StringVar(value='Pack default' if 'various_artists' not in entry['options'] else 'Various Artists' if entry['options']['various_artists'] else 'Use chart fields')
        ctk.CTkOptionMenu(self.body,variable=self.artist_mode,values=['Pack default','Use chart fields','Various Artists']).pack(pady=8)
        self.bitrate_label=ctk.CTkLabel(self.body,text='Reading source audio bitrate…',text_color='#94a3b8');self.bitrate_label.pack()
        self.error=ctk.CTkLabel(self.body,text='',text_color='#fb7185');self.error.pack()
        ctk.CTkButton(self.body,text='Save chart options',command=self.save).pack(pady=8)
        def probe():
            try:
                _,sections=pack.core.parse_osu(entry['info']['path'])
                filename=pack.core.kv(pack.core.sec(sections,'General'),'AudioFilename')
                from pack_backend import safe_source
                from pathlib import Path
                bitrate=audio_bitrate(pack.app.ffmpeg,safe_source(Path(entry['info']['path']).resolve().parent,filename))
                pack.q.put(('bitrate',self,bitrate))
            except Exception:pack.q.put(('bitrate',self,None))
        threading.Thread(target=probe,daemon=True).start()

    def save(self):
        if self.pack.busy:self.error.configure(text='Wait for pack creation to finish.');return
        values={k:v.get().strip() for k,v in self.vars.items()}
        if any(not values[k] for k in ('diffname','artist')) or any('\n' in v or '\r' in v for v in values.values()):
            self.error.configure(text='Enter nonempty, single-line metadata.');return
        self.entry['options'].update(values)
        mode=self.artist_mode.get()
        if mode=='Pack default':self.entry['options'].pop('various_artists',None)
        else:self.entry['options']['various_artists']=mode=='Various Artists'
        self.destroy()
