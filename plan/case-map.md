# Case map: Tokimeki Memorial 4 PSP

Which part of this add-on to read for each kind of change. Read only the
section you need.

| Problem | Targeted source/reference |
|---|---|
| PIDX/FSTS/compression, ASB/TSID/CSV, supported profile | [Format plan](../plan/README.md); its **Name-table startup loading fix** section covers FSTS layout preservation and TSID string-pool/padding headers; `python/tm4_bridge.py`, `pidx.py`, `rebuild.py`, `tsid2.py`, `iso9660.py` in that add-on |
| String-reference growth, budgets and speakers | Format plan's ASB/speaker sections and **MC speaker role (1.1.3)**; bridge `reference_map`, `simple_ref`, `asb_speaker`, `speaker_metadata`, `rebuild_resource`; shared `speaker-roles.json` |
| Control selectors, date/place substitutions, byte counting | [CONTROL_CODES.md](../CONTROL_CODES.md); `control-code-inventory.json`; bridge `TOKEN`, `ESCAPE_PREFIXES`, `validate` |
| Source moved; Inject/update/reopen or images | `tm4Psp.module.js` source resolution/export; `tm4Psp.js` host hooks; [README](../README.md) |
| GIM pixels/palettes | `python/tm4_images.py` and image fixtures; format plan |
| Half-width font, loader relocations or PPSSPP | [Investigation](../plan/half-width-and-ppsspp.md), only the relevant section; `python/tm4_font.py` |

Use `rg -n` for those symbols/headings, then read the enclosing function/section.
Do not load all Python codecs or the full reverse-engineering transcript first.

The original em-dash/name regression was in export encoding;
fixing it did not require changing the verified 13-word font patch.

Evidence: mixed ASCII/Japanese opening scene was user-confirmed; the fixed
opening export was cold-booted and its full processed message checked. This is
not a completed full-game translation or physical PSP verification. Broader
support claims must add their own evidence.

Run the relevant commands from [AGENTS.md](../AGENTS.md). Real-disc checks
use your own disc image; none is included here.
