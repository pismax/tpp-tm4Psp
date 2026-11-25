"use strict";

const assert = require("node:assert/strict");
const {test} = require("node:test");
const {Worker} = require("node:worker_threads");
const parser = require("../tm4Psp.module.js");
const fs = require("node:fs/promises"), path = require("node:path"), os = require("node:os"), {spawnSync} = require("node:child_process");
const guidance=require('../tm4Psp.guidance.js');

test('pre-CRC projects gain disabled optional checking without needing an ISO rescan or recreating their data',()=>{
    const rows=[['原文','Existing translation']],parameters=[[{speakerId:22,contextStr:'string/7'}]];
    const project={gameEngine:'tm4Psp',options:{init:{entryPoint:'moved-original.iso',sourceManifest:{isoSha256:'a'.repeat(64)}}},
        files:{scene:{tm4Resource:{kind:'ASB'},data:rows,parameters}}};
    guidance.applyProjectDefaults(project);
    assert.deepEqual(project.options.init.sourceChecksum,{enabled:false,algorithm:'crc32',expected:''});
    assert.equal(project.files.scene.data,rows);assert.equal(project.files.scene.parameters,parameters);
    assert.equal(project.options.init.entryPoint,'moved-original.iso');
    assert.equal(project.options.init.sourceManifest.isoCrc32,undefined);
    assert.equal(guidance.applyProjectDefaults(project),false);
});

test('game guidance supplies editable cast translations and personalities without replacing existing project edits',()=>{
    const project={gameEngine:'tm4Psp',options:{init:{sourceManifest:{isoCrc32:'1234ABCD'}}},files:{scene:{tm4Resource:{kind:'ASB'},data:[['原文','Draft']]}}};
    assert.equal(guidance.applyProjectDefaults(project),true);
    const reference=project.files['Actor Reference'];
    assert.equal(reference.data.length,15);assert.equal(reference.actorInfoColumn,2);
    assert.equal(reference.data.find(row=>row[0]==='龍光寺カイ')[1],'Kai Ryukoji');
    assert.match(reference.data.find(row=>row[0]==='MC')[2],/^male/);
    assert.equal(project.options.translationConstraints.types.scenario.maxLines,3);
    assert.equal(project.options.init.sourceChecksum.expected,'1234ABCD');
    assert.equal(project.files.scene.translationConstraintType,'scenario');
    reference.data[0][1]='The Player';reference.data[0][2]='My own voice guidance';
    project.options.translationConstraints.types.scenario.maxCharsPerLine=40;
    assert.equal(guidance.applyProjectDefaults(project),true,'The export layout follows the edited width cap');
    assert.equal(guidance.applyProjectDefaults(project),false);
    assert.equal(reference.data[0][1],'The Player');assert.equal(reference.data[0][2],'My own voice guidance');
    assert.equal(project.options.translationConstraints.types.scenario.maxCharsPerLine,40);
    assert.equal(project.files.scene.data[0][1],'Draft');
    const unknownLayout={gameEngine:'tm4Psp',options:{init:{}},files:{'Actor Reference':{data:[['MC','Draft','Preferred']]}}};
    guidance.applyProjectDefaults(unknownLayout);
    assert.equal(unknownLayout.files['Actor Reference'].actorInfoColumn,3);
    assert.equal(unknownLayout.files['Actor Reference'].data[0][2],'Preferred');
    const C=require('../../../js/TranslationConstraints.js');
    const rules=C.forRows(project,[{path:'scene',row:0}]);
    assert.deepEqual(C.validate(rules,['Hi']),[]);
    project.files.scene.data[0][0]='名前\\h00';
    assert.ok(C.validate(C.forRows(project,[{path:'scene',row:0}]),['Name\\h01']).some(error=>error.type==='controls'));
});

test('old ASB display references gain message types without changing row contexts or relaxing mixed uses',()=>{
    const parameters=[[{canGrow:true,contextStr:'string/7'}],[{canGrow:false,contextStr:'string/20'}],[{canGrow:true},{canGrow:false}]];
    const project={gameEngine:'tm4Psp',options:{init:{}},files:{scene:{tm4Resource:{kind:'ASB'},data:[['一\n二\n三',''],['名前',''],['重複\n行','']],parameters}}};
    guidance.applyProjectDefaults(project);
    assert.equal(parameters[0][0].messageType,'messageBox');assert.equal(parameters[0][0].translationConstraintType,'messageBox');assert.equal(parameters[0][0].contextStr,'string/7');
    assert.equal(parameters[1][0].messageType,'unknown');
    const C=require('../../../js/TranslationConstraints.js'),rules=C.forRows(project,[0,1,2].map(row=>({path:'scene',row})));
    assert.equal(rules[0].preserveLineCount,false);assert.equal(rules[0].maxLines,3);assert.equal(rules[0].maxCharsPerLine,44);
    assert.equal(rules[1].preserveLineCount,true);assert.equal(rules[2].preserveLineCount,true);
    project.options.translationConstraints.types.messageBox.preserveLineCount=true;guidance.applyProjectDefaults(project);
    assert.equal(project.options.init.messageBoxLayout.preserveLineCount,true);assert.equal(C.forRows(project,[{path:'scene',row:0}])[0].preserveLineCount,true);
});

