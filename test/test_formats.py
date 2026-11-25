"""Synthetic binary fixtures: no copyrighted game assets are distributed."""
import unittest,sys,pathlib,struct,base64,tempfile,json
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'python'))
import tm4_bridge as tm4
import tm4_images as images
from tsid2 import Tsid

def block(magic,count,payload):
    payload+=b'\0'*((-len(payload))%16)
    return magic+struct.pack('<IIHH',count,16+len(payload),1,0)+payload
def tsid(speakers=(12,13)):
    return b'TSID'+struct.pack('<IIHH',2,32,1,0)+b'a\0b\0'+b'\0'*12+block(b'TSTT',2,b'char\0msg\0')+block(b'TSTD',2,bytes([3,9]))+block(b'TSDD',2,b'\x02\0'+bytes([speakers[0]])+ 'こんにちは\n%s\\h01'.encode('cp932')+b'\0\x02\0'+bytes([speakers[1]])+'こんにちは\n%s\\h01'.encode('cp932')+b'\0')

def speaker_asb(calls):
    d=bytearray(0x100);code=b''
    for args in calls:
        code+=bytes([len(args)])+b''.join(b'\x01'+struct.pack('<i',arg) for arg in args)+b'\x29\x13\0\0\0'
        code+=b'\x05\x01'+struct.pack('<I',7)+b'\x29\0\0\0\0'
    d[64:64+len(code)]=code
    d+=b'__main\0'+'こんにちは'.encode('cp932')+b'\0'
    struct.pack_into('<III',d,0x34,0x100,len(d)-0x100,len(d))
    return bytes(d)
def asb(ambiguous=False):
    source='こんにちは\n%s\\h01'.encode('cp932');d=bytearray(0x80)
    struct.pack_into('<I',d,0x34,0x80)
    setup=b'\x01\x01\x0c\0\0\0\x29\x13\0\0\0'
    code=setup+b'\x05\x01\0\0\0\0\x29\0\0\0\0'
    d[64:64+len(code)]=code
    if ambiguous:struct.pack_into('<I',d,0x70,0)
    d+=source+b'\0';struct.pack_into('<I',d,0x38,len(d)-0x80);struct.pack_into('<I',d,0x3c,len(d))
    return bytes(d)
