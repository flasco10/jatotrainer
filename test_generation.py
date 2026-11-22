"""Headless regression tests; run python -m unittest -v test_generation."""
import ast
import json
import math
import pathlib
import shutil
import struct
import subprocess
import tempfile
import types
import unittest
import wave
from unittest.mock import patch

# Exercise production backend without installing GUI packages or opening Tk.
tree = ast.parse(pathlib.Path(__file__).with_name('jatotrainer.py').read_text())
tree.body = [n for n in tree.body if not isinstance(n, ast.ClassDef)
             and not (isinstance(n, ast.Import) and any(a.name == 'customtkinter' for a in n.names))
             and not (isinstance(n, ast.FunctionDef) and n.name in ('gradient_heading', 'load_poppins'))
             and not (isinstance(n, ast.If) and '__name__' in ast.unparse(n.test))]
m = types.ModuleType('backend')
exec(compile(tree, 'jatotrainer.py', 'exec'), m.__dict__)

MAP = '''osu file format v14
[General]
AudioFilename: audio.wav
Mode: 3
PreviewTime: 2000
AudioLeadIn: 1000
[Metadata]
Artist:A
Title:T
Creator:C
Version:Hard
BeatmapID:42
Tags:test
[Difficulty]
CircleSize:4
OverallDifficulty:8
[Editor]
Bookmarks:1000,2000
[Events]
2,1000,2000
Sprite,Foreground,Centre,"image,1.png",320,240
 F,0,1000,2000,0,1
 L,2000,3
  M,0,100,200,320,240,400,240
 T,HitSound,1000,3000,1
  F,0,0,100,0,1
Animation,Foreground,Centre,"frame.png",320,240,4,100,LoopForever
Sample,1500,0,"sample.wav",80
[TimingPoints]
1000,500,4,2,0,100,1,0
2000,-50,4,2,0,100,0,0
[HitObjects]
64,192,1000,1,0,0:0:0:0:
192,192,2000,128,0,3000:0:0:0:0:
'''

