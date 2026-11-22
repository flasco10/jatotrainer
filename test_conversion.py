"""Conversion tests compare native StepMania timing against exported judgments."""
import csv
import math
from pathlib import Path
from zipfile import ZipFile
import shutil
import tempfile
import unittest
import wave
from unittest.mock import patch
import simfile
from simfile.ssc import SSCSimfile, SSCChart
from simfile.notes import NoteData, Note, NoteType
from simfile.timing import Beat, TimingData
from simfile.timing.engine import TimingEngine
from chart_conversion import catalog, convert, sm_to_osu, osu_to_sm
from test_generation import m as core, MAP


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir();self.output=self.root/'output';self.output.mkdir()
        with wave.open(str(self.source/'music.wav'),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(44100);f.writeframes(b'\0'*(44100*4))
        (self.source/'bg.png').write_bytes(b'background')
    def tearDown(self):self.tmp.cleanup()
    def song(self, fields=None, notes=None, charts=1):
        s=SSCSimfile.blank();s['TITLE']='空の涙';s['TITLETRANSLIT']='Sky Tears';s['ARTIST']='Artist';s['CREDIT']='Mapper';s['MUSIC']='music.wav';s['BACKGROUND']='bg.png';s['BPMS']='0=120,4=240';s['OFFSET']='-0.25';s['SAMPLESTART']='1.5';s['SAMPLELENGTH']='12'
        for k,v in (fields or {}).items():s[k]=v
        for i in range(charts):
            c=SSCChart.blank();c['CREDIT']='Mapper';c['CHARTNAME']=f'Chart {i}';c['DIFFICULTY']='Hard';c['METER']='12'
            c['NOTES']=str(NoteData.from_notes(notes or [Note(Beat(0),0,NoteType.TAP),Note(Beat(1),1,NoteType.HOLD_HEAD),Note(Beat(4),1,NoteType.TAIL),Note(Beat(7),2,NoteType.TAP)],4));s.charts.append(c)
        path=self.source/'chart.ssc';path.write_bytes(str(s).encode());return path
    def info(self,path,direction='sm_to_osu'):
        items,errors=catalog(core,str(path),direction);self.assertFalse(errors);return items
    def osu(self, objects='64,192,1000,1,0,0:0:0:0:\n192,192,2000,128,0,3000:0:0:0:0:\n', timing='0,500,4,2,0,100,1,0\n2000,250,3,2,0,100,1,0\n'):
        text=MAP.split('[Events]')[0].replace('audio.wav','music.wav')+'[Events]\n0,0,"bg.png",0,0\n[TimingPoints]\n'+timing+'[HitObjects]\n'+objects
        path=self.source/'chart.osu';path.write_bytes(text.replace('\n','\r\n').encode());return path
    def unpack_osz(self, result):
        archive=Path(result['paths'][0])
        self.assertEqual(archive.suffix,'.osz')
        folder=self.root/(archive.stem+'-unpacked')
        with ZipFile(archive) as z:
            self.assertTrue(all('/' not in name for name in z.namelist()))
            self.assertIsNone(z.testzip())
            z.extractall(folder)
        return folder
    @staticmethod
    def fake_audio(ff,src,dst,rate,pitch,**kwargs):Path(dst).write_bytes(f'{rate}:{pitch}'.encode())

    def test_sm_to_osu_bpm_holds_unicode_preview_and_media_rate(self):
        path=self.song(dict(SUBTITLE='Practice difficulty',ORIGIN='Unrelated game'));song=simfile.open(str(path));song.charts[0]['STEPARTIST']='Step Artist';path.write_bytes(str(song).encode());info=self.info(path)[0];model=sm_to_osu(core,info,1.25)
        self.assertEqual(model['objects'],[(200,0,None),(600,1,1800),(2400,2,None)])
        self.assertEqual(model['preview'],1200)
        with patch.object(core,'make_audio',side_effect=self.fake_audio):result=convert(core,[info],self.output,'sm_to_osu',1.25,ffmpeg='fake')
        self.assertEqual(result['charts'],1);self.assertFalse(result['failures'])
        folder=self.unpack_osz(result);osu=next(folder.glob('*.osu'));_,sections=core.parse_osu(str(osu))
        self.assertEqual(core.kv(core.sec(sections,'Metadata'),'TitleUnicode'),'空の涙')
        self.assertEqual(core.kv(core.sec(sections,'Metadata'),'Title'),'Sky Tears')
        metadata=core.sec(sections,'Metadata')
        self.assertEqual(core.kv(metadata,'Version'),'Practice difficulty x1.25')
        self.assertEqual(core.kv(metadata,'Creator'),'Step Artist')
        self.assertEqual(core.kv(metadata,'Artist'),'Artist')
        self.assertEqual(core.kv(metadata,'Source'),self.root.name)
        self.assertEqual(core.kv(metadata,'Tags'),self.root.name+' jatotrainer')
        self.assertEqual(core.kv(metadata,'BeatmapSetID'),'-1')
        self.assertEqual(list(self.output.iterdir()),[Path(result['paths'][0])])
        self.assertEqual(core.kv(core.sec(sections,'General'),'PreviewTime'),'1200')
        self.assertTrue((folder/core.kv(core.sec(sections,'General'),'AudioFilename')).exists())
        self.assertEqual(next(csv.reader([core.sec(sections,'Events')[0]]))[2],'background.png')
        self.assertNotIn(b'\r\r\n',osu.read_bytes())
        self.assertTrue(any(abs(float(l.split(',')[1])-400)<.001 for l in core.sec(sections,'TimingPoints') if l.split(',')[6]=='1'))

    def test_stops_delays_warps_and_fakes_match_native_engine(self):
        notes=[Note(Beat(b),b%4,NoteType.TAP) for b in range(8)]
        path=self.song(dict(STOPS='2=1',DELAYS='3=0.5',WARPS='5=1',FAKES='7=1'),notes)
        model=sm_to_osu(core,self.info(path)[0])
        self.assertEqual([n[0] for n in model['objects']],[250,750,1250,3250,3750,4000])
        self.assertTrue(any('pause/warp' in w for w in model['warnings']))
        self.assertTrue(any('omitted' in w for w in model['warnings']))

    def test_split_ssc_timing_does_not_inherit_song_segments(self):
        path=self.song(dict(STOPS='2=5'),charts=2);s=simfile.open(str(path))
        s.charts[1]['BPMS']='0=60';s.charts[1]['OFFSET']='-1';path.write_bytes(str(s).encode())
        infos=self.info(path);m=sm_to_osu(core,infos[1])
        self.assertEqual(m['objects'][0][0],1000)
        self.assertEqual(m['objects'][1],(2000,1,5000))

    def test_chart_timing_inherits_song_offset_but_not_song_bpm(self):
        path=self.song(dict(OFFSET='-0.25',BPMS='0=120'),charts=1)
        song=simfile.open(str(path));song.charts[0]['STOPS']='2=1';path.write_bytes(str(song).encode())
        model=sm_to_osu(core,self.info(path)[0])
        self.assertEqual(model['objects'][0][0],250)
        self.assertEqual(model['objects'][1],(1250,1,5250))
        self.assertTrue(any('60 BPM' in w for w in model['warnings']))

    def test_offset_only_chart_timing_is_ignored_without_chart_segments(self):
        path=self.song();song=simfile.open(str(path));song.charts[0]['OFFSET']='-1';path.write_bytes(str(song).encode())
        model=sm_to_osu(core,self.info(path)[0])
        self.assertEqual(model['objects'][0][0],250)
        self.assertEqual(model['objects'][1],(750,1,2250))

    def test_legacy_sm_and_ssc_precedence(self):
        path=self.source/'legacy.sm'
        path.write_text('#TITLE:Legacy;\n#ARTIST:Artist;\n#MUSIC:music.wav;\n#BPMS:0=120;\n#OFFSET:0;\n#NOTES:dance-single:Mapper:Hard:10:0,0,0,0,0:\n1000\n0100\n0010\n0001\n;')
        self.assertEqual(self.info(path)[0]['keys'],4)
        self.assertEqual(len(sm_to_osu(core,self.info(path)[0])['objects']),4)
        ssc=self.song();(self.source/'chart.sm').write_bytes(path.read_bytes())
        items,_=catalog(core,str(self.source),'sm_to_osu');self.assertEqual(len(items),2)

    def test_osu_to_ssc_native_time_grid_and_properties(self):
        path=self.osu();info=self.info(path,'osu_to_sm')[0];model=osu_to_sm(core,info,1.25)
        engine=TimingEngine(TimingData(model['song']))
        notes=list(NoteData(model['chart']))
        self.assertEqual([round(float(engine.time_at(n.beat))*1000) for n in notes],[800,1600,2400])
        self.assertEqual(model['chart']['JATOTRAINEROD'],'8')
        self.assertEqual(model['song']['SAMPLESTART'],'1.600000')
        self.assertIn('150',model['song']['BPMS']);self.assertIn('300',model['song']['BPMS'])
        self.assertLess(model['sync_error'],.001)

    def test_osu_pack_preserves_separate_subtitles_source_and_timing(self):
        path=self.osu()
        path.write_bytes(path.read_bytes().replace(b'Version:Hard',b'Version:Hard\r\nSource:My Practice Pack'))
        second=self.source/'second.osu'
        second.write_bytes(path.read_bytes().replace(b'Version:Hard',b'Version:Expert').replace(b'2000,250',b'2000,500'))
        infos,_=catalog(core,str(self.source),'osu_to_sm');result=convert(core,infos,self.output,'osu_to_sm')
        self.assertEqual(result['charts'],2);self.assertEqual(len(result['paths']),2)
        subtitles=set()
        for exported in result['paths']:
            folder=Path(exported)
            self.assertEqual(folder.parent,self.output/'My Practice Pack')
            song=simfile.open(str(folder/'charts.ssc'))
            self.assertEqual(song['ORIGIN'],'My Practice Pack')
            self.assertEqual(len(song.charts),1)
            chart=song.charts[0];subtitles.add(song['SUBTITLE'])
            self.assertEqual(chart['CHARTNAME'],song['SUBTITLE'])
            engine=TimingEngine(TimingData(song,chart));notes=list(NoteData(chart))
            self.assertEqual(round(engine.time_at(notes[-1].beat)*1000),3000)
            self.assertTrue((folder/song['MUSIC']).is_file());self.assertTrue((folder/song['BACKGROUND']).is_file())
        self.assertEqual(subtitles,{'Hard','Expert'})

    def test_round_trip_native_grid_preserves_times_and_lanes(self):
        path=self.osu();info=self.info(path,'osu_to_sm')[0]
        exported=convert(core,[info],self.output,'osu_to_sm');ssc=Path(exported['paths'][0])/'charts.ssc'
        target=self.root/'back';target.mkdir();back=convert(core,self.info(ssc),target,'sm_to_osu')
        _,sections=core.parse_osu(str(next(self.unpack_osz(back).glob('*.osu'))))
        objects=core.sec(sections,'HitObjects');self.assertIn(',1000,1,',objects[0]);self.assertIn(',2000,128,0,3000:',objects[1])
        self.assertEqual(core.kv(core.sec(sections,'General'),'PreviewTime'),'2000')

    def test_strict_sync_accounts_for_rounded_bpm_change(self):
        path=self.osu(objects='64,192,756,1,0,0:0:0:0:\n',
                      timing='0,500,4,2,0,100,1,0\n506,250,4,2,0,100,1,0\n')
        info=self.info(path,'osu_to_sm')[0]
        model=osu_to_sm(core,info)
        self.assertLess(model['sync_error'],2)
        self.assertIn('240', model['song']['BPMS'])

    def test_public_profile_embedded_user_becomes_small_rgba_cdtitle(self):
        import io
        from PIL import Image
        from mapper_avatar import mapper_cdtitle
        html=b'<div data-initial-data="{&quot;user&quot;:{&quot;username&quot;:&quot;Mapper&quot;,&quot;avatar_url&quot;:&quot;https://a.ppy.sh/7&quot;}}"></div>'
        original=io.BytesIO()
        Image.new('RGB',(128,64),'red').save(original,'PNG')
        with patch('mapper_avatar._download',side_effect=[html,original.getvalue()]) as download:
            result=mapper_cdtitle('Mapper')
        self.assertTrue(download.call_args_list[0].args[0].endswith('/Mapper'))
        self.assertEqual(download.call_args_list[1].args[0],'https://a.ppy.sh/7')
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual((image.size,image.mode),((64,32),'RGBA'))

    def test_mapper_avatar_is_opt_in_and_failure_does_not_block_export(self):
        info=self.info(self.osu(),'osu_to_sm')[0]
        with patch('chart_conversion.mapper_cdtitle',return_value=b'avatar') as avatar:
            normal=convert(core,[info],self.output,'osu_to_sm')
            avatar.assert_not_called()
            self.assertFalse((Path(normal['paths'][0])/'cdtitle.png').exists())
            enabled=convert(core,[info],self.output,'osu_to_sm',include_cdtitle=True)
            avatar.assert_called_once_with(info['creator'])
            folder=Path(enabled['paths'][0]);song=simfile.open(str(folder/'charts.ssc'))
            self.assertEqual((folder/song['CDTITLE']).read_bytes(),b'avatar')
        with patch('chart_conversion.mapper_cdtitle',side_effect=ValueError('missing')):
            fallback=convert(core,[info],self.output,'osu_to_sm',include_cdtitle=True)
            self.assertEqual(fallback['charts'],1)
            self.assertIn('mapper avatar skipped',' '.join(fallback['warnings']))

    def test_strict_sync_rejects_irregular_notes_and_reports_quantization(self):
        path=self.osu(objects='64,192,1007,1,0,0:0:0:0:\n')
        info=self.info(path,'osu_to_sm')[0]
        with self.assertRaisesRegex(ValueError,'shift judgments'):osu_to_sm(core,info)
        model=osu_to_sm(core,info,strict=False);self.assertGreater(model['sync_error'],2)
        self.assertTrue(model['warnings'])

    def test_special_notes_require_explicit_approximation(self):
        notes=[Note(Beat(0),0,NoteType.MINE),Note(Beat(1),1,NoteType.ROLL_HEAD),Note(Beat(2),1,NoteType.TAIL),Note(Beat(3),2,NoteType.LIFT)]
        info=self.info(self.song(notes=notes))[0]
        with self.assertRaisesRegex(ValueError,'Mines'):sm_to_osu(core,info)
        model=sm_to_osu(core,info,approximate=True);self.assertEqual(len(model['objects']),2);self.assertIsNotNone(model['objects'][0][2])

    def test_missing_audio_and_unsupported_keys_publish_nothing(self):
        path=self.song();info=self.info(path)[0];(self.source/'music.wav').unlink()
        result=convert(core,[info],self.output,'sm_to_osu');self.assertEqual(result['charts'],0);self.assertTrue(result['failures']);self.assertEqual(list(self.output.iterdir()),[])
        path=self.osu();path.write_bytes(path.read_bytes().replace(b'CircleSize:4',b'CircleSize:9'))
        with self.assertRaisesRegex(ValueError,'9K'):osu_to_sm(core,self.info(path,'osu_to_sm')[0])

    def test_existing_outputs_and_source_files_never_overwritten(self):
        path=self.song();before=path.read_bytes();info=self.info(path)[0]
        first=convert(core,[info],self.output,'sm_to_osu');archive=Path(first['paths'][0]);old=archive.read_bytes()
        second=convert(core,[info],self.output,'sm_to_osu')
        self.assertNotEqual(first['paths'],second['paths']);self.assertEqual(archive.read_bytes(),old);self.assertEqual(path.read_bytes(),before)

    def test_empty_paths_and_escaping_assets_rejected(self):
        with self.assertRaisesRegex(ValueError,'Choose'):catalog(core,'','sm_to_osu')
        info=self.info(self.song())[0]
        with self.assertRaisesRegex(ValueError,'output folder'):convert(core,[info],'','sm_to_osu')
        path=self.song(dict(MUSIC='../outside.wav'));(self.root/'outside.wav').write_bytes(b'outside')
        result=convert(core,self.info(path),self.output,'sm_to_osu')
        self.assertEqual(result['charts'],0);self.assertIn('outside chart folder',result['failures'][0])

    def test_keysound_orphans_and_collision_are_rejected(self):
        path=self.song();song=simfile.open(str(path));song.charts[0]['NOTES']='2[0]000\n0000\n0000\n3000';path.write_bytes(str(song).encode())
        with self.assertRaisesRegex(ValueError,'Keysounded'):sm_to_osu(core,self.info(path)[0])
        song.charts[0]['NOTES']='2000\n0000\n0000\n0000';path.write_bytes(str(song).encode())
        result=convert(core,self.info(path),self.output,'sm_to_osu');self.assertEqual(result['charts'],0)
        path=self.osu(objects='64,192,1000,1,0,0:0:0:0:\n64,192,1001,1,0,0:0:0:0:\n')
        with self.assertRaisesRegex(ValueError,'collides'):osu_to_sm(core,self.info(path,'osu_to_sm')[0],strict=False)

    def test_missing_music_tag_detects_only_unambiguous_audio(self):
        path=self.song(dict(MUSIC=''))
        self.assertEqual(sm_to_osu(core,self.info(path)[0])['audio'].name,'music.wav')
        (self.source/'other.mp3').write_bytes(b'audio')
        with self.assertRaisesRegex(ValueError,'music filename'):sm_to_osu(core,self.info(path)[0])

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_real_rate_encoding_duration_and_pitch_switch(self):
        from pack_backend import audio_bitrate
        info=self.info(self.song())[0]
        for pitch in (True,False):
            result=convert(core,[info],self.output,'sm_to_osu',rate=1.25,pitch=pitch,ffmpeg=shutil.which('ffmpeg'))
            self.assertFalse(result['failures']);folder=self.unpack_osz(result);audio=next(folder.glob('*.mp3'))
            self.assertEqual(audio_bitrate(shutil.which('ffmpeg'),audio),320)
            import subprocess
            pcm=subprocess.check_output([shutil.which('ffmpeg'),'-v','error','-i',str(audio),'-f','s16le','-ar','44100','-ac','2','-'])
            self.assertAlmostEqual(len(pcm)/(44100*4),.8,delta=.06)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_negative_offset_notes_get_matching_audio_padding(self):
        info=self.info(self.song(dict(OFFSET='0.25',BPMS='0=120')))[0]
        result=convert(core,[info],self.output,'sm_to_osu',ffmpeg=shutil.which('ffmpeg'))
        self.assertFalse(result['failures']);folder=self.unpack_osz(result);_,sections=core.parse_osu(str(next(folder.glob('*.osu'))))
        with wave.open(str(folder/core.kv(core.sec(sections,'General'),'AudioFilename')),'rb') as audio:
            self.assertAlmostEqual(audio.getnframes()/audio.getframerate(),1.25,places=3)
        self.assertEqual(int(core.sec(sections,'HitObjects')[0].split(',')[2]),0)
        self.assertEqual(core.kv(core.sec(sections,'General'),'PreviewTime'),'1750')

if __name__=='__main__':unittest.main()
