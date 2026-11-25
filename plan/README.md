# Format and validation notes

Control-code catalog, selector IDs and storage-versus-rendering budget rules:
[CONTROL_CODES.md](../CONTROL_CODES.md).

Detailed diagnosis, solution and reusable emulator automation:
[Half-width text and PPSSPP testing](half-width-and-ppsspp.md).

Source: the user-supplied Japanese PSP ISO and its local tm4_translation docs.
Implementation date: 2026-11-02. No source game data is bundled with the add-on.

## Name-table startup loading fix (1.2.3)

Translating the shared name tables exposed two separate loader requirements.
TSID `TSDD.f1` is the total byte length of type-9 strings including their NULs;
`TSDD.f2` is trailing record padding. The old writer retained both values after
translation. For `girl_a_name.dat`, the pool grew from 95 to 122 bytes but the
header still requested only 95. Fixing layout alone then exposed heap corruption
in the InitGame thread, with English name bytes used as free-list pointers.
The original user research documents this in `docs/02-text-formats.md`, section 1.

`tsid2.Tsid` now recognises the original pool-size convention on parse, recomputes
pool size and padding on encode (including raw payload overrides), and rejects
overflow of the 16-bit allocation field. The single voice-table variant keeps
its original pool convention. Exact identity round trips were checked against
all 740 unique original TSIDs: 739 use the measured convention, one is preserved.
Growth/shrink, repeated encode, raw overrides and overflow fixtures are in
`test/test_formats.py`. Stored translations and numeric fields are untouched.

The archive layer also has a loader-sensitive container layout.
The older full FSTS repack moved untouched members of `slg_ctbl.dat` and caused
an immediate NOW LOADING stall. The user research already records this rule in
`tm4_translation/docs/01-containers.md`, section 3. Archive decoding alone missed
it: the old ISO contained all expected translated bytes, but did not boot.

`rebuild.build_fsts` now starts from original bytes, preserving reserved header
fields, the name table, padding and all untouched entry positions and metadata.
A changed file reuses its gap to the next original entry if it fits; otherwise
it appends at 16-byte alignment. Shared/aliased payloads are never overwritten
for just one owner. Identical replacements are exact no-ops. Outer PIDX archives
likewise retain their original layout, reuse space or append a changed FSTS,
and preserve the outer `zsize` type flag (583 for `slg_ctbl`), not treating it
as a compressed byte length. Unrelated outer archives are not rebuilt.

The failing build was actually the newer `.translated-2.iso` beside the user's
supplied `.translated.iso`; the older file had only five ASB changes and booted.
The failing one has 41 translated resources and 77 destinations. Layout-only
repair of its 36 changed shared tables preserves all 583 member contents, keeps 547 untouched
entries exact, and in this case requires no member-offset changes at all.
Synthetic regressions are in `test/test_archives.py`, covering gap writes,
append growth, aliases, reserved bytes, no-ops and unaffected outer archives.
That initial repair was insufficient because TSID allocation headers were still
stale; the final fix must include both layers. Existing projects need no
migration; re-export with the updated writer.

Verified 2026-11-06 through the actual live Translator++ Inject/export hooks:
41 translated resources (78 destinations including the Bold atlas), all 36
translated shared name tables preserved field-for-field, 547 untouched shared
entries retained at their original offsets, and valid pool/padding headers.
The final ISO is `rebuild-iso2/fixed-export/Tokimeki Memorial 4 (Japan).translated-2.iso`
in the user's research folder. An isolated PPSSPP 1.20.4 cold boot passed startup
with bad-memory-access ignoring disabled, reached New Game's first dialogue,
and verified all 13 font patch words plus ASCII `W` advancing 112→120. The
heavier opening text was visually checked. This does not establish a full-game
playthrough or physical PSP compatibility. All 18 add-on Node tests passed,
including the 15 format, four archive and eight font Python cases they invoke.
Private evidence: `artifacts/tm4-loading-fix/final-scene.json`,
`final-verification.json`, `final-opening.png` and `live-export.json`.

## Bold Latin option (1.2.2)

