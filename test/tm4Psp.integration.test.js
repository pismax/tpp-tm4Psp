"use strict";
const {test} = require("node:test"), assert = require("node:assert/strict"), vm = require("node:vm");
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const parser = require("../tm4Psp.module.js");
const hostRequire=specifier=>require(specifier.startsWith('www/')?path.resolve(specifier):specifier);
const hostSys=()=>({config:{},saveConfig(){}});

test("loaded and reopened TM4 projects upgrade MC row info without a disc rescan", async () => {
    const listeners = {}, draft = [["Original","Saved translation"]];
    const makeProject = () => ({gameEngine:"tm4Psp",files:{scene:{tm4Resource:{kind:"ASB"},data:draft,
        parameters:[[{speakerId:22}],[{speakerId:45}],[{speakerId:37}]]}}});
    let changed=0,refreshed=0;
    const trans={project:makeProject(),sanitize:()=>{},on:(name,fn)=>{listeners[name]=fn;},
        gridIsModified:()=>{changed++;},refreshGrid:()=>{refreshed++;}};
    const addon={getPathRelativeToRoot:()=>path.dirname(require.resolve("../tm4Psp.module.js")),updateProject:async()=>{}};
    const context={trans,sys:hostSys(),require:specifier=>specifier==="www/js/AddonUtils.js"?function(){}:hostRequire(specifier)};
    const source=fs.readFileSync(path.join(__dirname,"../tm4Psp.js"),"utf8").split("thisAddon.registerProjectWizard =")[0];
    await vm.runInNewContext("(async function(){\n"+source+"\n})",context).call(addon);
    assert.equal(trans.project.files.scene.parameters[0][0].rowInfoText,"MC");
    assert.equal(trans.project.files.scene.parameters[1][0].rowInfoText,"MC");
    assert.equal(trans.project.files.scene.parameters[2][0].rowInfoText,undefined);
    assert.equal(trans.project.files.scene.data,draft);
    assert.equal(trans.project.files['Actor Reference'].data.length,15);
    assert.match(trans.project.options.translationPrompts.game,/male player protagonist/);
    assert.equal(addon.upgradeSpeakerMetadata(),0);
    trans.project=makeProject();listeners["onLoadTrans.tm4SpeakerRoles"]();
    assert.equal(trans.project.files.scene.parameters[0][0].rowInfoText,"MC");
    assert.equal(changed,2);assert.equal(refreshed,2);
});

test("Inject forwards its selected ISO source while keeping staged resources, and remembers a verified relocation", async () => {
    const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-inject-test-"));
    try {
        const previous = path.join(root,"old","game.iso"), selected = path.join(root,"new"), relocated = path.join(selected,"game.iso");
        const manifest = {iso:previous,isoSha256:"a".repeat(64),files:[],images:[]};
        const halfWidthFont = {enabled:true,file:"font/tm4-decrypted-eboot.bin",profile:"fixture"};
        const project = {projectId:"fixture",loc:path.dirname(previous),options:{init:{entryPoint:previous,sourceManifest:manifest,halfWidthFont}},files:{dialogue:{data:[["Source","Existing translation"]]}}};
        const calls = [], addon = {getPathRelativeToRoot:()=>path.dirname(require.resolve("../tm4Psp.module.js")),updateProject:async()=>{}};
        let modified = false;
        const trans = {project,sanitize:()=>{},getSaveData:()=>JSON.parse(JSON.stringify({project})),getTranslationData:()=>({translationData:{}}),
            getAllFiles:()=>[],getStagingPath:()=>path.join(root,"cache"),getStagingDataPath:()=>path.join(root,"cache","data"),gridIsModified:value=>{modified=value;}};
        const mockParser = {...parser,resolveSourceIso:async (source,options)=>{calls.push({source,options});return relocated;},
            exportIso:async (source,target,options)=>{calls.push({source,target,options});return {path:target,changedMembers:0};}};
        const source = fs.readFileSync(path.join(__dirname,"../tm4Psp.js"),"utf8").split("thisAddon.registerProjectWizard =")[0];
        const context = {trans,sys:hostSys(),ui:{log:()=>{}},require:specifier=>specifier==="www/js/AddonUtils.js"?function(){}:specifier.endsWith("tm4Psp.module.js")?mockParser:hostRequire(specifier)};
        await vm.runInNewContext("(async function(){\n"+source+"\n})",context).call(addon);
        const options = {resourcePath:path.join(root,"cache","data")};
        await addon.injectCopyMaterials(selected,root,options);
        assert.equal(options.tm4SourceMaterial,selected);
        await addon.exportToFolder(root,undefined,options);
        assert.equal(calls[0].options.sourceMaterial,selected);
        assert.equal(calls[1].source,relocated);
        assert.equal(calls[1].options.stage,options.resourcePath);
        assert.deepEqual(calls[1].options.init.halfWidthFont,halfWidthFont);
        assert.equal(project.options.init.entryPoint,relocated);
        assert.equal(project.options.init.sourceManifest.iso,relocated);
        assert.equal(project.loc,selected);
        assert.equal(project.files.dialogue.data[0][1],"Existing translation");
        assert.equal(options.imageTranslatorHandled,true);
        assert.equal(modified,true);
        const forceOptions={custom:{tm4SkipCrc:true}};
        await addon.exportToFolder(root,undefined,forceOptions);
        assert.equal(calls.at(-1).options.skipSourceCrc,true);
        await addon.exportToFolder(root,undefined,{});
        assert.equal(calls.at(-1).options.skipSourceCrc,false);
        project.options.init.entryPoint=project.options.init.sourceManifest.iso=previous;
        mockParser.exportIso=async()=>{throw new Error("Validation failed");};
        await assert.rejects(addon.exportToFolder(root,undefined,options),/Validation failed/);
        assert.equal(project.options.init.entryPoint,relocated);
    } finally {await fs.promises.rmdir(root);}
});