def gim(fmt=5,order=1):
    width=32;height=8;psize=16 if fmt==4 else 256
    def chunk(kind,format_,w,h,bpp,payload,order_=0):
        header=bytearray(64);struct.pack_into('<HHHHHHHH',header,0,48,0,format_,order_,w,h,bpp,16)
        struct.pack_into('<III',header,24,48,64,64+len(payload));struct.pack_into('<HHHH',header,40,2,1,3,1)
        return struct.pack('<IIII',kind,16+len(header)+len(payload),16+len(header)+len(payload),16)+header+payload
    pal=b''.join(bytes([i,i,255-i,255 if i else 0]) for i in range(psize))
    image=chunk(4,fmt,width,height,4 if fmt==4 else 8,bytes([0x11 if fmt==4 else 1])*(width*height//(2 if fmt==4 else 1)),order)
    palette=chunk(5,3,psize,1,32,pal)
    body=palette+image
    return b'MIG.00.1PSP\0'+b'\0'*4+struct.pack('<IIII',2,len(body)+32,16,16)+struct.pack('<IIII',3,len(body)+16,16,16)+body

class TextTests(unittest.TestCase):
    def test_import_records_crc32_with_original_sha256(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            p=pathlib.Path(root)/'source.iso';p.write_bytes(b'123456789')
            identity=tm4.source_identity(p)
            self.assertEqual(identity['isoCrc32'],'CBF43926')
            self.assertEqual(identity['isoSha256'],hashlib.sha256(b'123456789').hexdigest())
            self.assertEqual(tm4.full_hash(p),identity['isoSha256'])
    def test_mc_roles_from_verified_character_ids_only(self):
        for char in (22,45):
            for args in ([char],[char,0,0,0,0]):
                with self.subTest(args=args):
                    raw=speaker_asb([args]);obj=tm4.descriptor('ASB',raw,['fixture'])
                    row=obj['rows'][0]
                    self.assertEqual(row['rowInfoText'],'MC')
                    self.assertEqual(row['speakerId'],char)
                    self.assertEqual(row['speakerGender'],'male')
                    self.assertEqual(row['speakerRole'],'protagonist')
                    self.assertTrue(row['speakerNameIsVariable'])
                    self.assertEqual(tm4.rebuild_resource(obj,{}),raw)
        rows=tm4.descriptor('TSID',tsid((22,45)),['fixture'])['rows']
        self.assertEqual([r['rowInfoText'] for r in rows],['MC','MC'])
        # Name-control selector 26 is NOT the player dialogue speaker ID.
        for char in (26,37,9999,1048576):
            row=tm4.descriptor('ASB',speaker_asb([[char]]),['fixture'])['rows'][0]
            self.assertNotIn('rowInfoText',row)
            self.assertNotIn('speakerGender',row)
        # The same string used by MC and another speaker is ambiguous.
        row=tm4.descriptor('ASB',speaker_asb([[22],[12]]),['fixture'],{12:'小林学'})['rows'][0]
        self.assertNotIn('rowInfoText',row)
        self.assertNotIn('speakerId',row)
        dynamic=bytearray(speaker_asb([[22]]));dynamic[65]=2
        self.assertNotIn('rowInfoText',tm4.descriptor('ASB',bytes(dynamic),['fixture'])['rows'][0])
    def test_tsid_context_speakers_noop_and_growth(self):
        raw=tsid()+b'END';obj=tm4.descriptor('TSID',raw,['a'],{12:'小林学',13:'七河正志'})
        self.assertEqual(len(obj['rows']),2);self.assertEqual(obj['rows'][0]['rowInfoText'],'小林学')
        self.assertNotEqual(obj['rows'][0]['context'],obj['rows'][1]['context'])
        self.assertEqual(tm4.rebuild_resource(obj,{}),raw)
        new=tm4.rebuild_resource(obj,{obj['rows'][1]['context']:'Hello there\n%s\\h01'})
        parsed=Tsid.parse(new);self.assertEqual(parsed.tsdd.records[0].fields[1][1], 'こんにちは\n%s\\h01'.encode('cp932'))
        self.assertEqual(parsed.tsdd.records[1].fields[1][1],b'Hello there\n%s\\h01');self.assertEqual(parsed.trailing,b'END')
    def test_asb_in_place_and_append(self):
        raw=asb();obj=tm4.descriptor('ASB',raw,['a'],{12:'小林学'})
        # The fixture includes zero words elsewhere in the code, so the zero
        # relative offset is intentionally ambiguous and cannot grow.
        row=obj['rows'][0];self.assertEqual(tm4.rebuild_resource(obj,{}),raw)
        out=tm4.rebuild_resource(obj,{row['context']:'Hi\n%s\\h01'});self.assertEqual(out[:0x80],raw[:0x80])
        with self.assertRaisesRegex(ValueError,'fixed budget'):tm4.rebuild_resource(obj,{row['context']:'A long translation that cannot fit\n%s\\h01'})
        # Nonzero offset used only in one recognised instruction can grow.
        d=bytearray(raw);d[0x80:0x80]=b'__main\0';struct.pack_into('<I',d,77,7)
        struct.pack_into('<I',d,0x38,len(d)-0x80);struct.pack_into('<I',d,0x3c,len(d))
        obj=tm4.descriptor('ASB',bytes(d),['a'],{12:'小林学'});row=obj['rows'][0]
        self.assertTrue(row['canGrow']);self.assertEqual(row.get('rowInfoText'),'小林学')
        out=tm4.rebuild_resource(obj,{row['context']:'A long translation that can now grow\n%s\\h01'})
        rel=struct.unpack_from('<I',out,77)[0];self.assertGreater(rel,7)
        self.assertEqual(out[0x80+rel:].rstrip(b'\0'),b'A long translation that can now grow\n%s\\h01')
        self.assertEqual(out[0x80:len(d)],d[0x80:]);self.assertEqual(struct.unpack_from('<I',out,0x3c)[0],len(out))
    def test_message_box_line_policy_and_classification(self):
        d=bytearray(asb());d[0x80:0x80]=b'__main\0';struct.pack_into('<I',d,77,7)
        struct.pack_into('<I',d,0x38,len(d)-0x80);struct.pack_into('<I',d,0x3c,len(d))
        obj=tm4.descriptor('ASB',bytes(d),['a']);row=obj['rows'][0]
        self.assertEqual(row['messageType'],'messageBox')
        for text in ('Hello %s\\h01','Hi\nthere\n%s\\h01'):
            out=tm4.rebuild_resource(obj,{row['context']:text})
            self.assertEqual(dict(tm4.asb_strings(out))[7],text.encode('cp932'))
        for text in ('a\nb\nc\n%s\\h01','x'*45+'%s\\h01','Hello %s\\h02'):
            with self.assertRaises(ValueError):tm4.rebuild_resource(obj,{row['context']:text})
        with self.assertRaisesRegex(ValueError,'line count'):
            tm4.rebuild_resource(obj,{row['context']:'Hello %s\\h01'},{'preserveLineCount':True,'maxLines':3,'maxCharsPerLine':44})
        unknown=tm4.descriptor('ASB',asb(),['a']);self.assertEqual(unknown['rows'][0]['messageType'],'unknown')
        with self.assertRaisesRegex(ValueError,'line count'):
            tm4.rebuild_resource(unknown,{unknown['rows'][0]['context']:'Hello %s\\h01'})
    def test_csv_quotes_newlines_and_missing(self):
        raw='1,名前,"日本,語"\r\r\n0,備考,x\r\n'.encode('cp932');obj=tm4.descriptor('CSV',raw,['a'])
        self.assertEqual(tm4.rebuild_resource(obj,{}),raw)
        out=tm4.rebuild_resource(obj,{'cell/0/1':'Name, surname','cell/0/2':'Japanese'})
        self.assertEqual(out.decode('cp932'),'1,"Name, surname","Japanese"\r\r\n0,備考,x\r\n')
    def test_validation_rejects_lines_codes_nul_and_encoding(self):
        for value in ['Hello %s\\h01','Hello\n%s','Hello\n%d\\h01','Hello\n%s\\h01\0']:
            with self.assertRaises(ValueError):tm4.validate('こんにちは\n%s\\h01',value)
        with self.assertRaises(UnicodeError):tm4.validate('こんにちは','😀')
        self.assertEqual(tm4.validate('こんにちは','Hello—world').decode('cp932'),'Hello-world')
    def test_dash_before_hey_cannot_inject_name_control(self):
        # The old conversion made \h across a CP932 character boundary.
        self.assertIn(b'\\h','―hey'.encode('cp932'))
        # A leftover 81 byte before 星 (90 AF) becomes ＄ (81 90) plus
        # half-kana ｯ (AF), which this scenario renderer skips.
        self.assertEqual((b'\x81'+'星川さん'.encode('cp932')).decode('cp932'),'＄ｯ川さん')
        source='……なさい！\n起きなさいよー、ねぇってば！\n起きなさーい！'
        draft="……Wake up!\nWake up already—hey, I'm talking to you!\nWake up!"
        raw=tm4.validate(source,draft)
        self.assertIn(b'already-hey,',raw)
        self.assertNotIn(b'\\h',raw)
        self.assertIn('—hey',draft)  # normalization is export-only
        for text in ['―hey','―h01','ソk26','―next']:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'trail-byte escape collision'):
                tm4.validate('こんにちは',text)
        self.assertEqual(tm4.validate('名前\\h01','Name\\h01'),b'Name\\h01')
        self.assertEqual(tm4.validate('名前\\k26','Name\\k26'),b'Name\\k26')
        self.assertEqual(tm4.validate('こんにちは','――'), '――'.encode('cp932'))
    def test_control_parameters_are_preserved(self):
        for original,changed in [('h00','h01'),('i26','i08'),('j26','j09'),('k26','k00'),('m01','m03'),('p01','p02'),('g01','g02'),('d01','d02'),('s16','s24'),('v100','v050'),('cffffffff','c00000000')]:
            with self.subTest(original=original):
                self.assertEqual(tm4.validate('名前\\'+original,'Name\\'+original),('Name\\'+original).encode('ascii'))
                with self.assertRaisesRegex(ValueError,'control codes'):tm4.validate('名前\\'+original,'Name\\'+changed)
        self.assertEqual(tm4.validate('名前\\nPlayStation','Name\\nPSP'),b'Name\\nPSP')
        self.assertEqual(tm4.validate('こんにちは','―v100'),'―v100'.encode('cp932'))
        for letter in 'cdeghijkmnprsxz':
            with self.subTest(letter=letter),self.assertRaisesRegex(ValueError,'trail-byte escape collision'):
                tm4.validate('こんにちは','―'+letter+'00')
    def test_budget_counts_stored_control_bytes_before_expansion(self):
        self.assertEqual(len(tm4.validate('名前\\h00','Hi\\h00')),6) # Hi=2, token=4
        self.assertEqual(len('星川さん'.encode('cp932')),8)
        obj=tm4.descriptor('ASB',asb(),['fixture']);row=obj['rows'][0]
        suffix='\n%s\\h01';suffix_bytes=len(suffix.encode('ascii'))
        exact='X'*(row['byteLength']-suffix_bytes)+suffix
        out=tm4.rebuild_resource(obj,{row['context']:exact})
        self.assertEqual(len(out),len(asb()))
        with self.assertRaisesRegex(ValueError,'fixed budget'):
            tm4.rebuild_resource(obj,{row['context']:'X'+exact})
    def test_malformed_inputs(self):
        with self.assertRaises(ValueError):tm4.asb_strings(b'x'*12)
        with self.assertRaises(ValueError):tm4.csv_cells('"broken')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):tm4.safe(root,'../escape')

class TsidHeaderTests(unittest.TestCase):
    @staticmethod
    def fixture():
        raw = bytearray(tsid())
        parsed = Tsid.parse(raw)
        string_bytes = sum(len(v) + 1 for rec in parsed.tsdd.records for typ, v in rec.fields if typ == 9)
        start = parsed.data_off + sum(b.size for b in parsed.blocks if b.magic != b'TSDD')
        struct.pack_into('<HH', raw, start + 12, string_bytes, len(parsed.tsdd_pad))
        return bytes(raw)

    def test_string_pool_and_padding_headers_follow_growth_and_shrink(self):
        raw = self.fixture()
        self.assertEqual(Tsid.parse(raw).encode(), raw)
        for value in (b'A', b'Translated full character name'):
            table = Tsid.parse(raw)
            table.tsdd.records[0].fields[1] = (9, value)
            out = Tsid.parse(table.encode())
            expected = sum(len(v) + 1 for r in out.tsdd.records for typ, v in r.fields if typ == 9)
            self.assertEqual(out.tsdd.f1, expected)
            self.assertEqual(out.tsdd.f2, len(out.tsdd_pad))
            self.assertEqual(out.tsdd.records[0].fields[1][1], value)
            self.assertEqual(out.tsdd.records[1].fields, Tsid.parse(raw).tsdd.records[1].fields)
            # Repeated encoding does not retain stale size/padding bookkeeping.
            self.assertEqual(table.encode(), table.encode())

    def test_raw_payload_override_recomputes_the_same_loader_headers(self):
        raw = self.fixture(); table = Tsid.parse(raw)
        edited = Tsid.parse(raw); edited.tsdd.records[1].fields[1] = (9, b'A longer English name')
        expected = edited.encode()
        self.assertEqual(table.encode(edited._encode_tsdd_payload()), expected)

    def test_unrecognised_pool_convention_is_preserved_and_normal_overflow_rejected(self):
        unknown = Tsid.parse(tsid()); original = unknown.tsdd.f1
        unknown.tsdd.records[0].fields[1] = (9, b'Longer name')
        self.assertEqual(Tsid.parse(unknown.encode()).tsdd.f1, original)
        table = Tsid.parse(self.fixture()); table.tsdd.records[0].fields[1] = (9, b'A' * 65536)
        with self.assertRaisesRegex(ValueError, '16-bit header budget'): table.encode()

class ImageTests(unittest.TestCase):
    def test_gim_index4_and_8_normal_and_swizzled(self):
        from PIL import Image
        import io
        for fmt in [4,5]:
            for order in [0,1]:
                with self.subTest(fmt=fmt,order=order):
                    raw=gim(fmt,order);png,w,h,_=images.png_bytes(raw)
                    self.assertEqual((w,h),(32,8));self.assertEqual(images.replace(raw,png),raw)
                    im=Image.open(io.BytesIO(png)).convert('RGBA');im.putpixel((17,4),(0,0,255,0));buf=io.BytesIO();im.save(buf,format='PNG')
                    out=images.replace(raw,buf.getvalue());decoded,_=images.decode(out)
                    self.assertEqual(decoded.getpixel((17,4)),(0,0,255,0));self.assertEqual(decoded.getpixel((16,4)),(1,1,254,255))
                    self.assertEqual(len(out),len(raw))
    def test_gim_bad_header(self):
        with self.assertRaises(ValueError):images.decode(b'bad')

class ValidationPolicyTests(unittest.TestCase):
    def test_optional_name_policy_preserves_physical_and_functional_guards(self):
        warn={'rules':{'nameCodes':'warn','lineWidth':'warn','lineCount':'warn'}}
        self.assertEqual(tm4.validate('Hello \\h09','Hello',policy=warn),b'Hello')
        with self.assertRaises(ValueError):tm4.validate('Hello \\h09','Hello',policy={'rules':{'nameCodes':'block'}})
        with self.assertRaises(ValueError):tm4.validate('Hello \\h09','Hello \\h10',policy=warn)
        with self.assertRaises(ValueError):tm4.validate('%s \\h09','Hello',policy=warn)
        with self.assertRaises(ValueError):tm4.validate('%s %d','%d %s',policy=warn)
        with self.assertRaises(UnicodeError):tm4.validate('Hello','😀',policy=warn)
        layout={'preserveLineCount':False,'maxLines':3,'maxCharsPerLine':44}
        self.assertEqual(len(tm4.validate('Hello','A'*45,layout,warn)),45)
        with self.assertRaises(ValueError):tm4.validate('Hello','1\n2\n3\n4',layout,warn)
        obj=tm4.descriptor('ASB',asb(ambiguous=True),['fixture'])
        with self.assertRaises(ValueError):tm4.rebuild_resource(obj,{obj['rows'][0]['context']:'A'*200+' %s\\h01'},validation_policy=warn)

if __name__=='__main__':unittest.main()