test('ISO export enforces optional CRC in the portable writer and permits an explicit one-call bypass',async()=>{
    const root=await fs.mkdtemp(path.join(os.tmpdir(),'tpp-tm4-crc-')),iso=path.join(root,'source.iso'),target=path.join(root,'translated.iso');
    try {
        await fs.writeFile(iso,'123456789');
        const init={sourceChecksum:{enabled:true,algorithm:'crc32',expected:'00000000'}};
        await assert.rejects(parser.exportIso(iso,target,{init}),/CRC32 mismatch/);
        await assert.rejects(parser.exportIso(iso,target,{init,skipSourceCrc:true,manifest:{},stage:root}),error=>!/CRC32 mismatch/.test(error.message));
        await assert.rejects(parser.exportIso(iso,target,{init}),/CRC32 mismatch/);
        assert.equal(init.sourceChecksum.enabled,true);
        assert.equal(await fs.stat(target).then(()=>true,()=>false),false);
    } finally {await fs.unlink(iso);await fs.rmdir(root);}
});

test("business API imports in Node without Translator++ globals", () => {
    for (const name of ["tm4PspProject", "parseFile", "writeFile", "detecttm4Psp"]) {
        assert.equal(typeof parser[name], "function");
    }
});

test("detector rejects a non-game path", async () => {
    assert.equal(await parser.detecttm4Psp("nonexistent-game-path"), false);
});

test("worker imports the business module and responds to ping", {timeout: 5000}, async () => {
    const worker = new Worker(require.resolve("../tm4Psp.worker.js"), {workerData: {command: "ping"}});
    try {
        const message = await new Promise((resolve, reject) => {
            worker.once("message", resolve);
            worker.once("error", reject);
            worker.once("exit", code => reject(new Error("Worker exited before responding: " + code)));
        });
        assert.deepEqual(message, {result: "ok", errors: []});
    } finally {
        await worker.terminate();
    }
});

test("context pairs keep distinct translations and an explicit untranslated occurrence", () => {
    const selected = {translationPair: {"Hi": "Fallback", "string/7\nHi": "Alice", "string/8\nHi": ""}};
    assert.equal(parser.resolveTranslation({context:"string/7",text:"Hi"}, selected), "Alice");
    assert.equal(parser.resolveTranslation({context:"string/8",text:"Hi"}, selected), undefined);
    assert.equal(parser.resolveTranslation({context:"string/9",text:"Hi"}, selected), "Fallback");
});
test("repeated source rows merge all contexts and speaker metadata before host sanitization", async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-test-"));
    const source = path.join(root, "fixture.tm4.json");
    try {
        await fs.writeFile(source, JSON.stringify({version:1,kind:"ASB",sha256:"fixture",destinations:["tokimeki/1.asb"],rows:[
            {text:"こんにちは",context:"string/7",rowInfoText:"Alice"}, {text:"こんにちは",context:"string/9",rowInfoText:"Bob"}]}));
        const parsed = await parser.parseFile(source);
        assert.equal(parsed.data.length, 1);
        assert.deepEqual(parsed.context, [["string/7","string/9"]]);
        assert.equal(parsed.parameters[0][1].rowInfoText, "Bob");
        await assert.rejects(parser.writeFile(source, source), /overwrite/);
        assert.throws(() => parser.resourcePath(root,"../escape"), /Invalid/);
    } finally { await fs.unlink(source); await fs.rmdir(root); }
});
test("binary codecs: synthetic TSID, ASB, CSV and GIM fixtures", {timeout:30000}, () => {
    const result = spawnSync(process.env.TM4_PYTHON || "python", ["-B", path.join(__dirname,"test_formats.py")], {encoding:"utf8",windowsHide:true});
    assert.equal(result.status, 0, result.stderr || result.error?.message);
});

test("archive edits retain loader-sensitive FSTS and outer PIDX layouts", {timeout:30000}, () => {
    const result=spawnSync(process.env.TM4_PYTHON || "python",["-B",path.join(__dirname,"test_archives.py")],{encoding:"utf8",windowsHide:true});
    assert.equal(result.status,0,result.stdout+result.stderr);
});

