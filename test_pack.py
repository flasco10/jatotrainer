"""Pack export integration tests use real chart rewriting and temporary files."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from test_generation import m as core, MAP
from pack_backend import build_pack,parse_rates


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.songs=self.root/'Songs';self.songs.mkdir()
        self.source=self.songs/'source';self.source.mkdir()
        (self.source/'audio.wav').write_bytes(b'original audio')
        (self.source/'bg.jpg').write_bytes(b'background')
        self.chart=self.source/'chart.osu'
        self.chart.write_text(MAP.replace('[Events]\n','[Events]\n0,0,"bg.jpg",0,0\n').split('Sprite,')[0]+'[TimingPoints]\n0,500,4,2,0,100,1,0\n[HitObjects]\n64,192,1000,1,0,0:0:0:0:\n192,192,2000,128,0,3000:0:0:0:0:\n')
        self.info=dict(path=str(self.chart),title='T',creator='C')
        self.original=self.chart.read_bytes()
    def tearDown(self):self.tmp.cleanup()
    def export(self,entries=None,name='Chordjack Pack'):
        return build_pack(core,str(self.songs),name,'flasco',7.5,6,entries or [(self.info,[1])],'fake')
    def test_original_three_files_and_metadata(self):
        path,count=self.export();folder=pathlib.Path(path)
        self.assertEqual(folder.name,'Various Artists - Chordjack Pack');self.assertEqual(count,1)
        self.assertEqual(len(list(folder.iterdir())),3)
        chart=next(folder.glob('*.osu'));_,sections=core.parse_osu(str(chart))
        md=core.sec(sections,'Metadata');general=core.sec(sections,'General');difficulty=core.sec(sections,'Difficulty')
        for key,value in dict(Title='Chordjack Pack',TitleUnicode='Chordjack Pack',Artist='A',ArtistUnicode='A',Creator='flasco',Version='T [C]',BeatmapID='0',BeatmapSetID='-1').items():self.assertEqual(core.kv(md,key),value)
        self.assertIn('[T [C]]',chart.name)
        self.assertEqual(core.kv(general,'AudioFilename'),'T.wav')
        self.assertEqual((folder/'T.wav').read_bytes(),b'original audio')
        self.assertIn('0,0,"T.jpg",0,0',core.sec(sections,'Events'))
        self.assertEqual(core.kv(difficulty,'OverallDifficulty'),'7.5');self.assertEqual(core.kv(difficulty,'HPDrainRate'),'6')
        self.assertEqual(core.sec(sections,'HitObjects')[-1],'192,192,2000,128,0,3000:0:0:0:0:')
        self.assertEqual(self.chart.read_bytes(),self.original)
    def test_rates_timing_audio_and_unicode(self):
        def audio(ff,src,dst,rate,pitch,**kwargs):pathlib.Path(dst).write_bytes(b'converted')
        with patch.object(core,'make_audio',side_effect=audio), patch('pack_backend.audio_bitrate',return_value=320):path,count=self.export([(self.info,[1,1.25])],name='Coração Pack')
        folder=pathlib.Path(path);self.assertEqual(count,2)
        rate_chart=next(p for p in folder.glob('*.osu') if 'x1.25' in p.name)
        _,sections=core.parse_osu(str(rate_chart));md=core.sec(sections,'Metadata')
        self.assertEqual(core.kv(md,'Title'),'Coracao Pack');self.assertEqual(core.kv(md,'TitleUnicode'),'Coração Pack')
        self.assertEqual(core.kv(md,'Version'),'T [C] x1.25')
        self.assertEqual(core.kv(core.sec(sections,'General'),'PreviewTime'),'1600')
        self.assertEqual(core.sec(sections,'HitObjects')[-1],'192,192,1600,128,0,2400:0:0:0:0:')
        self.assertEqual((folder/'T x1.25.mp3').read_bytes(),b'converted')
    def test_rate_export_preserves_crlf_spacing_and_single_background(self):
        import csv
        # A Windows-style input with a comment before its background: the old
        # text-mode temporary write doubled CRLF and shifted background indices.
        source = self.chart.read_text().replace('[Events]\n', '[Events]\n//Background and Video events\n').replace('[TimingPoints]', '//Break Periods\n2,1000,2000\n[TimingPoints]')
        self.chart.write_bytes(source.replace('\n', '\r\n').encode())
        original = self.chart.read_bytes()
        def audio(ff, src, dst, rate, pitch, **kwargs):
            pathlib.Path(dst).write_bytes(b'converted')
        with patch.object(core, 'make_audio', side_effect=audio), patch('pack_backend.audio_bitrate', return_value=320), patch.object(pathlib.Path, 'write_text', side_effect=AssertionError('Chart serialization must not pass through a text-mode temporary file')):
            path, count = self.export([(self.info, [1, .9, 1.1])])
        self.assertEqual(count, 3)
        folder = pathlib.Path(path)
        for chart in folder.glob('*.osu'):
            data = chart.read_bytes()
            self.assertNotIn(b'\r\r\n', data)
            self.assertNotIn(b'[General]\r\n\r\n', data)
            self.assertNotIn(b'[HitObjects]\r\n\r\n', data)
            self.assertNotIn(b'\r\n\r\nAudioLeadIn:', data)
            self.assertNotIn(b'\r\n\r\nOverallDifficulty:', data)
            _, sections = core.parse_osu(str(chart))
            events = core.sec(sections, 'Events')
            self.assertIn('//Background and Video events', events)
            backgrounds = [next(csv.reader([line])) for line in events if line.startswith(('0,', 'Background,'))]
            self.assertEqual(len(backgrounds), 1)
            self.assertEqual(backgrounds[0][2], 'T.jpg')
            self.assertTrue((folder/backgrounds[0][2]).is_file())
            rate = 1.1 if 'x1.1' in chart.name else .9 if 'x0.9' in chart.name else 1
            self.assertIn(f'2,{core.tm("1000", rate)},{core.tm("2000", rate)}', events)
            objects = core.sec(sections, 'HitObjects')
            self.assertTrue(all(line.strip() for line in objects))
            self.assertEqual(len(objects), 2)
        self.assertEqual(len(list(folder.glob('*.jpg'))), 1)
        self.assertEqual(self.chart.read_bytes(), original)

    def test_collisions_keep_references_valid(self):
        second=self.source/'second.osu';second.write_bytes(self.original)
        info=dict(self.info,path=str(second))
        path,count=self.export([(self.info,[1]),(info,[1])]);folder=pathlib.Path(path)
        self.assertEqual(len(list(folder.glob('*.osu'))),2)
        for file in folder.glob('*.osu'):
            _,sections=core.parse_osu(str(file));md=core.sec(sections,'Metadata')
            self.assertIn('['+core.kv(md,'Version')+']',file.name)
            self.assertTrue((folder/core.kv(core.sec(sections,'General'),'AudioFilename')).exists())
    def test_failed_conversion_leaves_no_pack(self):
        with patch.object(core,'make_audio',side_effect=RuntimeError('FFmpeg failed')), patch('pack_backend.audio_bitrate',return_value=320):
            with self.assertRaises(RuntimeError):self.export([(self.info,[1.3])])
        self.assertFalse((self.songs/'Various Artists - Chordjack Pack').exists())
        self.assertEqual(self.chart.read_bytes(),self.original)
    def test_existing_folder_preserved(self):
        folder=self.songs/'Various Artists - Chordjack Pack';folder.mkdir();(folder/'keep').write_text('unchanged')
        with self.assertRaises(ValueError):self.export()
        self.assertEqual((folder/'keep').read_text(),'unchanged')
    def test_artist_override_metadata_pitch_and_shared_palette_background(self):
        from PIL import Image
        Image.new('RGB',(60,40),(120,30,220)).save(self.source/'bg.jpg')
        second=self.source/'second.osu';second.write_bytes(self.original)
        info=dict(self.info,path=str(second))
        options=dict(diffname='Custom difficulty',artist='Custom artist',artist_unicode='アーティスト',pitch=True)
        calls=[]
        def audio(ff,src,dst,rate,pitch,**kwargs):
            calls.append((rate,pitch,kwargs['bitrate']));pathlib.Path(dst).write_bytes(b'converted')
        with patch.object(core,'make_audio',side_effect=audio),patch('pack_backend.audio_bitrate',return_value=192):
            path,count=build_pack(core,str(self.songs),'Test','flasco',8,7,[(self.info,[1,1.3],options),(info,[1.2],dict(pitch=False,various_artists=True))],'fake',audio_quality='128 kbps',backgrounds_8bit=True)
        folder=pathlib.Path(path)
        self.assertEqual(len(list(folder.glob('*.png'))),1)
        with Image.open(next(folder.glob('*.png'))) as image:self.assertEqual(image.mode,'P')
        for chart in folder.glob('*.osu'):
            _,sections=core.parse_osu(str(chart));meta=core.sec(sections,'Metadata')
            if 'Custom difficulty' in core.kv(meta,'Version'):
                self.assertEqual(core.kv(meta,'Artist'),'Custom artist');self.assertEqual(core.kv(meta,'ArtistUnicode'),'アーティスト')
            else:self.assertEqual(core.kv(meta,'Artist'),'Various Artists')
            self.assertIn('.png', '\n'.join(core.sec(sections,'Events')))
        self.assertEqual(calls,[(1,False,128),(1.3,True,128),(1.2,False,128)])

    def test_real_audio_compression_and_rate_output(self):
        import shutil,wave,struct,math
        from pack_backend import audio_bitrate
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg unavailable')
        with wave.open(str(self.source/'audio.wav'),'wb') as wavefile:
            wavefile.setnchannels(2);wavefile.setsampwidth(2);wavefile.setframerate(44100)
            wavefile.writeframes(b''.join(struct.pack('<hh',int(6000*math.sin(i*.1)),int(6000*math.sin(i*.1))) for i in range(44100)))
        path,count=build_pack(core,str(self.songs),'Audio Test','flasco',8,8,[(self.info,[1,1.25],dict(pitch=True))],ffmpeg,audio_quality='128 kbps')
        folder=pathlib.Path(path)
        self.assertEqual(count,2)
        for file in folder.glob('*.mp3'):
            self.assertEqual(audio_bitrate(ffmpeg,file),128)
        self.assertEqual(self.chart.read_bytes(),self.original)

    def test_optional_artist_prefix_with_various_artists(self):
        for number,(various,include,expected) in enumerate(((True,False,'T [C]'),(True,True,'A - T [C]'),(False,True,'T [C]'))):
            path,_=build_pack(core,str(self.songs),f'Prefix {number}','flasco',8,8,[(self.info,[1])],None,various_artists=various,include_artist_in_diffname=include)
            chart=next(pathlib.Path(path).glob('*.osu'));_,sections=core.parse_osu(str(chart));meta=core.sec(sections,'Metadata')
            self.assertEqual(core.kv(meta,'Version'),expected)
            self.assertEqual(core.kv(meta,'Artist'),'Various Artists' if various else 'A')
            self.assertIn('['+expected+']',chart.name)
            self.assertEqual(core.kv(meta,'Creator'),'flasco')

    def test_quality_does_not_exceed_source(self):
        from pack_backend import target_bitrate
        self.assertEqual(target_bitrate('256 kbps',160),160)
        self.assertEqual(target_bitrate('Original',128),128)
        self.assertEqual(target_bitrate('Original',1411),320)
        with self.assertRaises(ValueError):target_bitrate('999 kbps',320)

    def test_invalid_settings_rates_and_missing_background(self):
        for text in ('','nan','1, garbage','0','6'):
            with self.assertRaises(ValueError):parse_rates(text)
        self.assertEqual(parse_rates('1,1.2x; 1'),[1,1.2])
        (self.source/'bg.jpg').unlink()
        with self.assertRaises(ValueError):self.export()
        self.assertFalse((self.songs/'Various Artists - Chordjack Pack').exists())

if __name__=='__main__':unittest.main()