test("font settings persist through creation, configuration and project update without changing translation rows", async () => {
    const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), "tpp-tm4-font-ui-"));
    try {
        const sourceFile = path.join(root,"selected.bin"), oldStage = path.join(root,"old"), newStage = path.join(root,"new");
        await fs.promises.mkdir(path.join(oldStage,"font"),{recursive:true});
        await fs.promises.writeFile(path.join(oldStage,"font","tm4-decrypted-eboot.bin"),"fixture");
        const rows = [["原文","Existing draft"]];
        const oldProject = {gameEngine:"tm4Psp",stage:oldStage,options:{init:{}},files:{text:{data:rows}}};
        let modified = false;
        const trans = {project:oldProject,sanitize:()=>{},getStagingDataPath:data=>(data?.project||trans.project).stage,
            getStagingPath:data=>path.dirname((data?.project||trans.project).stage),getSaveData:()=>{
                const data=JSON.parse(JSON.stringify({project:trans.project}));
                if(data.project.files['Actor Reference']) {
                    data.project.references ||= {};data.project.references['Actor Reference']=data.project.files['Actor Reference'];
                    delete data.project.files['Actor Reference'];
                }
                return data;
            },
            gridIsModified:value=>{modified=value;},syncFileNavigator:()=>{},refreshGrid:()=>{}};
        const calls = [], settings = {enabled:true,file:"font/tm4-decrypted-eboot.bin",profile:"fixture"};
        const mockParser = {...parser,bridge:async(command,request)=>{
            assert.equal(command,"font");assert.equal(request.source,path.join(oldStage,settings.file));
            return {profile:"fixture"};
        },stageHalfWidthFont:async(source,stage)=>{
            calls.push({source,stage});if(source==="bad")throw new Error("Unsupported executable");return {...settings};
        }};
        const addon = {getPathRelativeToRoot:()=>path.dirname(require.resolve("../tm4Psp.module.js")),updateProject:async()=>{
            trans.project={...oldProject,stage:newStage,options:{init:{}}};return "updated";
        }};
        const context = {trans,sys:hostSys(),ui:{log:()=>{}},require:specifier=>specifier==="www/js/AddonUtils.js"?function(){}:specifier.endsWith("tm4Psp.module.js")?mockParser:hostRequire(specifier)};
        const source = fs.readFileSync(path.join(__dirname,"../tm4Psp.js"),"utf8").split("thisAddon.registerProjectWizard =")[0];
        await vm.runInNewContext("(async function(){\n"+source+"\n})",context).call(addon);
        await addon.configureHalfWidthFont(sourceFile);
        assert.deepEqual(trans.project.options.init.halfWidthFont,{...settings,weight:"regular"});
        await assert.rejects(addon.configureHalfWidthFont("bad"),/Unsupported/);
        assert.deepEqual(trans.project.options.init.halfWidthFont,{...settings,weight:"regular"});
        await addon.configureHalfWidthFont("", "bold");
        assert.equal(trans.project.options.init.halfWidthFont.weight,"bold");
        await assert.rejects(addon.configureHalfWidthFont("", "heavy"),/supported font weight/);
        assert.equal(trans.project.files.text.data,rows);
        assert.equal(modified,true);
        trans.project.options.init.halfWidthFont.enabled=false;
        trans.project.options.translationPrompts.game='Custom school localization';
        trans.project.options.translationConstraints.types.scenario.maxCharsPerLine=37;
        trans.project.options.init.sourceChecksum={enabled:false,algorithm:'crc32',expected:'12345678'};
        trans.project.files['Actor Reference'].data[0][1]='Player';
        assert.equal(await addon.updateProject(),"updated");
        assert.equal(trans.project.options.translationPrompts.game,'Custom school localization');
        assert.equal(trans.project.options.translationConstraints.types.scenario.maxCharsPerLine,37);
        assert.equal(trans.project.options.init.sourceChecksum.expected,'12345678');
        assert.equal(trans.project.files['Actor Reference'].data[0][1],'Player');
        assert.equal(trans.project.options.init.halfWidthFont.enabled,false);
        assert.equal(trans.project.options.init.halfWidthFont.weight,"bold");
        assert.deepEqual(calls.at(-1),{source:path.join(oldStage,settings.file),stage:newStage});
        assert.equal(trans.project.files.text.data,rows);
        const data={project:{gameEngine:"tm4Psp",stage:newStage,options:{init:{halfWidthEboot:sourceFile}},files:{}}};
        await addon.finalizeTransData(data,root,{init:{halfWidthEboot:sourceFile,sourceManifest:{images:[]}}});
        assert.deepEqual(data.project.options.init.halfWidthFont,settings);
        assert.equal(data.project.options.init.halfWidthEboot,undefined);
        assert.deepEqual(calls.at(-1),{source:sourceFile,stage:newStage});
        assert.equal(data.project.files['Actor Reference'].data.length,15);
        await addon.configureTranslationSettings({enabled:true,scenarioCharsPerLine:42,scenarioMaxLines:3,checkSourceCrc:true,expectedCrc32:'0x1234abcd'});
        assert.equal(trans.project.options.init.sourceChecksum.expected,'1234ABCD');
        assert.equal(trans.project.options.translationConstraints.types.scenario.maxCharsPerLine,42);
        await assert.rejects(addon.configureTranslationSettings({enabled:true,scenarioCharsPerLine:-1}),/positive/);
    } finally {await fs.promises.rm(root,{recursive:true,force:true});}
});