test("old staged descriptors gain MC role per occurrence without confusing name-control IDs", async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-mc-test-"));
    const source = path.join(root, "fixture.tm4.json");
    try {
        await fs.writeFile(source, JSON.stringify({version:1,kind:"ASB",sha256:"fixture",destinations:["fixture.asb"],rows:[
            {text:"こんにちは",context:"string/7",speakerId:22},
            {text:"こんにちは",context:"string/9",speakerId:12,rowInfoText:"小林学"},
            {text:"こんにちは",context:"string/11",speakerId:45},
            {text:"名前",context:"string/15",speakerId:26}]}));
        const parsed = await parser.parseFile(source);
        assert.deepEqual(parsed.context[0], ["string/7","string/9","string/11"]);
        assert.deepEqual(parsed.parameters[0].map(p=>p.rowInfoText), ["MC","小林学","MC"]);
        assert.equal(parsed.parameters[0][0].speakerGender,"male");
        assert.equal(parsed.parameters[1][0].rowInfoText,undefined);
    } finally {await fs.unlink(source);await fs.rmdir(root);}
});

test("existing projects upgrade speaker metadata idempotently and preserve edited labels and all translations", () => {
    const file = {tm4Resource:{kind:"ASB"},data:[["Original","Draft","Preferred"]],context:[["string/7","string/9"]],
        parameters:[[{speakerId:22,contextStr:"string/7"},{speakerId:45,rowInfoText:"Player",contextStr:"string/9"}]]};
    const image = {tm4Image:{},parameters:[[{speakerId:22}]]};
    const project = {gameEngine:"tm4Psp",files:{file,image}};
    const data=JSON.stringify(file.data), contexts=JSON.stringify(file.context);
    assert.equal(parser.upgradeSpeakerMetadata({...project,gameEngine:"other"}),0);
    assert.equal(parser.upgradeSpeakerMetadata(project),2);
    assert.equal(file.parameters[0][0].rowInfoText,"MC");
    assert.equal(file.parameters[0][1].rowInfoText,"Player");
    assert.equal(file.parameters[0][1].speakerGender,"male");
    assert.equal(JSON.stringify(file.data),data);
    assert.equal(JSON.stringify(file.context),contexts);
    assert.equal(image.parameters[0][0].rowInfoText,undefined);
    assert.equal(parser.upgradeSpeakerMetadata(project),0);
});
test("half-width executable guards and MIPS ASCII/Japanese scenario rendering", {timeout:30000}, () => {
    const result = spawnSync(process.env.TM4_PYTHON || "python", ["-B", path.join(__dirname,"test_font.py")], {encoding:"utf8",windowsHide:true});
    assert.equal(result.status, 0, result.stderr || result.error?.message);
});

test("relocated ISO uses the explicitly selected source folder or file, even when the old path still exists", async () => {
    const crypto = require("node:crypto"), root = await fs.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-source-test-"));
    const bytes = Buffer.from("synthetic-original-disc"), expected = crypto.createHash("sha256").update(bytes).digest("hex");
    const old = path.join(root,"game.iso"), moved = path.join(root,"relocated"), iso = path.join(moved,"renamed.ISO");
    try {
        await fs.mkdir(moved); await fs.writeFile(old,bytes); await fs.writeFile(iso,bytes);
        const manifest = {iso:old,isoSha256:expected,isoSize:bytes.length};
        assert.equal(await parser.resolveSourceIso(old,{manifest,sourceMaterial:moved}),iso);
        assert.equal(await parser.resolveSourceIso(old,{manifest,sourceMaterial:iso}),iso);
        await fs.writeFile(path.join(moved,"wrong.iso"),Buffer.alloc(bytes.length,7));
        await assert.rejects(parser.resolveSourceIso(old,{manifest,sourceMaterial:path.join(moved,"wrong.iso")}),/does not match/);
        await assert.rejects(parser.resolveSourceIso(old,{manifest,sourceMaterial:path.join(root,"missing")}),/could not be found/);
        await fs.unlink(old);
        assert.equal(await parser.resolveSourceIso(old,{manifest,sourceMaterial:moved}),iso);
    } finally {
        for (const filename of [old,iso,path.join(moved,"wrong.iso")]) await fs.unlink(filename).catch(()=>{});
        await fs.rmdir(moved);await fs.rmdir(root);
    }
});

test("export finds a disc moved into a same-name subfolder and checks its fingerprint", async () => {
    const crypto = require("node:crypto"), root = await fs.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-nearby-test-"));
    const bytes = Buffer.from("synthetic-disc"), old=path.join(root,"game.iso"), moved=path.join(root,"game"), iso=path.join(moved,"game.iso");
    const manifest={iso:old,isoSize:bytes.length,isoSha256:crypto.createHash("sha256").update(bytes).digest("hex")};
    try {
        await fs.mkdir(moved);await fs.writeFile(iso,bytes);
        assert.equal(await parser.resolveSourceIso(old,{manifest}),iso);
        await fs.writeFile(iso,Buffer.alloc(bytes.length,0));
        await assert.rejects(parser.resolveSourceIso(old,{manifest}),/does not match/);
        await fs.unlink(iso);
        await assert.rejects(parser.resolveSourceIso(old,{manifest}),/In Inject, select the folder/);
    } finally {await fs.unlink(iso).catch(()=>{});await fs.rmdir(moved);await fs.rmdir(root);}
});
