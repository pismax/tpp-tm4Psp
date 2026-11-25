"""Tests for the emulator helper, without a game or PPSSPP dependency."""
import asyncio
import importlib.util
import json
import pathlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('tm4_ppsspp', pathlib.Path(__file__).with_name('tm4-ppsspp.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class PrepareTests(unittest.TestCase):
    def test_isolated_config_and_first_copy_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); source = root / 'source'; lab = root / 'lab'
            source.mkdir(); (source / 'assets').mkdir()
            (source / 'assets/icon.png').write_bytes(b'asset')
            (source / 'PPSSPPWindows64.exe').write_bytes(b'fake exe')
            system = source / 'memstick/PSP/SYSTEM'; system.mkdir(parents=True)
            ini = system / 'ppsspp.ini'; ini.write_text('[General]\nLanguage = en_US\nRemoteISOPort = 123\n', encoding='utf8')
            original = ini.read_bytes()
            saves = source / 'memstick/PSP/SAVEDATA'; saves.mkdir(); (saves / 'test.bin').write_bytes(b'original')
            helper.prepare(source, lab, 20003, copy_saves=True)
            self.assertEqual(ini.read_bytes(), original)
            self.assertEqual((saves / 'test.bin').read_bytes(), b'original')
            self.assertIn('RemoteISOPort = 20003', (lab / 'memstick/PSP/SYSTEM/ppsspp.ini').read_text())
            self.assertTrue((lab / helper.MARKER).is_file())
            copied = lab / 'memstick/PSP/SAVEDATA/test.bin'; copied.write_bytes(b'lab progress')
            helper.prepare(source, lab, 20004, copy_saves=True)
            self.assertEqual(copied.read_bytes(), b'lab progress')
            with self.assertRaisesRegex(ValueError, 'separate lab'): helper.prepare(source, source / 'bad', 20002)
            unknown = root / 'unknown'; unknown.mkdir(); (unknown / 'keep.txt').write_text('keep')
            with self.assertRaisesRegex(ValueError, 'not an owned'): helper.prepare(source, unknown, 20002)
            self.assertEqual((unknown / 'keep.txt').read_text(), 'keep')


class Socket:
    def __init__(self, replies): self.replies, self.sent = iter(replies), []
    async def send(self, data): self.sent.append(json.loads(data))
    async def recv(self): return json.dumps(next(self.replies))


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_ignores_notifications_and_bounds_log_memory(self):
        debugger = helper.Debugger()
        debugger.ws = Socket([{'event': 'log', 'message': str(i)} for i in range(120)] +
                             [{'event': 'cpu.stepping'}, {'event': 'cpu.status', 'pc': 123}])
        self.assertEqual((await debugger.rpc('cpu.status'))['pc'], 123)
        self.assertEqual(len(debugger.logs), 100)
        self.assertEqual(debugger.ws.sent, [{'event': 'cpu.status'}])

    async def test_navigation_stops_at_scene_and_removes_probe(self):
        class Fake:
            def __init__(self): self.polls, self.buttons, self.removed = 0, [], []
            async def require_game(self): pass
            async def running(self, **kwargs): pass
            async def add_probe(self, address): self.address = address
            async def hit(self, address, seconds): self.polls += 1; return self.polls == 3
            async def rpc(self, event, **params): self.buttons.append(params['button'])
            async def remove_probe(self, address): self.removed.append(address)
        fake = Fake()
        result = await helper.navigate(fake)
        self.assertTrue(result['sceneReached'])
        self.assertEqual(fake.buttons, ['circle', 'start'])
        self.assertEqual(fake.removed, [helper.SCENE_ADDRESS])

    async def test_startup_pause_can_clear_naturally_without_resuming(self):
        debugger=helper.Debugger()
        debugger.ws=Socket([{'event':'cpu.status','stepping':True,'paused':False},
                            {'event':'cpu.status','stepping':False,'paused':False}])
        await debugger.running(wait_seconds=1)
        self.assertEqual(debugger.ws.sent,[{'event':'cpu.status'},{'event':'cpu.status'}])

    async def test_ascii_probe_checks_instructions_and_always_cleans_up(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
        import tm4_font
        class Fake:
            def __init__(self): self.removed = []
            async def require_game(self): pass
            async def running(self): pass
            async def add_probe(self, *args): pass
            async def hit(self, *args): return True
            async def read(self, address, size):
                assert address == 0x1000
                return b'W\0'
            async def rpc(self, event, **params):
                if event == 'memory.disasm':
                    address = params['address']
                    value = 0xc4409480 if address == 0x08835d9c else tm4_font.PATCHES[address][1]
                    return {'lines': [{'address': address, 'encoding': value}]}
                return {'categories': [{'registerNames': ['a0', 'a1', 's1', 't4'], 'uintValues': [0x1000, 112, 120, 87]}]}
            async def remove_probe(self, address): self.removed.append(address)
        fake = Fake()
        result = await helper.verify(fake, expected_character='W')
        self.assertEqual((result['advance'], result['patchWordsVerified']), (8, 13))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected first ASCII'): await helper.verify(fake, expected_character='X')
        self.assertEqual(fake.removed, [helper.DRAW_ADDRESS] * 2)


if __name__ == '__main__': unittest.main()
