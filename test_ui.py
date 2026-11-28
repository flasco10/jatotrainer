"""Real-widget UI checks: run in a desktop session or under xvfb-run."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import jatotrainer as j

@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Desktop display unavailable')
class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.config_patch=patch.object(j,'CONFIG_PATH',str(Path(self.tmp.name)/'config.json'))
        self.config_patch.start()
        Path(j.CONFIG_PATH).write_text('{"setup_complete": true, "follow_osu": false}')
        with patch.object(j,'find_songs_folder',return_value=None), patch.object(j,'find_ffmpeg',return_value=None), patch.object(j.App,'show_ffmpeg_setup'):
            self.app=j.App()
            # Fully transparent but still mapped: real layout for the checks, nothing flashes on screen.
            # Set JATO_SHOW_TEST_WINDOWS=1 to watch the tests run.
            if not os.environ.get('JATO_SHOW_TEST_WINDOWS'):
                self.app.attributes('-alpha', 0.0)
            self.app.update()
    def tearDown(self):
        # Stop Tk timers before destroying widgets.
        for job in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", job)
        self.app.destroy()
        # Free the destroyed app's Tk fonts here; if a later test's worker thread collects them, it blocks on Tk.
        import gc; gc.collect()
        self.config_patch.stop()
        self.tmp.cleanup()
    def pump(self):
        until=time.monotonic()+.6
        while time.monotonic()<until:
            self.app.update()
            time.sleep(.01)
    def test_rate_presets_slider_and_ignored_input(self):
        a=self.app
        self.assertEqual(j.QUICK_RATES[0],'0.8');self.assertEqual(j.QUICK_RATES[-1],'2');self.assertIn('1.65',j.QUICK_RATES)
        self.assertEqual(max(b.grid_info()['row'] for b in a.chip_btns.values()),2)
        a.rates_var.set('1.1');a._on_rate_slider(1.6499999);a.add_slider_rate();a.add_slider_rate()
        self.assertEqual(a.rates_var.get(),'1.1, 1.65')
        a._on_rate_slider(1.0);a.add_slider_rate()
        self.assertEqual(a.rates_var.get(),'1.1, 1.65')
        a.rates_var.set('1.2, abc, 7, 1')
        self.assertEqual(a.parse_rates(),[1.2])
        self.assertIn('abc, 7, 1',a.rates_warning.cget('text'))
        a.rates_var.set('1.2, 1.3')
        self.assertEqual(a.rates_warning.cget('text'),'')
    def test_bitrate_defaults_to_192_and_warns_above(self):
        self.assertEqual(self.app._bitrate(),192)
        self.assertEqual(self.app.bitrate_warning.cget('text'),'')
        self.app.bitrate_var.set('320 kbps')
        self.assertEqual(self.app._bitrate(),320)
        self.assertIn('Bancho',self.app.bitrate_warning.cget('text'))
    def test_converter_follows_when_main_follow_is_off(self):
        from test_generation import MAP
        a=self.app
        chart=Path(self.tmp.name)/'chart.osu'
        chart.write_text(MAP)
        a.maps=[j.read_header_info(str(chart))]
        a._latest_osu_selection=dict(path=str(chart),folder=None,file=None,songs=None,bid=0,
                                     artist=None,title=None,mapper=None,version=None,md5=None)
        a.open_conversion();page=a.conversion_page
        page.direction.set('osu!mania → StepMania')
        try:
            with patch.object(a,'update_follow_worker'):
                page.change_direction()
            self.assertTrue(page.follows_osu())
            self.assertFalse(a.follow_var.get())
            self.assertEqual(page.selected()[0]['path'],str(chart))
            self.assertEqual(page.tree.cget('columns'),('song','diff','author'))
        finally:a.back_from_conversion()

    def test_compact_mode_controls_geometry_and_return(self):
        a = self.app
        a.selected = dict(path='sample.osu', title='Song', artist='Artist', creator='Charter', version='Hard', bpm=180, od='8', keys=4)
        a.fmt_var.set('{diff} x{rate} [{bpm}]')
        a.on_options_changed()
        before = a.geometry()
        with patch.object(j, 'current_selection', return_value=None):
            a.enter_compact(); a.update()
            c = a.compact
            self.assertTrue(a.follow_var.get())
            self.assertEqual((a.winfo_width(), a.winfo_height()), (300, 500))
            self.assertTrue(c.create.winfo_ismapped())
            self.assertLessEqual(c.create.winfo_rooty()+c.create.winfo_height(), a.winfo_rooty()+500)
            self.assertGreater(c.status.winfo_rooty(), c.pitch.winfo_rooty()+c.pitch.winfo_height())
            self.assertGreater(c.progress.winfo_rooty(), c.create.winfo_rooty()+c.create.winfo_height())
            self.assertLessEqual(c.status.winfo_rooty()+c.status.winfo_height(), c.create.winfo_rooty())
            self.assertEqual(list(c.rate_buttons), [n/100 for n in range(80,141,5)])
            self.assertEqual(c.rate.cget('number_of_steps'), 150)
            existing = a.rates_var.get()
            c.set_rate(1.27); c.refresh()
            self.assertEqual(c.rate_label.cget('text'), '1.27×')
            self.assertEqual(a.rates_var.get(), existing)
            c.add_slider_rate(); c.add_slider_rate()
            self.assertEqual(a.parse_rates().count(1.27), 1)
            c.toggle_rate(.8)
            self.assertIn(.8, a.parse_rates())
            c.toggle_rate(.8)
            self.assertNotIn(.8, a.parse_rates())
            a.busy = True; a.gen_btn.configure(state='disabled'); c.refresh()
            self.assertEqual(c.create.cget('text'), '')
            self.assertEqual(c.create.cget('state'), 'disabled')
            a.busy = False; a.on_options_changed(); c.refresh()
            self.assertEqual(c.create.cget('text'), 'Create map')
            a.rates_var.set(''); c.set_rate(1.3); c.add_slider_rate(); c.set_od(7.5); c.set_hp(6); c.refresh(); a.update()
            self.assertIn('234', c.bpm.cget('text'))
            self.assertEqual(a.fmt_var.get(), '{diff} x{rate} [{bpm}]')
            self.assertEqual(a._od_override(), 7.5)
            self.assertEqual(c.hp_value, 6)
            old = a.pitch_var.get(); c.toggle_pitch()
            self.assertNotEqual(a.pitch_var.get(), old)
            with patch.object(j, 'generate', return_value=[]) as generate:
                a.on_generate(); self.pump()
                self.assertEqual(generate.call_args.args[-1], 6)
                self.assertEqual(generate.call_args.args[2], '{diff} x{rate} [{bpm}]')
            a.exit_compact(); a.update()
        self.assertFalse(a.compact_active)
        self.assertFalse(a.follow_var.get())
        self.assertEqual(a.geometry(), before)
        self.assertTrue(a.compact_btn.winfo_ismapped())

    def test_compact_create_button_writes_real_chart_and_reports_repeats(self):
        import shutil, wave
        from test_generation import MAP
        ff = shutil.which('ffmpeg')
        if not ff: self.skipTest('FFmpeg unavailable')
        a = self.app; folder = Path(self.tmp.name)/'Songs'/'Set'; folder.mkdir(parents=True)
        chart = folder/'source.osu'; chart.write_text(MAP.split('[Events]')[0] + '[Events]\n[TimingPoints]\n0,500,4,2,0,100,1,0\n[HitObjects]\n64,192,1000,1,0,0:0:0:0:\n')
        with wave.open(str(folder/'audio.wav'), 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(44100)
            audio.writeframes(b'\0'*(44100*4))
        a.ffmpeg = ff; a.maps = [j.read_header_info(str(chart))]; a.songs_dir = str(folder.parent)
        a.refresh_list()
        with patch.object(j, 'current_selection', return_value=None), patch.object(j, 'AUDIO_CACHE_PATH', str(Path(self.tmp.name)/'audio-cache.json')):
            a.select_map(a.maps[0]); a.update(); a.rates_var.set('1.25')
            a.enter_compact(); a.update(); c = a.compact
            c.set_od(7.5); c.set_hp(6); c.refresh()
            self.assertEqual(c.create.cget('state'), 'normal')
            for run in range(2):
                c.create.invoke()
                deadline = time.monotonic() + 10
                while a.busy and time.monotonic() < deadline: a.update(); time.sleep(.01)
                self.assertFalse(a.busy)
                self.assertEqual(len(a.last_outputs), 1)
                self.assertEqual(a.last_outputs[0]['created'], run == 0)
                output = Path(a.last_outputs[0]['path'])
                self.assertTrue(output.is_file())
                _, sections = j.parse_osu(str(output))
                self.assertIn('1.25', j.kv(j.sec(sections,'Metadata'),'Version'))
                self.assertEqual(j.kv(j.sec(sections,'Difficulty'),'HPDrainRate'), '6')
                self.assertEqual(j.kv(j.sec(sections,'Difficulty'),'OverallDifficulty'), '7.5')
                self.assertTrue((folder/j.kv(j.sec(sections,'General'),'AudioFilename')).is_file())
                self.assertNotIn(b'\r\r\n', output.read_bytes())
            self.assertEqual(len(a.maps), 2)
            self.assertIn('already exist', a.status.cget('text'))
            c.refresh(); panel = c.show_details(); a.update()
            self.assertIs(panel.winfo_toplevel(), a)
            a.exit_compact(); a.update()
            self.assertFalse(panel.winfo_exists())

    def test_compact_rescan_and_new_follow_selection_refresh_index(self):
        from test_generation import MAP
        a = self.app; songs = Path(self.tmp.name)/'Songs'; folder = songs/'Set'; folder.mkdir(parents=True)
        chart = folder/'new.osu'; chart.write_text(MAP.replace('Title:T', 'Title:New chart'))
        a.songs_dir = str(songs)
        with patch.object(j, 'current_selection', return_value=None), patch.object(j, 'CACHE_PATH', str(Path(self.tmp.name)/'scan-cache.json')):
            a.enter_compact(); a.update()
            with patch.object(j, 'scan_songs', wraps=j.scan_songs) as scan:
                a.compact.rescan.invoke(); self.pump()
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(len(a.maps), 1)
                second = folder/'second.osu'; second.write_text(MAP.replace('Title:T', 'Title:Second chart').replace('BeatmapID:42','BeatmapID:43'))
                a.q.put(('follow', dict(path=str(second), folder='Set', file='second.osu', songs=str(songs), bid=43, artist='A', title='Second chart', mapper='C', version='Hard', md5=None)))
                self.pump()
                self.assertEqual(scan.call_count, 2)
                self.assertEqual(a.selected['path'], str(second))
                self.assertEqual(len(a.maps), 2)
            a.exit_compact()

    def test_compact_bpm_list_and_stable_rescan_polling(self):
        a = self.app
        a.selected = dict(path='sample.osu', title='Song', artist='Artist', creator='Charter', version='Hard', bpm=171, od='8', keys=4)
        a.rates_var.set('0.95, 1.05, 1.1'); a.on_options_changed()
        with patch.object(j, 'current_selection', return_value=None):
            a.enter_compact(); a.update(); c = a.compact
            self.assertEqual(c.bpm.cget('text'), 'Base 171 BPM  →  New 162, 180, 188 BPM')
            c.set_rate(1.27)
            self.assertIn('162, 180, 188', c.bpm.cget('text'))
            c.toggle_rate(1.1)
            self.assertIn('New 162, 180 BPM', c.bpm.cget('text'))
            c.add_slider_rate()
            self.assertIn('New 162, 180, 217 BPM', c.bpm.cget('text'))
            position = (c.rescan.winfo_rootx(), c.rescan.winfo_rooty(), c.rescan.winfo_width())
            with patch.object(c.rescan, 'configure', wraps=c.rescan.configure) as configure:
                for _ in range(20): c.refresh(); a.update_idletasks()
                configure.assert_not_called()
            self.assertEqual(position, (c.rescan.winfo_rootx(), c.rescan.winfo_rooty(), c.rescan.winfo_width()))
            a.rates_var.set(', '.join(str(n/100) for n in range(80,141,5))); c.refresh(); a.update()
            self.assertLessEqual(c.status.winfo_rooty()+c.status.winfo_height(), c.create.winfo_rooty())
            a.exit_compact()

    def test_conversion_page_scan_convert_and_embedded_back(self):
        from simfile.ssc import SSCSimfile, SSCChart
        from conversion_ui import SourcePicker
        import wave
        a=self.app; folder=Path(self.tmp.name)/'SM';folder.mkdir();output=Path(self.tmp.name)/'Output';output.mkdir()
        with wave.open(str(folder/'audio.wav'),'wb') as audio:
            audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(44100);audio.writeframes(b'\0'*(44100*4))
        song=SSCSimfile.blank();song['TITLE']='Test song';song['ARTIST']='Artist';song['MUSIC']='audio.wav';song['BPMS']='0=120';song['OFFSET']='0'
        for i in range(2):
            chart=SSCChart.blank();chart['CHARTNAME']=f'Hard {i}';chart['CREDIT']='Charter';chart['NOTES']='1000\n0100\n0010\n0001';song.charts.append(chart)
        (folder/'song.ssc').write_bytes(str(song).encode())
        a.conversion_btn.invoke();a.update();page=a.conversion_page
        self.assertTrue(page.winfo_ismapped())
        self.assertFalse(a.sidebar_btn.winfo_ismapped())
        picker=SourcePicker(page,page.source_button);a.update()
        self.assertIs(picker.winfo_toplevel(),a)
        with patch('conversion_ui.filedialog.askdirectory',return_value=''):
            picker.browse_pack()
        self.assertTrue(picker.winfo_exists());self.assertEqual(page.source.get(),'')
        page.output.set(str(output))
        with patch('conversion_ui.filedialog.askdirectory',return_value=str(folder)) as browse:
            picker.browse_pack()
        self.assertIs(browse.call_args.kwargs['parent'],a)
        self.assertEqual(page.source.get(),str(folder));self.pump()
        self.assertEqual(len(page.items),2)
        page.all.set(True);page.update_selection();page.build_button.invoke()
        deadline=time.monotonic()+5
        while page.busy and time.monotonic()<deadline:a.update();time.sleep(.01)
        self.assertFalse(page.busy)
        from zipfile import ZipFile
        archives=list(output.glob('*.osz'))
        self.assertEqual(len(archives),1)
        with ZipFile(archives[0]) as archive:
            self.assertEqual(sum(name.endswith('.osu') for name in archive.namelist()),2)
        self.assertIn('Converted 2',page.status.cget('text'))
        self.assertEqual(page.progress.cget('progress_color'),'#34d399')
        a.back_from_conversion();a.update()
        self.assertTrue(a.sidebar_btn.winfo_ismapped())
        a.open_conversion();a.update();self.assertIs(a.conversion_page,page)
        a.back_from_conversion();page.destroy()

    def test_pack_maker_setup_and_per_chart_rates(self):
        from pack_maker import PackMaker
        a=self.app
        self.assertLess(a.pack_btn.winfo_rootx(),a.sidebar_btn.winfo_rootx())
        a.open_pack_maker();a.update()
        setup=a.pack_window
        setup.name.set('Chordjack Pack');setup.creator.set('flasco');setup.submit();a.update()
        pack=a.pack_window
        self.assertIsInstance(pack,PackMaker)
        self.assertFalse(pack.include_artist.get())
        self.assertFalse(pack.include_artist_switch.winfo_ismapped())
        pack.various.set(True);a.update()
        self.assertTrue(pack.include_artist_switch.winfo_ismapped())
        pack.various.set(False);a.update()
        self.assertFalse(pack.include_artist_switch.winfo_ismapped())
        pack.selected=dict(path='sample.osu',title='Song',artist='Artist',creator='Charter',version='Hard')
        pack.rates.set('1, 1.3');pack.add();a.update()
        self.assertEqual(len(pack.entries),1)
        self.assertEqual(pack.entries[0]['rates'].get(),'1, 1.3')
        entry=pack.entries[0]
        self.assertEqual(entry['card'].pitch_button.cget('fg_color'),j.ACCENT)
        pack.toggle_pitch(entry)
        self.assertFalse(entry['pitch'])
        self.assertEqual(entry['card'].pitch_button.cget('fg_color'),'#424752')
        pack.entries[0]['rates'].set('0.95, 1.25')
        self.assertEqual(pack.entries[0]['rates'].get(),'0.95, 1.25')
        pack.remove(pack.entries[0]);self.assertEqual(pack.entries,[])
        a.back_from_pack();a.update()
        self.assertTrue(a.sidebar_btn.winfo_ismapped())
        self.assertFalse(pack.winfo_ismapped())
        a.open_pack_maker();a.update()
        self.assertTrue(pack.winfo_ismapped())
        pack.destroy()

    def test_pack_background_card_and_cog_metadata(self):
        from PIL import Image
        from pack_maker import ChartOptions
        a=self.app;folder=Path(self.tmp.name)
        Image.new('RGB',(80,40),'red').save(folder/'bg.png')
        chart=folder/'chart.osu'
        chart.write_text('osu file format v14\n[General]\nMode:3\nAudioFilename:audio.mp3\n[Metadata]\nArtist:A\nArtistUnicode:アーティスト\nCreator:C\nTitle:T\nVersion:Hard\n[Events]\n0,0,"bg.png",0,0\n')
        a.open_pack_maker();a.update();setup=a.pack_window
        setup.name.set('Test');setup.creator.set('Pack creator');setup.submit();a.update();pack=a.pack_window
        pack.selected=dict(path=str(chart),title='T',creator='C',artist='A',version='Hard')
        pack.add();a.update();entry=pack.entries[0]
        self.assertEqual(entry['card'].background.getpixel((0,0)),(255,0,0))
        dialog=ChartOptions(pack,entry);a.update()
        dialog.vars['diffname'].set('Edited name');dialog.vars['artist'].set('Edited artist');dialog.save()
        self.assertEqual(entry['options']['diffname'],'Edited name')
        self.assertEqual(entry['options']['artist'],'Edited artist')
        a.back_from_pack();pack.destroy()

    def test_marathon_maker_songs_order_and_collage(self):
        from PIL import Image
        from marathon_maker import MarathonMaker
        a=self.app;folder=Path(self.tmp.name)
        charts=[]
        for name,color,last in [('One','red',60000),('Two','blue',60000),('Long','green',120000)]:
            Image.new('RGB',(160,90),color).save(folder/f'{name}.png')
            path=folder/f'{name}.osu'
            lines=['osu file format v14','[General]','Mode:3','AudioFilename:a.mp3','[Metadata]',f'Title:{name}','Creator:C','Version:Hard',
                   '[Difficulty]','CircleSize:4','[Events]',f'0,0,"{name}.png",0,0','[HitObjects]','64,192,0,1,0,0:0:0:0:',f'64,192,{last},1,0,0:0:0:0:']
            path.write_text(chr(10).join(lines)+chr(10))
            charts.append(dict(path=str(path),title=name,creator='C',artist='A',version='Hard'))
        a.open_marathon_maker();a.update()
        setup=a.marathon_window;setup.name.set('Marathon');setup.creator.set('Me');setup.submit();a.update()
        m=a.marathon_window;self.assertIsInstance(m,MarathonMaker)
        for info in charts:m.selected=info;m.add()
        m.rates.set('1.2');m.selected=charts[0];m.add();a.update()
        self.assertEqual([e['info']['title'] for e in m.entries],['One','Two','Long','One'])
        self.assertEqual(m.entries[3]['rate'].get(),'1.2')
        self.assertEqual(m.layout_inputs()[0],[1,1,2,1])  # the 2-minute song gets a double slot
        m.entries[0]['weight'].set('3');m.entries[1]['row'].set('2')
        self.assertEqual(m.layout_inputs(),([3,1,2,1],[None,2,None,None]))
        m.auto_layout();self.assertEqual(m.layout_inputs(),([1,1,2,1],[None,None,None,None]))
        m.move(m.entries[2],-1);self.assertEqual([e['info']['title'] for e in m.entries],['One','Long','Two','One'])
        m.draw_preview();a.update()
        self.assertIn('4 songs',m.total_label.cget('text'))
        self.assertEqual(m.per_row_value(),4);m.per_row.set('All in one row');self.assertIsNone(m.per_row_value())
        m.per_row.set('4');m.draw_preview();a.update()
        from types import SimpleNamespace as E
        ed=m.preview_canvas;centre=lambda i:(ed.rects[i][0]+ed.rects[i][2]//2,ed.rects[i][1]+ed.rects[i][3]//2)
        # Dragging a tile right pans its picture right (focus moves toward the left edge).
        x,y=centre(0);ed.press(E(x=x,y=y));self.assertEqual(m.selected_tile,0)
        ed.motion(E(x=x+30,y=y));ed.release(E(x=x+30,y=y))
        self.assertLess(m.focus_values()[0][0],0.5)
        ed.wheel(E(x=x,y=y,delta=120));self.assertGreater(m.focus_values()[0][2],1.0)
        ed.double(E(x=x,y=y));self.assertEqual(m.focus_values()[0],(0.5,0.5,1.0))
        # The top bar is the move zone; the rest of the tile is the pan zone.
        bx,by=ed.rects[0][0]+10,ed.rects[0][1]+10;tx,ty=centre(2)
        self.assertEqual(ed.zone_at(bx,by),(0,'handle'));self.assertEqual(ed.zone_at(tx,ty),(2,'pan'))
        ed.hover_move(E(x=bx,y=by));self.assertEqual(ed.cget('cursor'),'hand2')
        # Dragging tile 1's bar onto tile 3 moves that song to position 3 (play order too).
        cards={id(e):e['card'] for e in m.entries}
        ed.press(E(x=bx,y=by));ed.motion(E(x=tx,y=ty))
        self.assertEqual(ed.target,2);self.assertIsNotNone(ed.preview_rects)  # new order shown before the drop
        ed.release(E(x=tx,y=ty))
        self.assertEqual([e['info']['title'] for e in m.entries],['Long','Two','One','One'])
        self.assertEqual(m.selected_tile,2)
        # Reordering reuses the song cards (rebuilding them froze the UI for ~1 s) and renumbers them.
        self.assertTrue(all(e['card'] is cards[id(e)] for e in m.entries))
        self.assertEqual([e['card'].number.cget('text') for e in m.entries],['1','2','3','4'])
        # Panning never reorders, even when the mouse ends up over another tile.
        m.draw_preview();a.update()  # the move's scheduled redraw
        x,y=centre(1);tx,ty=centre(3)
        ed.press(E(x=x,y=y));ed.motion(E(x=tx,y=ty));ed.release(E(x=tx,y=ty))
        self.assertEqual([e['info']['title'] for e in m.entries],['Long','Two','One','One'])
        self.assertNotEqual(m.focus_values()[1][0],0.5)
        hx,hy=centre(1);ed.hover_move(E(x=hx,y=hy));self.assertEqual((ed.hover,ed.hover_zone),(1,'pan'))
        self.assertEqual(ed.cget('cursor'),'sb_h_double_arrow')  # this tile only has room to pan sideways
        ed.hover_move(E(x=centre(2)[0],y=centre(2)[1]));self.assertEqual(ed.cget('cursor'),'arrow')  # exact fit: nothing to pan
        m.set_image(0,str(folder/'One.png'));self.assertEqual(m.entries[0]['image'],str(folder/'One.png'))
        self.assertEqual(m.entries[0]['thumb'].getpixel((0,0)),(255,0,0))
        m.set_image(0,None);self.assertIsNone(m.entries[0]['image'])
        big=m.open_editor();a.update();self.assertEqual(len(big.rects),4)
        a._active_popover.destroy();a.update()
        m.select_tile(3);ed.event_generate('<Delete>');self.assertEqual(len(m.entries),3)  # Delete removes the selected song
        # The song list ticks charts already added; double-click adds the highlighted one.
        m.maps=[dict(c,gen=False) for c in charts];m.search.set('');a.update()
        self.assertTrue(m.tree.set('0','title').startswith('✓ '))
        m.tree.selection_set('2');m.tree.focus_set();m.tree.event_generate('<Return>');self.assertEqual(len(m.entries),4)  # same handler as double-click
        # Name and bitrate are on the page; bitrates above 192 warn inline.
        self.assertTrue(m.compression_button.winfo_manager()=='' )
        m.bitrate.set('320 kbps');self.assertIn('192',m.bitrate_warning.cget('text'))
        m.bitrate.set('192 kbps');self.assertEqual(m.bitrate_warning.cget('text'),'')
        m.remove(m.entries[3]);self.assertEqual(len(m.entries),3)
        # One break value for every gap; songs added later start with it.
        m.default_break.set('5');m.apply_break_to_all()
        self.assertEqual({e['brk'].get() for e in m.entries},{'5'})
        m.default_break.set('-1');m.apply_break_to_all();self.assertIn('0–600',m.status.cget('text'))
        self.assertEqual({e['brk'].get() for e in m.entries},{'5'})
        m.default_break.set('2.5');m.apply_break_to_all();m.selected=charts[1];m.add()
        self.assertEqual(m.entries[-1]['brk'].get(),'2.5');m.remove(m.entries[-1])
        m.entries[0]['brk'].set('abc');m.build();self.assertIn('must be numbers',m.status.cget('text'))
        a.back_from_pack();a.update()
        self.assertFalse(m.winfo_ismapped());self.assertTrue(a.sidebar_btn.winfo_ismapped())
        a.open_marathon_maker();a.update();self.assertTrue(m.winfo_ismapped())
        a.back_from_pack();m.destroy()

    def test_side_popovers_and_folder_selection_stay_inside_app(self):
        from pack_maker import FolderPicker, Popover
        a=self.app;selected=[]
        popup=FolderPicker(a,a.pack_btn,self.tmp.name,selected.append);a.update()
        self.assertIs(popup.winfo_toplevel(),a)
        self.assertGreaterEqual(popup.winfo_rootx(),a.winfo_rootx())
        self.assertLessEqual(popup.winfo_rootx()+popup.winfo_width(),a.winfo_rootx()+a.winfo_width())
        popup.choose();self.assertEqual(selected,[self.tmp.name])
        a.open_pack_maker();a.update();setup=a.pack_window
        self.assertIs(setup.winfo_toplevel(),a)
        setup.name.set('Test');setup.creator.set('Creator');setup.submit();a.update();pack=a.pack_window
        pack.compression_options();a.update()
        self.assertIsInstance(a._active_popover,Popover)
        self.assertIs(a._active_popover.winfo_toplevel(),a)
        a.back_from_pack();a.update()
        self.assertIsNone(a._active_popover)
        pack.destroy()

    def test_fixed_od_default_and_card_update(self):
        a=self.app
        self.assertTrue(a.od_override_enabled.get())
        a.selected=dict(title='Title',creator='Mapper',version='Hard',keys=4,bpm=174,od='9')
        a.od_override_value.set('7.5');a.update()
        def texts():
            return [a.chart_canvas.itemcget(item,'text') for item in a.chart_canvas.find_all()
                    if a.chart_canvas.type(item)=='text']
        self.assertIn('OD 7.5',texts())
        a.od_override_enabled.set(False);a.update()
        self.assertIn('OD 9',texts())
        for fmt,expected in (('{diff} x{rate} [{bpm}]','Hard x1.3 [226]'),('{diff} x{rate}','Hard x1.3')):
            self.assertIn(fmt,j.FORMAT_PRESETS)
            self.assertEqual(j.format_version(fmt,'Hard',1.3,174,'7.5'),expected)

    def test_convert_and_progress_stay_visible_while_scrolling(self):
        a=self.app
        a.geometry('1080x780');a.update()
        y=a.gen_btn.winfo_rooty()
        a.workspace._parent_canvas.yview_moveto(1);a.update()
        self.assertEqual(a.gen_btn.winfo_rooty(),y)
        self.assertLess(a.progress.winfo_rooty()+a.progress.winfo_height(),a.winfo_rooty()+a.winfo_height())
        a.workspace._parent_canvas.yview_moveto(0);a.update()
        self.assertEqual(a.gen_btn.winfo_rooty(),y)

    def test_background_loaded_from_events(self):
        from PIL import Image
        a=self.app
        folder=Path(self.tmp.name)
        Image.new('RGB',(100,50),'red').save(folder/'chart bg.png')
        chart=folder/'chart.osu'
        chart.write_text('osu file format v14\n[General]\nMode:3\n[Events]\n0,0,"chart bg.png",0,0\n')
        a.maps=[dict(path=str(chart),artist='A',title='Title',creator='C',version='Hard',keys=4,bpm=174,od='8',gen=False)]
        a.refresh_list();a.tree.selection_set('0');a.on_select();a.update()
        self.assertEqual(a.background_image.size,(100,50))
        self.assertEqual(a.background_image.getpixel((0,0)),(255,0,0))

    def test_manual_rate_tiles_and_od_validation(self):
        a=self.app
        a.rates_var.set('0.95, 1.25, 1.7');a.update()
        texts=[a.chart_canvas.itemcget(item,'text') for item in a.chart_canvas.find_all()
               if a.chart_canvas.type(item)=='text']
        for rate in ('0.95','1.25','1.7'): self.assertIn(rate,texts)
        a.od_override_enabled.set(True);a.od_override_value.set('7.5')
        self.assertEqual(a._od_override(),7.5)
        a.od_override_value.set('11')
        self.assertEqual(a.gen_btn.cget('state'),'disabled')

    def test_sidebar_search_and_selection_survive_toggle(self):
        a=self.app
        a.search_entry.insert(0,'sample query')
        a.tree.insert('', 'end', iid='sample', values=('Sample','Hard','Mapper','4K',180))
        a.tree.selection_set('sample')
        # Avoid triggering a map-selection callback for the synthetic tree item.
        a.tree.unbind('<<TreeviewSelect>>')
        a.toggle_sidebar(); a.update()
        self.assertFalse(a.sidebar.winfo_ismapped())
        self.assertEqual(a.grid_columnconfigure(0)['minsize'],0)
        self.assertEqual(a.sidebar_btn.cget('text'),'Expand sidebar')
        self.assertTrue(a.detect_btn.winfo_ismapped())
        a.toggle_sidebar(); a.update()
        self.assertTrue(a.sidebar.winfo_ismapped())
        self.assertEqual(a.search_entry.get(),'sample query')
        self.assertEqual(a.tree.selection(),('sample',))
    def test_logs_expand_downward_without_losing_content(self):
        a=self.app
        self.assertFalse(a.log.winfo_ismapped())
        a._log('conversion detail')
        a.toggle_logs();a.update()
        self.assertTrue(a.log.winfo_ismapped())
        self.assertGreater(a.log.winfo_rooty(), a.logs_btn.winfo_rooty())
        self.assertIn('conversion detail',a.log.get('1.0','end'))
        a.toggle_logs();a.update()
        self.assertFalse(a.log.winfo_ismapped())
    def test_progress_finished_error_and_reset(self):
        a=self.app
        a.q.put(('prog',.5));self.pump()
        self.assertAlmostEqual(a.progress.get(),.5)
        a.q.put(('done',2));self.pump()
        self.assertEqual(a.progress.get(),1)
        self.assertEqual(a.progress.cget('progress_color'),'#34d399')
        a._set_progress(0)
        self.assertEqual(a.progress.cget('progress_color'),j.ACCENT)
        self.assertEqual(a.progress.get(),0)
        a.q.put(('error','test error'));self.pump()
        self.assertEqual(a.progress.cget('progress_color'),'#fb7185')
        self.assertTrue(a.log.winfo_ismapped())
    def test_window_brand_and_controls_inside_minimum_size(self):
        a=self.app
        self.assertEqual(a.title(),'jatotrainer')
        a.geometry('1080x780');a.toggle_logs();a.update()
        a.workspace._parent_canvas.yview_moveto(1);a.update()
        for widget in [a.sidebar_btn,a.detect_btn,a.compact_btn,a.conversion_btn,a.gen_btn,a.progress,a.log,a.status]:
            self.assertGreater(widget.winfo_width(),0)
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),a.winfo_rootx()+a.winfo_width()+1)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),a.winfo_rooty()+a.winfo_height()+1)

if __name__=='__main__': unittest.main()