Half-width alphabet settings now offer Regular/Bold. Bold changes the original
Latin/digit atlas pixels while retaining the verified 8-pixel spacing patch and
all storage budgets. Existing projects default to Regular; Update preserves the
chosen weight. See the [font findings](half-width-and-ppsspp.md#optional-bold-latin-122-2026-11-06)
for the exact atlas guard, shared full-width Latin behaviour and verification.

## Translation context, AI limits and source CRC (1.2.0)

Compatibility correction (1.2.1): missing CRC settings or a null/empty/whitespace
expected CRC skip the optional check before any source read, even if an enabled
flag exists. Pre-CRC projects receive disabled defaults without needing the ISO
for migration. Import no longer rejects a partially configured missing CRC.
Explicit configured mismatches and one-injection bypass behaviour remain intact.

`translation-guidance.json` contains the short game/engine prompts, typed text
limits and editable cast defaults. `tm4Psp.guidance.js` applies missing defaults
without overwriting edited prompts, reference cells or limits. A normal Actor
Reference file declares `actorInfoColumn:2`; the host excludes that column from
row-header/name lookup and uses it as AI glossary context when no explicit
translator information column is selected. Speaker metadata connects the cast
even when dialogue never mentions the speaker's own name.

Actor names are given-name-first ASCII transliteration defaults. The profile
records source URLs for personality facts and labels voice directions as
editorial. Sources: [character overview](https://navio.blog/tokimemo4-chara/),
[additional cast descriptions](https://en.wikipedia.org/wiki/Tokimeki_Memorial_4),
[Manabu](https://w.atwiki.jp/tokimeki_dictionary/pages/405.html), and
[Tadashi](https://w.atwiki.jp/tokimeki_dictionary/pages/406.html).
Rizumi Kyono/Rhythmy Kyono is an explicitly recorded naming alternative.
MC's role follows the measured game-table evidence in the MC speaker-role section.

Read-only ASB inventory: 19,782 single-line, 20,178 two-line and 13,509 three-line
occurrences. Three is therefore the observed scenario line maximum. The default
44 stored characters per line is a configurable English editorial guideline,
not a reverse-engineered display-width limit. Preserve source actual/literal
line counts. TSID/CSV use CP932/control validation without scenario line caps;
images and reference tables opt out of those restrictions.

The shared `TranslationConstraints` snapshots per-occurrence byte caps and
layout/character rules. `canGrow:false` keeps original CP932 storage budgets;
other ASB/TSID/CSV text stays byte-unrestricted. AI prompt tables use local IDs,
including for concurrent/split batches and selected duplicate rows. Validation
uses restored text, so masking placeholders/JSON escaping do not inflate budgets.
Preview restoration exposed destructive placeholder lookups; JSON/HTML/XML/JS
cloak lookups now retain their maps across previews and corrective turns. Errors
include grid row, actual size, limit and required reduction; prior assistant
replies and errors are retained in the next request. Exhaustion and post-correction
overflow cannot overwrite drafts. The HTTP tool `translation.constraints.read`
returns the same rules to agents in bounded ranges.

Import now streams SHA-256 and CRC32 together. The inspected original ISO has
CRC32 `8C6E35CD` (SHA-256 remains the imported manifest's identity). Optional CRC
is off initially and persists in `init.sourceChecksum`. The portable ISO writer
checks it before building. A deliberate `custom.tm4SkipCrc:true` only skips that
operation's optional CRC; mandatory source/revision/resource guards continue.
The checkbox resets whenever Inject opens. Reports record the CRC status.

Validation on 2026-11-04: current project received both prompts, 15 actor entries,
scenario limits and its recorded source CRC and was saved. All 1,309 pre-existing
file/reference contents, translation cells, contexts and row metadata were
compared with the pre-change backup and preserved (empty-row padding normalized).
The live actor header returns `Manabu Kobayashi`, not biography text. A local
mock reply exceeded a real 57-byte row, followed by a corrective conversation
containing that reply and its size error; no provider was called and no game
translation cell was written. The real source CRC also matched independently in
Python and JavaScript. See the reusable API guide for boundaries and retry policy;
this metadata/AI change does not claim a new full-game ISO or emulator validation.
All 108 targeted tests passed, including shared request/selected/batch regression
coverage, constraint/CRC helpers and TM4 binary/font/integration suites. Both
parser/guidance module wrappers compiled with NW.js and loaded in the live app;
the compiled parser classified the real staged scene and the guidance populated
all 15 cast entries. The live settings form exposed the saved limits/CRC controls.
Save/reopen serialization keeps reference files under `project.references`;
Update explicitly carries actor edits from either that representation or live
`project.files`, with regression coverage for the serialized representation.

The format is ISO9660 -> PIDX -> raw FSTS or direct payload -> Konami ` 3;0`
or ` 3;1` wrapping (zero-initialised 4096-byte LZSS ring, XOR 0x72). Both the
PIDX prefix inside tokimeki.dat and tokimeki.idx must be patched on relocation.

Text formats: TSID typed TSTT/TSTD/TSDD records; ASB NUL-terminated CP932
string tables with static relative offsets; CP932 CSV cells with exact spans.
Some TSID names/field names contain Japanese, despite the research notes
describing them as ASCII. Decode those as CP932 too.

Observed imported inventory after grouping byte-identical archive copies:

| Kind | Resources with text | Rows |
|---|---:|---:|
| ASB | 109 | 53,469 |
| TSID | 182 | 5,709 |
| CSV | 8 | 778 |
| Total | 299 | 59,956 |

These are extracted occurrences. Translator++ displays 58,361 distinct source
rows; repeated strings retain every context and its associated speaker/byte
budget on their shared row. Context translation can override each occurrence.

The research dump's ASB total 53,474 counts tm4base.asb twice; its five text
strings occur in both the main archive and event_base.dat. One project resource
updates both copies. Many of the 740 unique TSID files contain only numbers or
internal identifiers and therefore produce no translation rows.

Speaker names use fullname records from girl_[a-l]_name.dat and
mate_[mn]_name.dat. ASB extraction accepts an immediately preceding static
message-setup call 0x13 and a consistent character ID across recognised uses.
Single-argument and five-immediate-argument forms are supported. No name is
invented for dynamic calls or unmapped IDs. Row parameters retain numeric speaker
IDs and evidence. The initial import had 27,798 named occurrences; version 1.1.3
adds the verified player role described below. Opening dialogue also resolves
小林学 and 七河正志.

## MC speaker role (1.1.3)

The user-selected player name must not be guessed from a default save or confused
with the separate name-control selector namespace. Read-only inspection of the
supplied disc's tables establishes these zero-based **char_char** record IDs:

| Speaker ID | Original record / evidence | Row information |
|---|---|---|
| 22 | `char_100`, `attr = 0`; `char_attr[0]` is `attr_player` | MC |
| 45 | `char_214`, `char_name` and `char_mes_name` are `あなた`; the player before name entry in the opening | MC |

The supported executable's name resolver at guest `0x08870ea8` reads
`char_char.attr`, compares with `char_attr.attr_etc`, then uses either the
character object's runtime name or the table's `char_name`. This corroborates
the table namespace. **Speaker 26 is not MC**: it is `char_001` / `mate_001`;
the decimal control selector `\i26` uses a different dispatch.

`speaker-roles.json` is shared by Python extraction and the Node adapter.
Verified MC occurrences receive `rowInfoText: "MC"`, `speakerRole: "protagonist"`,
`speakerGender: "male"`, and `speakerNameIsVariable: true`, while keeping their
original numeric ID and instruction evidence. Ambiguous references, dynamic
speaker expressions, hidden-speaker labels and unrecognised IDs remain
unresolved. Existing nonempty user labels/metadata are preserved by migration.
Gender metadata is available to agents; engines must use their own actor/context
settings to forward it, since arbitrary row parameters are not universal prompts.

New extraction labels these roles directly. `parseFile` also enriches older
staged descriptors, so no stage rewrite or disc rescan is required. The add-on's
`onLoadTrans.tm4SpeakerRoles` hook upgrades opened projects idempotently, marks
changed metadata for saving and refreshes the grid. No text cell or control code
is modified.

Validation on 2026-11-04: fresh extraction from all staged raw resources found
10,357 occurrences with ID 22 and three with ID 45. The current live project was
updated and saved: 10,360 occurrences in 10,180 distinct rows across 98 files;
the opening player line reports `MC` through `trans.getRowInfoText`. Comparison
with the pre-change project preserved all source/translation cells, contexts and
non-role metadata (normal empty-row padding/index cache excluded). Synthetic
fixtures cover one/five-argument calls, TSID character fields, conflicting
speakers, dynamic calls, selector-ID confusion, older descriptors and reopen
migration. All 14 Node module/integration tests passed, including Python format
and font suites. An NW.js-compiled business-module wrapper loaded in the live
app and resolved MC from an older opening-scene descriptor. This changes editor
metadata only; no new ISO or emulator boot is needed to validate the labels.

The import includes 1,009 unique editable interface textures after excluding
gallery CG/portrait folders. All decoded without a format failure. Local Windows
OneOCR found 661 text blocks in 174 of these images. Empty OCR results stay
editable. GIM palettes remain unchanged on export, so artwork colours are
limited to the source palette for indexed images.

Validation performed:

- Node module/worker tests and Python synthetic binary fixtures passed.
- Read-only extraction/no-op checks passed against all 740 unique TSID files
  and the full supplied ASB/CSV dump. Seven title GIM PNG round trips were exact.
- Live project creation, staging and save succeeded; the original ISO hash is
  stored in the project and checked again on every export.
- Save/reopen retains all 59,956 source contexts, their speaker parameters,
  and all 661 OCR boxes (including 12 repeated-text boxes). The host normally
  discards repeated source rows; text contexts are merged before sanitization,
  and the add-on preserves its positional image boxes through that step.
- A real ISO test changed one TSID record, one long ASB line (append + patched
  operand), one CSV cell and one GIM pixel. Five archive member copies were
  changed. All modified members were re-extracted and matched the expected
  bytes; resulting ISO size was 1,774,354,432 bytes.
- Folder export and the registered Inject handler both rebuilt a selected menu
  table. A no-op ISO matched the imported disc's SHA-256; the source ISO hash
  remained unchanged. ZIP export passed a full 7-Zip integrity test.
- A real project update re-scanned the ISO, retained a test translation and
  copied its edited image layer into the new cache. Test edits were then removed
  and the translation-ready project was saved and reopened.

At initial release, font rendering and gameplay were unverified. The half-width
opening-scene checks below supersede that limitation for the tested scene only.
Stale PIDX hashes on other execution paths and broader gameplay still need checks.

## Relocated source ISO (1.0.1)

The common Inject handler already passes its Source material folder to
`injectCopyMaterials`. The initial add-on ignored that argument and always
built from `options.init.entryPoint`, producing a missing-file error after the
disc moved. The add-on now carries this source through its own task options,
separately from staged text/image resources. Explicitly selected sources take
priority, even when the old path still exists. Files and one-level directories
are accepted; checksum matching identifies the original disc, including renamed
files. Export can also find a same-name ISO in its adjacent same-name folder.
Checksum-verified moves update the source paths and project location, even if
translation validation then reports a separate text issue. Regression
tests cover missing sources, explicit-source precedence, renamed files, multiple
candidate images, wrong-disc rejection and automatic nearby relocation.
The live registered Inject path was exercised with the user's moved ISO and
an empty translation selection to isolate path handling. It produced a full
disc copy and saved the verified location, preserving all eight current draft
translations and their contexts. Full-draft validation also revealed an
independent fixed-budget overflow (scespa01.asb, string/718); this is reported
without truncating or editing the user's translation. Initially em dashes were
mapped to CP932's horizontal bar. The 1.1.1 correction below replaces that
unsafe conversion with an ASCII hyphen during export only.

## ASB byte budgets versus message-window width

2026-11-09: the user confirmed that message-box ASB dialogue can render with
fewer lines than its Japanese source. The parser now marks strings whose every
detected reference matches the direct display-function-0 operand as
`messageType: messageBox`. Old projects can recover the same classification from
`canGrow:true`; unknown or mixed references remain strict. Default layout allows
1–3 lines and 44 stored characters per line; an exact-source-line option remains
available. Synthetic extraction/reinsertion checks cover fewer/more lines, caps,
strict mode and unchanged controls. This is not a new emulator verification of
every layout. Raw offsets, byte budgets and stable string contexts are unchanged.

Confirmed from the live project's row metadata and the exporter on 2026-11-02:
`scespa01.asb`, context `string/718`, has `byteLength: 57` and `canGrow: false`.
Its source contains 29 characters across two lines. The draft translation
required 83 CP932 bytes, exceeding the original slot by 26 bytes. The observed
grid row was 15; the stable identity is the file plus `string/718`.

`byteLength` comes from the original raw string bytes, excluding the terminating
NUL. It is not a pixel width, a character-count limit, or a measurement of the
message window. ASCII usually takes one CP932 byte and Japanese characters
usually take two; actual newline bytes and literal escape/control-code bytes
count toward the same budget. The exporter protects non-newline controls in
every mode and preserves source line counts for strict/unclassified text.

For a fitting replacement, the exporter overwrites the original slot, retaining
the terminator and zero-filling unused bytes. For a longer replacement, it can
append the string and patch relative offsets only when every detected reference
matches its recognised static operand pattern. It updates the ASB header sizes
after appending. Otherwise, it rejects the translation instead of moving an
unrecognised reference or truncating the text.

Consequently, `canGrow: false` describes the current relocation analysis, not a
proven hardware or game-renderer limit. The conservative reference scan may
include ambiguous matches; improving bytecode/reference decoding could remove
some fixed-budget restrictions. TSID/CSV growth and ASB append-and-patch already
demonstrate that PSP translation is not universally limited to the source byte
length. Visual text fit still depends on the game's font, line layout and window
dimensions and must be checked separately in the game.

## Confirmed half-width scenario text (1.1.0, 2026-11-03)

The original renderer has an ASCII-to-SJIS lookup table and usable Latin glyphs
in its existing atlas. Missing scenario ASCII was not an absence of glyph art:
the scenario loop explicitly skipped records with a zero high byte. It draws
each character separately and advances its own X position by 16; changing only
the shared renderer's ASCII width therefore did not fix scenario text.

The successful patch has three parts:

1. Shared advance helper `08834ff0`: return half the requested glyph size for
   ASCII; retain the double-byte path. Use a PC-relative branch into the existing
   return sequence so no new absolute-jump relocation is necessary.
2. Shared ASCII drawing path `08835d9c`: use the existing 0.5 constant instead
   of 0.75 for the glyph quad width. The original 16-pixel height is retained.
3. Scenario loop `088710f8`–`08871138`: accept single-byte ASCII, serialize its
   byte plus NUL for the shared renderer, and advance 8 instead of 16. Double-byte
   CP932 remains 16 pixels. Previously unsupported single-byte kana remain
   skipped. Newline handling sits outside this patched block and is unchanged.

Addresses are guest RAM after relocation at base `08804000`; the code segment's
ELF file offset is `guest - 08804000 + c0`. LWC1 also has a loader relocation:
the patched file word is `c4405480`, which becomes `c4409480` in this runtime.
Writing the runtime immediate directly into the ELF would select a wrong
constant. The 13 original/new words are listed with checks in `tm4_font.py`.

Supported decrypted executable SHA-256:
`7068e4cb62a1eb2761d207564182fddb72dcb7703f1ffc2d292b5b88a4f5886d`.
Patched SHA-256:
`f249b7bd0c4ba9b7a7e11053dac1653dc69329726fdf2980ed4f87b7314bb8c2`.
The file is 4,631,376 bytes. Both fingerprint and original instruction words
must match before patching. No executable is bundled. The user's selected
original ELF is validated, staged in `data/font/tm4-decrypted-eboot.bin`, and
referenced by relative path from `project.options.init.halfWidthFont`.
Export verifies the staged ELF again and checks the resulting ISO's EBOOT bytes.

The original ISO's EBOOT is encrypted and BOOT.BIN is a zero-filled dummy.
PPSSPP's decrypted executable dump supplies the patch input. A separate ISO
with the unsigned ELF boots in PPSSPP; stock PSP compatibility is not claimed.
Physical PSP testing and custom-firmware compatibility remain unverified.

Observed in isolated PPSSPP 1.20.4 after a fresh boot into New Game, skipping
the opening videos and reaching the first wake-up message:

```text
ABC abc!
ＡＢＣ abc!
日本語 ABC xyz
```

Unpatched scenario code omitted all ASCII in this comparison while retaining
`ＡＢＣ` and `日本語`. The patched ISO shows all three lines: ASCII occupies
half the width, full-width Latin/Japanese retain their size, and line breaks
remain correct. The user independently supplied a screenshot confirming this
result. There is no replacement font atlas, unused-kanji bank, variable-width
lookup table or two-letter glyph encoding in the released patch.

The benefit is one-byte ordinary Latin characters with half-width rendering;
it does **not** enlarge an ASB slot. Fixed byte budgets, line-count validation,
control-code preservation and conservative relocation checks still apply.
For example, an 83-byte ASCII draft cannot occupy a 57-byte fixed slot merely
because the glyphs are narrower. No existing drafts are shortened automatically.

Integration verification:

- Synthetic MIPS execution tests cover every printable ASCII character,
  Japanese/ASCII mixed spacing, branch delay slots, and skipping half-kana.
- Tests reject encrypted, dummy, changed and already-patched executables; check
  instruction guards; and cover font-only export and disabled no-op export.
- UI integration tests cover creation, configuring/enabling, failed configuration,
  preserving the disabled setting through Update, and passing it through Inject.
- The NW.js compiler built the business module; its bytecode loaded in the live
  app and validated the real executable with the expected patched fingerprint.
- Enabled and saved the existing project. SHA-256 over all file data, contexts
  and row parameters was identical before/after configuration:
  `39db3d80b8f9fd9b44860ea7166c2a80bd42fbebebc485aafac724be98db049a`.
- The normal Inject/export hooks built an ISO from the original disc with the
  patch plus just the user's opening-line translation. All modified archive
  members and the EBOOT bytes passed post-build verification. The test ISO is
  1,774,354,432 bytes; the report records one changed text resource and the font
  profile. This was a deliberately limited export, not approval or a successful
  full export of every current draft.
- Cold-booted that exported ISO and reached the opening scenario again. The
  first ASCII `W` in the user's draft was drawn at X=112 and advanced to X=120,
  confirming the 8-pixel advance in the permanent exported executable.
- The live configuration dialog opens with its file picker and enabled state;
  closing it preserves the saved project and its unmodified state.

Developer-only evidence is under `artifacts/tm4-font-lab` (ignored, not shipped).
Only an isolated PPSSPP copy was used for testing; original ISO bytes and the
user's main emulator configuration/saves were not changed.

## Em-dash/name substitution correction (1.1.1)

The user later reported `＄川さん` inside `Wake up already—hey, ...`.
The 1.0.1 encoder's em-dash→horizontal-bar alias was unsafe: CP932 `―` is
`81 5C`, and the following `hey` made a raw-byte `\h` escape across that
character boundary. The game substituted a name inside the English sentence.
An orphan `81` paired with `星`'s `90 AF` yields `＄ｯ`; skipped half-kana
then explains the visible dollar sign before `川さん`.

Export now maps Unicode em dash to ASCII hyphen and rejects analogous
CP932-trail-backslash collisions before `h`, `k` or `n`. Genuine authored codes
remain protected. Saved drafts and the font executable patch are unchanged.
The regression fixture includes the complete opening draft and the dollar/kana
byte pairing. See the detailed guide's follow-up section for the diagnosis.

A fresh boot of the corrected test ISO was checked at the scenario drawing
loop: all 60 processed character records matched the expected opening message,
including `already-hey`, with no Japanese-name insertion. The test result is
recorded in `artifacts/tm4-font-lab/dash-fix-scene.json`.


## Configurable validation policy (1.2.5)

The shared Block/Warn/Off policy classifies only contextual `\hNN` address
omissions as optional. Added/duplicated address codes and changed selectors
remain invalid. The native writer consumes the project init snapshot, retains
functional control/printf argument order, CP932 encoding and trail-byte checks,
fixed ASB capacity, source-resource identity and the three-line message-box
maximum. The editable stored-character width is a guideline in Warn/Off modes.
No format signatures, extraction IDs, contexts or original resources change.
Verified with synthetic native fixtures, Node integration checks and shared
validator/browser UI tests. No new emulator or physical PSP check is claimed.
