"""Synthetic executable guards and MIPS scenario-loop regression tests.

Execute the patched instructions, including branch delay slots, to check
single-byte output, cursor positions and preservation of Japanese characters.
No game executable or font asset is included.
"""
import hashlib
import pathlib
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
import tm4_font as font
import tm4_bridge as bridge


def scenario_character(code, start=80):
    words = {
        0x088710f4: 0x304300ff, 0x0887110c: 0x00041a03,
        0x08871114: 0x26310010, 0x08871118: 0x27a40010,
        0x0887111c: 0x02803021, 0x08871120: 0x02e03821,
        0x08871124: 0x02c04021, 0x08871128: 0x24090000,
        0x08871130: 0x240a0000, 0x0887113c: 0xa3a30011,
        0x08871140: 0xa3ac0010, 0x08871148: 0xa3a00012,
    }
    words.update({a: new for a, (_, new) in font.PATCHES.items() if a >= 0x088710f4})
    regs = [0] * 32
    regs[2] = regs[12] = code
    regs[4] = code & 0xff00
    regs[17] = start
    regs[29] = 0x1000
    memory = {}

    def execute(pc):
        w = words[pc]
        op, rs, rt, rd, shift, fn = w >> 26, w >> 21 & 31, w >> 16 & 31, w >> 11 & 31, w >> 6 & 31, w & 63
        imm = w & 0xffff
        signed = imm if imm < 0x8000 else imm - 0x10000
        if op == 0:
            if fn == 0: regs[rd] = regs[rt] << shift
            elif fn == 3: regs[rd] = (regs[rt] if regs[rt] < 0x80000000 else regs[rt] - 0x100000000) >> shift
            elif fn == 33: regs[rd] = regs[rs] + regs[rt]
            elif fn == 35: regs[rd] = regs[rs] - regs[rt]
            else: raise AssertionError(hex(w))
        elif op == 9: regs[rt] = regs[rs] + signed
        elif op == 11: regs[rt] = int(regs[rs] < (signed & 0xffffffff))
        elif op == 12: regs[rt] = regs[rs] & imm
        elif op == 40: memory[regs[rs] + signed] = regs[rt] & 255
        elif op in (4, 5):
            take = (regs[rs] == regs[rt]) if op == 4 else (regs[rs] != regs[rt])
            return pc + 4 + signed * 4 if take else pc + 8
        else: raise AssertionError(hex(w))
        regs[:] = [r & 0xffffffff for r in regs]
        regs[0] = 0

    pc = 0x088710f4
    for _ in range(40):
        if pc == 0x08871150: return None, regs[17], start
        if pc == 0x08871144:
            execute(pc + 4)
            return bytes(memory[0x1010 + i] for i in range(3)).split(b'\0')[0], regs[17], regs[5]
        target = execute(pc)
        if target is not None:
            execute(pc + 4)
            pc = target
        else: pc += 4
    raise AssertionError('Scenario loop did not terminate')