class GenerationTests(unittest.TestCase):
    def test_hp_override_changes_output_and_checks_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder)/'test.osu'; path.write_text(MAP)
            header, sections = m.parse_osu(path)
            text, *_ = m.build_rate(header, sections, 1.3, '{diff} x{rate}', False, hp_override=6.5)
            self.assertIn('HPDrainRate:6.5', text)
            for hp in (-1, 11, float('nan')):
                with self.assertRaises(ValueError):
                    m.build_rate(header, sections, 1.3, '{diff}', False, hp_override=hp)

    def test_fixed_od_overrides_scaling_and_preserves_source(self):
        path = pathlib.Path(tempfile.gettempdir()) / 'jato-od-test.osu'
        path.write_text(MAP)
        try:
            header, sections = m.parse_osu(str(path))
            text, version, _, _ = m.build_rate(header, sections, 1.3, "{diff} OD{od}", True, od_override=7.5)
            self.assertIn("OverallDifficulty:7.5", text.replace("OverallDifficulty: ", "OverallDifficulty:"))
            self.assertIn("OD7.5", version)
            self.assertEqual(m.kv(m.sec(sections, 'Difficulty'), 'OverallDifficulty'), '8')
            for invalid in (-1, 11, float('nan'), float('inf')):
                with self.assertRaises(ValueError):
                    m.build_rate(header, sections, 1.3, '{diff}', False, od_override=invalid)
        finally:
            path.unlink()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.cache_patch = patch.object(m, 'AUDIO_CACHE_PATH', str(self.root/'user_audio_cache.json'))
        self.cache_patch.start()
        self.path = self.root/'original.osu'
        self.path.write_text(MAP)
        (self.root/'audio.wav').write_bytes(b'original audio')
        self.info = dict(path=str(self.path), artist='A', title='T', creator='C')
    def tearDown(self):
        self.cache_patch.stop()
        self.temp.cleanup()
    def generate(self, rates=(1.25,), pitch=False, fmt='{diff} ({rate}x)', ff='fake'):
        return list(m.generate(self.info, rates, fmt, pitch, False, lambda s: None, ff))
    @staticmethod
    def fake_audio(ff, src, dst, rate, pitch, bitrate=m.DEFAULT_BITRATE):
        pathlib.Path(dst).write_bytes(f'{rate}:{pitch}:{bitrate}'.encode())
    def maps(self):
        return sorted(p for p in self.root.glob('*.osu') if p != self.path)
    def test_new_audio_uses_central_cache_without_sidecars(self):
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate()
            self.assertFalse(list(self.root.glob('*.mp3.json')))
            audio=next(self.root.glob('*.mp3'))
            records=json.loads(pathlib.Path(m.AUDIO_CACHE_PATH).read_text())
            self.assertEqual(records[m._audio_cache_key(audio)]['sha256'],m._file_digest(audio))
        with patch.object(m, 'make_audio', side_effect=AssertionError('must reuse')):
            self.generate()
    def test_bitrate_defaults_to_192_and_is_part_of_cache_identity(self):
        calls=[]
        with patch.object(m, 'make_audio', lambda *a, **k: (calls.append(k['bitrate']), self.fake_audio(*a, **k))):
            self.generate()
            list(m.generate(self.info, (1.25,), '{diff} ({rate}x)', False, False, lambda s: None, 'fake', bitrate=320))
        self.assertEqual(calls, [192, 320])
        self.assertEqual(len(list(self.root.glob('*.mp3'))), 2)
    def test_rates_encode_in_parallel_and_publish_in_order(self):
        import threading
        barrier=threading.Barrier(3, timeout=10)  # deadlocks (BrokenBarrierError) if encodes run one at a time
        def fake(*a, **k):
            barrier.wait(); self.fake_audio(*a, **k)
        outputs=[]
        with patch.object(m, 'make_audio', fake):
            done=list(m.generate(self.info, (1.3, 1.1, 1.2), '{diff} ({rate}x)', False, False, lambda s: None, 'fake', result=outputs.append))
        self.assertEqual(done, [1.3, 1.1, 1.2])
        self.assertEqual([o['rate'] for o in outputs], [1.3, 1.1, 1.2])
        self.assertFalse(list(self.root.glob('.mmr-*')))
    def test_failed_rate_cleans_up_other_running_encodes(self):
        import time
        def fake(ff, src, dst, rate, pitch, bitrate=192):
            pathlib.Path(dst).write_bytes(b'partial')
            if rate == 1.1: raise RuntimeError('conversion failed')
            time.sleep(0.3)
        with patch.object(m, 'make_audio', fake), self.assertRaises(RuntimeError):
            list(m.generate(self.info, (1.1, 1.2, 1.3), '{diff} ({rate}x)', False, False, lambda s: None, 'fake'))
        self.assertFalse(self.maps())
        self.assertFalse(list(self.root.glob('.mmr-*')))
        self.assertFalse(list(self.root.glob('*.mp3')))
    def test_sidecar_migration_preserves_audio_and_reuses_it(self):
        with patch.object(m, 'make_audio', self.fake_audio): self.generate()
        audio=next(self.root.glob('*.mp3')); original=audio.read_bytes()
        cache=pathlib.Path(m.AUDIO_CACHE_PATH)
        record=json.loads(cache.read_text())[m._audio_cache_key(audio)]
        cache.unlink()
        sidecar=pathlib.Path(str(audio)+'.json'); sidecar.write_text(json.dumps(record))
        unknown=self.root/'unrelated.mp3.json';unknown.write_text('{"personal":true}')
        with patch.object(m, 'make_audio', side_effect=AssertionError('must reuse migrated audio')):
            self.generate()
        self.assertFalse(sidecar.exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(audio.read_bytes(),original)
        self.assertEqual(len(self.maps()),1)
        self.assertEqual(json.loads(cache.read_text())[m._audio_cache_key(audio)],record)
    def test_failed_migration_keeps_sidecar(self):
        audio=self.root/'audio x1.25 mmr.mp3';audio.write_bytes(b'valid audio')
        record={'identity':'mmr-audio-v3-cbr320:test:1.25:False','sha256':m._file_digest(audio)}
        sidecar=pathlib.Path(str(audio)+'.json');sidecar.write_text(json.dumps(record))
        with patch.object(m, '_save_audio_records', side_effect=OSError('cannot save cache')):
            with self.assertRaises(OSError): self.generate()
        self.assertTrue(sidecar.exists())
        self.assertFalse(self.maps())
    def test_central_cache_preserves_records_from_other_folders(self):
        other={'identity':'mmr-audio-v3-cbr320:other','sha256':'unused'}
        m._save_audio_records({'other-folder.mp3':other})
        with patch.object(m, 'make_audio', self.fake_audio): self.generate()
        records=m._load_audio_cache()
        self.assertEqual(records['other-folder.mp3'],other)
        self.assertEqual(len(records),2)
    def test_preferred_filenames_and_pitch_collision_reuse(self):
        self.path.write_text(MAP.replace('Version:Hard', 'Version:< Obstinacy >'))
        self.info.update(artist='Fellowship', title='Hold Up Your Hearts (Again)', creator='Jhown')
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate((1.3,), pitch=True, fmt='{diff} x{rate}')
            expected='Fellowship - Hold Up Your Hearts (Again) (Jhown) [ Obstinacy  x1.3] [mmr-x1.3].osu'
            self.assertEqual(self.maps()[0].name, expected)
            audio=self.root/'audio x1.3 mmr.mp3'
            self.assertTrue(audio.exists())
            self.assertIn('AudioFilename: audio x1.3 mmr.mp3', self.maps()[0].read_text())
            self.generate((1.3,), pitch=False, fmt='{diff} x{rate}')
            self.assertTrue((self.root/'audio x1.3 mmr (2).mp3').exists())
            self.generate((1.3,), pitch=False, fmt='{diff} x{rate}')
            self.generate((1.3,), pitch=True, fmt='{diff} x{rate}')
            self.assertEqual(len(self.maps()), 2)
            self.assertEqual(len(list(self.root.glob('*.mp3'))), 2)
    def test_same_metadata_different_source_maps_are_preserved(self):
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate(fmt='{diff}')
            first=self.maps()[0]; data=first.read_bytes()
            other=self.root/'another source.osu'
            other.write_text(MAP.replace('64,192,1000,1', '64,192,1100,1'))
            self.info['path']=str(other)
            self.generate(fmt='{diff}')
            self.assertEqual(first.read_bytes(), data)
            outputs=[p for p in self.maps() if p!=other]
            self.assertEqual(len(outputs), 2)
    def test_timestamps_and_original_preserved(self):
        h, s = m.parse_osu(self.path)
        out, *_ = m.build_rate(h, s, 2, '{diff}', False)
        for value in ['PreviewTime: 1000', 'AudioLeadIn:500', 'Bookmarks:500,1000',
                      '500,250,4', '1000,-50,4', '64,192,500,1',
                      '192,192,1000,128,0,1500:', '2,500,1000',
                      ' F,0,500,1000,0,1', ' L,1000,3',
                      '  M,0,50,100,320,240,400,240', ' T,HitSound,500,1500,1',
                      '4,50,LoopForever', 'Sample,750,0,"sample.wav",80']:
            self.assertIn(value, out)
        self.assertEqual(self.path.read_text(), MAP)
    def test_close_rates_and_constant_names(self):
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate((1.2501, 1.2502), fmt='{diff}')
        self.assertEqual(len(self.maps()), 2)
        self.assertEqual(len(list(self.root.glob('*.mp3'))), 2)
        self.assertNotEqual(m.fmt_rate(1.2501), m.fmt_rate(1.2502))
    def test_pitch_modes_repeat_and_source_changes(self):
        with patch.object(m, 'make_audio', self.fake_audio) as _:
            self.generate(); original_output=self.maps()[0]; first=original_output.read_bytes()
            self.generate(); self.assertEqual(len(self.maps()), 1)
            self.generate(pitch=True); self.assertEqual(len(self.maps()), 2)
            (self.root/'audio.wav').write_bytes(b'changed source')
            self.generate(); self.assertEqual(len(self.maps()), 3)
            self.assertEqual(original_output.read_bytes(), first)
        self.assertEqual(len(list(self.root.glob('*.mp3'))), 3)
    def test_existing_output_is_preserved(self):
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate()
            old=self.maps()[0]; old.write_text('user edit')
            self.generate()
        self.assertEqual(old.read_text(), 'user edit')
        self.assertEqual(len(self.maps()), 2)
    def test_audio_failure_leaves_no_map_or_temporary(self):
        def fail(*args, **kwargs):
            pathlib.Path(args[2]).write_bytes(b'partial')
            raise RuntimeError('conversion failed')
        with patch.object(m, 'make_audio', fail), self.assertRaises(RuntimeError):
            self.generate()
        self.assertFalse(self.maps())
        self.assertFalse(list(self.root.glob('.mmr-*')))
    def test_missing_audio_and_ffmpeg(self):
        with self.assertRaises(RuntimeError): self.generate(ff=None)
        (self.root/'audio.wav').unlink()
        with self.assertRaises(FileNotFoundError): self.generate()
        self.assertFalse(self.maps())
    def test_corrupted_audio_is_not_reused_or_overwritten(self):
        with patch.object(m, 'make_audio', self.fake_audio):
            self.generate()
            audio=next(self.root.glob('*.mp3')); audio.write_bytes(b'user edit')
            self.generate()
        self.assertEqual(audio.read_bytes(), b'user edit')
        self.assertEqual(len(self.maps()), 2)
    def test_unsupported_storyboards_fail_before_writing(self):
        (self.root/'shared.osb').write_text('[Events]\n F,0,100,200,0,1')
        with self.assertRaisesRegex(ValueError, 'External'): self.generate()
        (self.root/'shared.osb').unlink()
        self.path.write_text(MAP.replace('2,1000,2000', 'Video,0,"video.mp4"'))
        with self.assertRaisesRegex(ValueError, 'Video'): self.generate()
        self.assertFalse(self.maps())
    def test_invalid_rates(self):
        for rate in [0, 1, 6, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): self.generate((rate,))
        self.assertFalse(self.maps())
    def test_cache_same_mtime_modified_metadata(self):
        songs=self.root/'Songs'; folder=songs/'set'; folder.mkdir(parents=True)
        path=folder/'map.osu'; path.write_text(MAP)
        cache=str(self.root/'cache.json')
        with patch.object(m, 'CACHE_PATH', cache):
            first,_=m.scan_songs(songs)
            st=path.stat(); path.write_text(MAP.replace('Title:T', 'Title:Changed'))
            m.os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
            second,_=m.scan_songs(songs)
        self.assertEqual(first[0]['title'], 'T')
        self.assertEqual(second[0]['title'], 'Changed')
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg or ffprobe unavailable')
    def test_real_audio_speed_and_pitch_at_both_sample_rates(self):
        # A 1 kHz sine should become 1.25 kHz in pitch mode and stay 1 kHz
        # in tempo mode, with duration divided by 1.25 in both cases.
        for sr in (44100, 48000):
            src=self.root/f'{sr}.wav'
            with wave.open(str(src), 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
                f.writeframes(b''.join(struct.pack('<h', int(15000*math.sin(2*math.pi*1000*i/sr))) for i in range(sr*2)))
            for pitch in (True, False):
                dst=self.root/f'{sr}-{pitch}.mp3'
                m.make_audio(shutil.which('ffmpeg'), str(src), str(dst), 1.25, pitch)
                probe=json.loads(subprocess.check_output([
                    'ffprobe','-v','error','-select_streams','a:0','-show_packets',
                    '-show_entries','packet=size','-of','json',str(dst)]))
                # 320 kbps MPEG-1 Layer III at 44.1 kHz: padded/unpadded
                # frames differ by one byte, unlike the previous VBR output.
                sizes={int(p['size']) for p in probe['packets']}
                self.assertTrue(sizes <= {1044, 1045}, sizes)
                raw=subprocess.check_output(['ffmpeg','-loglevel','error','-i',str(dst),'-f','s16le','-ac','1','-ar','44100','-'])
                samples=struct.unpack('<'+'h'*(len(raw)//2), raw)
                duration=len(samples)/44100
                self.assertAlmostEqual(duration, 1.6, delta=.06)
                center=samples[22050:44100]
                crossings=sum(a<=0<b for a,b in zip(center,center[1:]))
                self.assertAlmostEqual(crossings*2, 1250 if pitch else 1000, delta=15)

if __name__ == '__main__': unittest.main()
