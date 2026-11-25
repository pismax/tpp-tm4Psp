"""Loader-layout regressions, using synthetic PIDX/FSTS containers only."""
import pathlib, random, struct, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from pidx import Pidx, Fsts, decompress_payload
import rebuild


def fsts():
    data = bytearray(b'\xa5' * 0x300)
    data[:4] = b'FSTS'
    names = b'first.dat\0second.dat\0third.dat\0'
    struct.pack_into('<4I', data, 4, 3, 0x20, 0x60, len(names))
    data[0x60:0x60 + len(names)] = names
    for i, (name, offset, value) in enumerate([(0, 0x100, b'A' * 16), (10, 0x180, b'B' * 16), (21, 0x200, b'C' * 16)]):
        struct.pack_into('<4I', data, 0x20 + i * 16, name, offset, len(value), 0)
        data[offset:offset + len(value)] = value
    return bytes(data)


def outer():
    data = bytearray(b'\xa7' * 0x1900)
    data[:4] = b'PIDX'
    struct.pack_into('<9I', data, 4, 0x30, 0, 0x50, 0, 0, 0x50, 52, 0x90, 16)
    struct.pack_into('<I', data, 0x50, 2)
    data[0x90:0xa0] = b'\0first\0second\0\0\0'
    for i, (name, offset) in enumerate([(1, 0x800), (7, 0x1000)]):
        blob = bytearray(fsts())
        if i: blob[0x60:0x6a] = b'other.dat\0'
        struct.pack_into('<5I', data, 0x5c + i * 20, name, 0, offset, len(blob), 583)
        data[offset:offset + len(blob)] = blob
    return bytes(data)


class ArchiveTests(unittest.TestCase):
    def test_fsts_noop_and_unused_replacements_are_byte_exact(self):
        raw = fsts()
        for replacements in ({}, {'missing.dat': b'new'}, {'first.dat': b'A' * 16}):
            self.assertEqual(rebuild.build_fsts(raw, Fsts(raw), replacements), raw)

    def test_fsts_gap_write_preserves_names_reserved_bytes_and_other_entries(self):
        raw = fsts(); original = Fsts(raw)
        out = rebuild.build_fsts(raw, original, {'first.dat': b'New name'})
        table = Fsts(out)
        self.assertEqual(table.entries[0].offset, original.entries[0].offset)
        self.assertEqual(out[:0x20], raw[:0x20])
        self.assertEqual(out[0x30:0x100], raw[0x30:0x100])
        self.assertEqual(out[0x180:], raw[0x180:])
        self.assertEqual(decompress_payload(out, table.entries[0].offset, table.entries[0].size, table.entries[0].zsize), b'New name')

    def test_fsts_oversize_and_aliases_relocate_only_changed_member(self):
        for aliased in (False, True):
            raw = bytearray(fsts())
            if aliased: struct.pack_into('<I', raw, 0x44, 0x100)
            raw = bytes(raw); original = Fsts(raw)
            content = random.Random(7).randbytes(1024) if not aliased else b'Changed'
            out = rebuild.build_fsts(raw, original, {'first.dat': content}); table = Fsts(out)
            self.assertGreaterEqual(table.entries[0].offset, len(raw))
            for a, b in zip(original.entries[1:], table.entries[1:]):
                self.assertEqual((a.offset, a.size, a.zsize, a.name_off), (b.offset, b.size, b.zsize, b.name_off))
                self.assertEqual(out[b.offset:b.offset + b.size], raw[a.offset:a.offset + a.size])
            self.assertEqual(decompress_payload(out, table.entries[0].offset, table.entries[0].size, table.entries[0].zsize), content)

    def test_outer_pack_preserves_peer_archives_flags_and_gaps_for_fit_and_growth(self):
        for size in (16, 6000):
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory); pack = root / 'source'; pack.mkdir()
                raw = outer(); (pack / 'slg_ctbl.dat').write_bytes(raw)
                mods = root / 'mods/packs/slg_ctbl.dat'; mods.mkdir(parents=True)
                content = random.Random(42).randbytes(size); (mods / 'first.dat').write_bytes(content)
                rebuild.rebuild_pack_files(pack, root / 'mods', root / 'out')
                out = (root / 'out/slg_ctbl.dat').read_bytes(); a, b = Pidx(raw), Pidx(out)
                self.assertEqual(out[0x70:0x800], raw[0x70:0x800])
                self.assertEqual(out[0x1000:len(raw)], raw[0x1000:])
                self.assertEqual((b.entries[1].offset, b.entries[1].size, b.entries[1].zsize),
                                 (a.entries[1].offset, a.entries[1].size, a.entries[1].zsize))
                self.assertEqual(b.entries[0].zsize, 583)
                self.assertEqual(b.entries[0].offset == a.entries[0].offset, size == 16)
                blob = decompress_payload(out, b.entries[0].offset, b.entries[0].size, b.entries[0].zsize)
                entry = Fsts(blob).entries[0]
                self.assertEqual(decompress_payload(blob, entry.offset, entry.size, entry.zsize), content)


if __name__ == '__main__': unittest.main()
