# Working on tm4Psp

The parser is implemented. Use the
[TM4 case map](../../docs/console-rom-parser/cases/tm4-psp.md) to select relevant
README/plan sections before changing formats or integration. Preserve the
validated extraction/export behaviour; do not load unrelated case notes.

Read the relevant CONTROL_CODES.md sections before changing control-code handling. Name/context
selectors use decimal digits and several codes have path-dependent meanings.
Fixed budgets count encoded stored tokens before game-side expansion.

1. Record the actual format signature, versions, encoding, extraction rules,
   and known limitations in plan/README.md using real fixtures.
2. Maintain scan(), parseFile(), and writeFile() in tm4Psp.module.js.
   Keep the business logic callable from plain Node.js and worker_threads.
3. Use tm4Psp.js only for Translator++ UI and AddonUtils integration.
   Top-level `this` there is the Addon instance. Never require that entry as
   a Node module. Persist options needed after reopening in project.options.init.
4. Adapt the JSONForm schema/form and the commented AddonUtils hooks as needed.
   Implement a reliable detector after the New Project flow works.
5. Keep format fixtures and tests: extraction/context/speaker metadata, unchanged
   export round trip, translated output, duplicate strings in different contexts,
   multiline/control-code preservation, malformed input, and missing translations.
6. Run `node --test www/addons/tm4Psp/test/tm4Psp.module.test.js`
   and `node --test www/addons/tm4Psp/test/tm4Psp.integration.test.js`
   from the Translator++ root. Also exercise New Project, reopen, folder/zip export,
   inject, and update in Translator++. Verify module loading after compilation.

Do not modify original game resources during extraction or export. Preserve
encoding/BOM, newline style, syntax, binary offsets/lengths, and non-text data.
Use the same file IDs and contexts for extraction and writing. Use the resolved
translationPair supplied by AddonUtils instead of guessing a target column.

Read these repository references before inventing an API:

- `www/js/ParserBase.js`: registerString/register, context, filters, getText/toTrans.
  It currently needs host globals `common` and `empty`; requiring it alone is
  insufficient in standalone Node/worker runtimes. See the module's recipe.
- `www/js/AddonUtils.js`: createProject, per-file hooks, export/inject/update.
- `www/js/jsonform.ext.js`, `www/js/CustomFields.js`: supported form controls.
- `www/js/addon.js`: loader and Addon paths; entry script execution model.
- `www/addons/unrealParser/unreal.js`, `unreal.module.js`, `package.json`: example
  of UI integration, archive staging, portable business logic, and compilation.
- `www/docs/parser-developer-guide-ai.md`, `parser-base-developer-guide-ai.md`,
  `addon-developer-guide-ai.md`, `trans.md`: detailed contracts (all under www/docs).

Tests include synthetic format fixtures and a Node/worker adapter suite. Keep
the live import/reopen/export/update checks in plan/README.md accurate. Source
strings must merge all contexts before host sanitization; repeated OCR boxes
must keep their individual positions and styles through save/reopen.

For font changes and live emulator tests, read
[plan/half-width-and-ppsspp.md](plan/half-width-and-ppsspp.md). Reusable setup,
navigation and debugger probes are in `tools/test-tm4-font.ps1` and
`tools/tm4-ppsspp.py` at the Translator++ root; do not depend on ignored lab files.
Use an isolated emulator copy and a fresh ISO boot for final verification.
Run `python -B tools/test_tm4_ppsspp.py` after changing the automation helper.

## Repository and releases

This folder is its own git repository,
[pismax/tpp-tm4Psp](https://github.com/pismax/tpp-tm4Psp), cloned at
`<Translator++>/www/addons/tm4Psp` so the app loads it and the tests can require
`www/js/...`. Commit here as `pismax <360907843+pismax@users.noreply.github.com>`
(set in this clone's git config). Never commit these files to the Translator++
repository, and never add other identities, emails or local paths.

To release:

1. Bump `version` in `package.json` (and the top-level and root-package
   versions in `package-lock.json` when present). Raise `minimumVersion` when
   the code needs a newer Translator++.
2. Describe the user-facing change under a new version heading in
   `CHANGELOG.md`.
3. Run the tests above, commit, then `git tag v<version>` and
   `git push origin main v<version>`. Never move a published tag.
4. In the catalog repository [pismax/tpp-addons](https://github.com/pismax/tpp-addons),
   set this add-on's `ref` to the new tag, update its README table, run
   `node scripts/validate-catalog.js`, and push. Translator++ offers the update
   within a few minutes.