class FontTests(unittest.TestCase):
    def test_bold_preserves_other_glyphs_paired_planes_and_vertical_metrics(self):
        lookup_offset = 0x314b00 + 0x08b197c0 - 0x08b18a00
        executable = bytearray(lookup_offset + 6960 * 2)
        executable[:4] = b'\x7fELF'
        for a, (old, _) in font.PATCHES.items(): struct.pack_into('<I', executable, font.file_offset(a), old)
        struct.pack_into('<6960H', executable, lookup_offset, *range(6960))
        struct.pack_into('<96H', executable, font.file_offset(0x08adefd4), *range(96))
        atlas = bytearray(font.ATLAS_SIZE)
        # Exercise both planes, all ASCII positions and a neighbouring Japanese slot.
        for index in range(97):
            offset, shift = font.glyph_pixel(index, 7, 2)
            atlas[offset] |= 3 << shift
        allowed = bytearray(len(atlas))
        indexes = [c - 32 for c in range(48, 123) if chr(c).isalnum()]
        for index in indexes:
            for y in range(16):
                for x in range(16):
                    offset, shift = font.glyph_pixel(index, x, y)
                    allowed[offset] |= 3 << shift
        with patch.object(font, 'SOURCE_SHA256', hashlib.sha256(executable).hexdigest()), \
             patch.object(font, 'ATLAS_SHA256', hashlib.sha256(atlas).hexdigest()):
            result, report = font.bold_atlas(atlas, executable)
            self.assertEqual(len(result), len(atlas))
            self.assertEqual(report['glyphs'], 62)
            self.assertEqual(report['patchedSha256'], hashlib.sha256(result).hexdigest())
            self.assertTrue(any(a != b for a, b in zip(atlas, result)))
            for a, b, mask in zip(atlas, result, allowed): self.assertEqual((a ^ b) & ~mask, 0)
            for index in indexes:
                for y in range(16):
                    for x in range(16):
                        offset, shift = font.glyph_pixel(index, x, y)
                        self.assertEqual((result[offset] >> shift) & 3, 3 if y == 2 and 6 <= x <= 8 else 0)
            with self.assertRaisesRegex(ValueError, 'Unsupported TM4 font atlas'):
                font.bold_atlas(result, executable)
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            font.bold_atlas(atlas, executable)

    def test_unknown_weight_or_bold_without_executable_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'source.iso'; source.write_bytes(b'original')
            target = pathlib.Path(directory) / 'output.iso'
            request = {'iso': str(source), 'target': str(target), 'stage': directory,
                       'manifest': {'isoSha256': hashlib.sha256(b'original').hexdigest()}}
            for weight in ('heavy', 'bold'):
                with self.assertRaisesRegex(ValueError, 'weight|requires half-width'):
                    bridge.build({**request, 'halfWidthWeight': weight})
                self.assertFalse(target.exists())

    def test_ascii_alphabet_digits_punctuation_and_spaces(self):
        for code in range(0x20, 0x7f):
            with self.subTest(code=code):
                text, end, draw_x = scenario_character(code)
                self.assertEqual(text, bytes([code]))
                self.assertEqual((draw_x, end), (80, 88))

    def test_mixed_japanese_and_ascii_cursor_positions(self):
        x = 80
        for char, expected_x in [('日', 96), ('本', 112), ('A', 120), (' ', 128), ('z', 136), ('Ａ', 152)]:
            raw = char.encode('cp932')
            text, x, draw_x = scenario_character(int.from_bytes(raw, 'little'), x)
            self.assertEqual(text, raw)
            self.assertEqual(x, expected_x)
            self.assertEqual(x - draw_x, 8 if len(raw) == 1 else 16)

    def test_unsupported_half_kana_still_skipped(self):
        for code in range(0xa1, 0xe0):
            self.assertEqual(scenario_character(code)[:2], (None, 80))

    def test_executable_fingerprint_and_encrypted_input_guards(self):
        for raw in [b'~PSP' + b'\0' * 100, b'\0' * 100]:
            with self.assertRaisesRegex(ValueError, 'decrypted EBOOT'): font.patch(raw)
        with self.assertRaisesRegex(ValueError, 'Unsupported'): font.patch(b'\x7fELF' + b'\0' * 100)

    def test_patch_changes_only_guarded_words_and_rejects_repatching(self):
        raw = bytearray(font.file_offset(max(font.PATCHES)) + 4)
        raw[:4] = b'\x7fELF'
        for a, (old, _) in font.PATCHES.items(): struct.pack_into('<I', raw, font.file_offset(a), old)
        fingerprint = hashlib.sha256(raw).hexdigest()
        with patch.object(font, 'SOURCE_SHA256', fingerprint):
            result = font.patch(raw)
            expected = bytearray(raw)
            for a, (_, new) in font.PATCHES.items(): struct.pack_into('<I', expected, font.file_offset(a), new)
            self.assertEqual(result, expected)
            self.assertEqual(font.inspect(raw)['patchedSha256'], hashlib.sha256(result).hexdigest())
            with self.assertRaisesRegex(ValueError, 'Unsupported'): font.patch(result)
        raw[font.file_offset(min(font.PATCHES))] ^= 1
        with patch.object(font, 'SOURCE_SHA256', hashlib.sha256(raw).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'instruction mismatch'): font.patch(raw)

    def test_font_only_export_and_disabled_noop_leave_source_unchanged(self):
        executable = bytearray(font.file_offset(max(font.PATCHES)) + 4)
        executable[:4] = b'\x7fELF'
        for a, (old, _) in font.PATCHES.items(): struct.pack_into('<I', executable, font.file_offset(a), old)
        original = b'synthetic original ISO'
        with tempfile.TemporaryDirectory(prefix='tpp-tm4-font-test-') as root:
            root = pathlib.Path(root)
            source = root / 'source.iso'; source.write_bytes(original)
            eboot = root / 'original.bin'; eboot.write_bytes(executable)
            target = root / 'halfwidth.iso'
            request = {'iso': str(source), 'stage': str(root), 'target': str(target),
                       'manifest': {'isoSha256': hashlib.sha256(original).hexdigest(), 'files': []},
                       'halfWidthEboot': str(eboot)}
            replacements = {}
            def write_iso(iso, output, files):
                self.assertEqual(pathlib.Path(iso).read_bytes(), original)
                replacements.update(files)
                pathlib.Path(output).write_bytes(files['PSP_GAME/SYSDIR/EBOOT.BIN'])
            def inventory(iso):
                return [SimpleNamespace(path='PSP_GAME/SYSDIR/EBOOT.BIN', lba=0, size=pathlib.Path(iso).stat().st_size)]
            with patch.object(font, 'SOURCE_SHA256', hashlib.sha256(executable).hexdigest()), \
                 patch.object(bridge, 'patch_iso', side_effect=write_iso), \
                 patch.object(bridge, 'parse_iso', side_effect=inventory):
                result = bridge.build(request)
                self.assertEqual(result['changedMembers'], 0)
                self.assertEqual(result['halfWidthFont']['profile'], font.PROFILE)
                self.assertEqual(target.read_bytes(), font.patch(executable))
                self.assertEqual(list(replacements), ['PSP_GAME/SYSDIR/EBOOT.BIN'])
            self.assertEqual(source.read_bytes(), original)
            request.pop('halfWidthEboot'); request['target'] = str(root / 'unchanged.iso')
            result = bridge.build(request)
            self.assertIsNone(result['halfWidthFont'])
            self.assertEqual((root / 'unchanged.iso').read_bytes(), original)


if __name__ == '__main__': unittest.main()
