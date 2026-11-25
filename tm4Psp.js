// Addon.loadJS AsyncFunction: top-level `this` is the Addon instance.
const thisAddon = this;
const nwPath = require("path"), fs = require("fs");
const AddonUtils = require("www/js/AddonUtils.js");
const parser = require(nwPath.join(thisAddon.getPathRelativeToRoot(), "tm4Psp.module.js"));
const guidance = require(nwPath.join(thisAddon.getPathRelativeToRoot(), "tm4Psp.guidance.js"));
const TranslationPrompts = require("www/js/TranslationPrompts.js");
const SourceChecksum = require("www/js/SourceChecksum.js");
const parserTitle = "Tokimeki Memorial 4 (PSP)";
thisAddon.gameEngine = "tm4Psp";
thisAddon.originalResourceIsReadOnly = true;
thisAddon.alwaysExportFromStage = true;
const supportedEngines = [thisAddon.gameEngine];
AddonUtils(thisAddon);

// Older projects already retain numeric speaker IDs. Upgrade their row info
// without rescanning the disc or touching translations and occurrence contexts.
thisAddon.upgradeSpeakerMetadata = function() {
    const changed = parser.upgradeSpeakerMetadata(trans.project);
    const defaultsChanged=thisAddon.applyTranslationGuidance(trans.project);
    if (changed || defaultsChanged) { trans.gridIsModified(true); trans.refreshGrid(); }
    return changed;
};
thisAddon.applyTranslationGuidance = function(project) {
    if(project?.gameEngine!=="tm4Psp")return false;
    const changed=guidance.applyProjectDefaults(project);
    const promptsChanged=TranslationPrompts.applyParserDefaults({trans,sys},project,{game:guidance.profile.gamePrompt,engine:guidance.profile.enginePrompt,source:guidance.profile.source});
    return changed || promptsChanged;
};
trans.on?.("onLoadTrans.tm4SpeakerRoles", () => thisAddon.upgradeSpeakerMetadata());
thisAddon.upgradeSpeakerMetadata();

// Each OCR box has its own position/style, even when its lettering repeats.
// The host's source-text deduplication must not discard those image boxes.
if (!trans.tm4ImageSanitizerInstalled) {
    const sanitize = trans.sanitize;
    trans.sanitize = function(data) {
        const target = data || this, preserved = new Map();
        for (const [id, file] of Object.entries(target.project?.files || {})) if (file.tm4Image) {
            preserved.set(id, {data: file.data, context: file.context, parameters: file.parameters, tags: file.tags});
        }
        const result = sanitize.call(this, data);
        for (const [id, fields] of preserved) if (target.project.files[id]?.tm4Image) Object.assign(target.project.files[id], fields);
        return result;
    };
    trans.tm4ImageSanitizerInstalled = true;
}

function imageTranslator() {
    const it = addonLoader.getAddonByName("imageTranslator");
    if (!it?.buildImageFileEntry) throw new Error("Enable Image Translator to import editable game images.");
    // Empty image translations must retain the original lettering.
    if (!it.tm4RendererHook) {
        const render = it.renderToCanvas;
        it.renderToCanvas = function(canvas, file, options) {
            if (!file?.tm4Image) return render.call(this, canvas, file, options);
            const parameters = (file.parameters || []).map((p, row) => it.getBestTranslation(file.data?.[row]) ? p : []);
            return render.call(this, canvas, {...file, parameters}, options);
        };
        it.tm4RendererHook = true;
    }
    if (it.createKritaLayer && !it.tm4KritaHook) {
        const create = it.createKritaLayer;
        it.createKritaLayer = async function(id, options) {
            const result = await create.call(this, id, options), file = trans.project?.files[id];
            if (file?.tm4Image) file.layerVisibility = {...file.layerVisibility, original: false, krita: true};
            return result;
        };
        it.tm4KritaHook = true;
    }
    return it;
}
thisAddon.prepareNewProject = async function(info = {}) {
    if (!info.entryPoint) throw new Error("Choose the Japanese PSP ISO first.");
    if(info.expectedCrc32)SourceChecksum.normalize(info.expectedCrc32);
    ui.showLoading();
    let project;
    try {
        if (info.halfWidthEboot) await parser.bridge("font", {source: info.halfWidthEboot}, {init: info});
        ui.log("Extracting Tokimeki Memorial 4 text and interface images from the disc.");
        const entryPoint = info.sourceManifest ? await parser.resolveSourceIso(info.entryPoint, {manifest: info.sourceManifest}) : nwPath.resolve(info.entryPoint);
        project = await parser.tm4PspProject.scan(entryPoint, {init: info});
        if (project.manifest.imageErrors.length) ui.log.error("Skipped " + project.manifest.imageErrors.length + " unsupported images. " + project.manifest.imageErrors[0].error);
        return await thisAddon.openScannedProject(project, info);
    } finally {
        if (project?.sourceDir) {
            const root = nwPath.resolve(project.sourceDir), temp = nwPath.resolve(require("os").tmpdir());
            if (nwPath.dirname(root) === temp && nwPath.basename(root).startsWith("tpp-tm4-source-")) await fs.promises.rm(root, {recursive: true, force: true});
        }
        ui.loadingEnd();
    }
};
// Also useful for CLI/worker imports: open an already-scanned, verified source.
thisAddon.openScannedProject = async function(project, info = {}) {
        const init = {...info, entryPoint: project.manifest.iso, sourceManifest: project.manifest,
            includeImages: info.includeImages !== false, projectTitle: info.projectTitle || parserTitle};
        // Cache only portable descriptors and PNGs, not disc archives. The
        // source ISO is checked again whenever a separate patched ISO is built.
        const assets = project.manifest.images.flatMap(im => [im.file, im.file + ".tm4.json"]);
        return await thisAddon.createProject(project.files, project.sourceDir, {init, tm4SourceDir: project.sourceDir, tm4Assets: assets});
};
thisAddon.getTransData = (file, basePath) => parser.parseFile(parser.resourcePath(basePath, file));
thisAddon.writeFile = async function(file, basePath, targetDir, options = {}) {
    const selected = thisAddon.selectTranslationData(options.translationDatas, file);
    return parser.writeFile(parser.resourcePath(basePath, file), parser.resourcePath(targetDir, file), {...selected, init: options.projectInfo?.init});
};
thisAddon.setFileFormatName = file => file.includes("/ASB/") ? "TM4 PSP ASB dialogue (CP932)" : file.includes("/TSID/") ? "TM4 PSP TSID message table (CP932)" : "TM4 PSP CSV (CP932)";
thisAddon.setProjectLocation = (_data, _base, options) => nwPath.dirname(options.init.entryPoint);
thisAddon.finalizeTransData = async function(data, basePath, options) {
    thisAddon.applyTranslationGuidance(data.project);
    data.project.options.sl = "ja";
    data.project.options.tl = options.init.targetLanguage || "en";
    data.project.options.gridInfo = {...data.project.options.gridInfo, rowHeaderWidth: 220, isRuleActive: true, rowHeaderInfo: true};
    const stage = trans.getStagingDataPath(data), cache = trans.getStagingPath(data);
    if (options.init.halfWidthEboot) {
        data.project.options.init.halfWidthFont = await parser.stageHalfWidthFont(options.init.halfWidthEboot, stage, {init: options.init});
    }
    delete data.project.options.init.halfWidthEboot;
    const sourceChecksum=data.project.options.init.sourceChecksum;
    if (options.init.checkSourceCrc!==undefined) sourceChecksum.enabled=options.init.checkSourceCrc===true;
    if (options.init.expectedCrc32) sourceChecksum.expected=SourceChecksum.normalize(options.init.expectedCrc32);
    for (const name of options.tm4Assets || []) {
        const target = parser.resourcePath(stage, name);
        await fs.promises.mkdir(nwPath.dirname(target), {recursive: true});
        await fs.promises.copyFile(parser.resourcePath(basePath, name), target);
    }
    if (options.init.sourceManifest.images.length) {
        const it = imageTranslator();
        for (const image of options.init.sourceManifest.images) {
            const relative = "images/tm4/" + nwPath.basename(image.file);
            const target = parser.resourcePath(cache, relative);
            await fs.promises.mkdir(nwPath.dirname(target), {recursive: true});
            await fs.promises.copyFile(parser.resourcePath(basePath, image.file), target);
            const file = it.buildImageFileEntry(relative, [], {width: image.width, height: image.height, stagingPath: relative,
                sourceExtension: ".png", originalFormat: "TM4 PSP " + image.kind + " interface texture"});
            file.tm4Image = image;
            file.translationConstraintType = 'image';
            file.filename = nwPath.basename(image.label);
            file.note = image.label + ". Preserve dimensions and sprite placement. GIM edits use the original palette.";
            data.project.files[file.path] = file;
        }
        if (options.init.ocrImages !== false) await thisAddon.recognizeGameImages(data);
    }
    return data;
};

thisAddon.recognizeGameImages = async function(data = {project: trans.project}, options = {}) {
    if (data.project.gameEngine !== "tm4Psp") throw new Error("Open a Tokimeki Memorial 4 PSP project first.");
    const it = imageTranslator(), engine = OcrEngine.getMainEngine();
    if (!engine) throw new Error("Enable an OCR engine, or disable image text recognition in New Project.");
    const jobs = Object.entries(data.project.files).filter(([id, file]) => file.tm4Image && !file.data?.some(row => Boolean(row?.[0])) && (!options.files || options.files.includes(id)));
    const result = {processed: 0, withText: 0, blocks: 0, failures: []};
    await it.runOcrJobs(jobs, engine, {ocrWorkerCount: 2}, async ([id, file], index, recognize) => {
        ui.loadingProgress("Image text", (index + 1) + "/" + jobs.length + ": " + file.filename, {consoleOnly: true, mode: "consoleOutput"});
        try {
            const png = await fs.promises.readFile(parser.resourcePath(trans.getStagingPath(data), file.imageStagingPath));
            const blocks = await it.translateImageAsset(png, {engineId: engine.id, recognize});
            if (blocks.length) {
                const parsed = it.buildImageFileEntry(id, blocks, {width: file.imageWidth, height: file.imageHeight, engineId: engine.id});
                for (const key of ["data", "context", "parameters", "tags"]) file[key] = parsed[key];
                file.ocrEngineId = engine.id; result.withText++; result.blocks += blocks.length;
            }
        } catch (error) { result.failures.push({id, error: error.message}); }
        result.processed++;
    });
    data.project.options.init.imageOcrReport = result;
    ui.log("Recognized " + result.blocks + " text blocks in " + result.withText + " images.");
    if (result.failures.length) ui.log.error(result.failures.length + " images could not be recognized and remain manually editable. " + result.failures[0].error);
    return result;
};

function hasImageText(file) { return file.layerVisibility?.texts !== false && file.data?.some(row => row.slice(1).some(Boolean)); }
thisAddon.configureHalfWidthFont = async function(source, weight = "regular") {
    if (trans.project?.gameEngine !== "tm4Psp") throw new Error("Open a Tokimeki Memorial 4 PSP project first.");
    const project = trans.project;
    if (!["regular", "bold"].includes(weight)) throw new Error("Select a supported font weight.");
    let settings;
    if (source?.trim()) settings = await parser.stageHalfWidthFont(source, trans.getStagingDataPath(), {init: project.options.init});
    else {
        const previous = project.options.init.halfWidthFont;
        if (!previous?.file) throw new Error("Select a decrypted EBOOT.BIN dumped from your original game first.");
        const info = await parser.bridge("font", {source: parser.resourcePath(trans.getStagingDataPath(), previous.file)}, {init: project.options.init});
        settings = {...previous, ...info, enabled: true};
    }
    settings.weight = weight;
    if (trans.project !== project) throw new Error("The active project changed. Enable half-width text again in the intended project.");
    project.options.init.halfWidthFont = settings;
    trans.gridIsModified(true);
    return settings;
};
thisAddon.showHalfWidthFontDialog = function() {
    if (trans.project?.gameEngine !== "tm4Psp") return alert("Open a Tokimeki Memorial 4 PSP project first.");
    const enabled = Boolean(trans.project.options.init.halfWidthFont?.enabled);
    const fields = new CustomFields($("<form></form>"), {jsonForm: {
        schema: {source: {type: "string", title: "Decrypted EBOOT.BIN (leave blank to reuse the staged executable)"},
            weight: {type: "string", title: "Latin font weight", enum: ["regular", "bold"], default: trans.project.options.init.halfWidthFont?.weight || "regular"}},
        form: [{key: "source", type: "selectfile", accept: ".bin,.elf"}, {key: "weight", type: "select", titleMap: {regular: "Regular", bold: "Bold (thicker letters and digits)"}}]
    }});
    const dialog = $("<div></div>").append($("<p></p>").text("Half-width text is " + (enabled ? "enabled" : "disabled") + ". Enable 8×16 ASCII letters for scenario dialogue. Japanese stays full width. Export requires PPSSPP or PSP custom firmware."))
        .append($("<p></p>").text("In PPSSPP enable Settings → Tools → Developer tools → Dump decrypted EBOOT.BIN on game boot, then boot your original game. Select PSP/SYSTEM/DUMP/<game-id>_EBOOT.BIN from its memory stick folder. The verified executable is stored with this project."))
        .append($("<p></p>").text("Bold thickens Latin letters and digits without changing spacing or text budgets. Full-width Latin shares these glyphs and is also thickened. Japanese letters and punctuation keep their existing shapes."))
        .append(fields.getElm()).appendTo(document.body);
    dialog.dialog({title: "TM4 half-width alphabet", width: 650, modal: true,
        close: function() { $(this).dialog("destroy").remove(); }, buttons: [
            {text: "Enable", click: async function() {
                try { const values=fields.getValues(); await thisAddon.configureHalfWidthFont(values.source, values.weight); dialog.dialog("close"); ui.toast("Half-width alphabet enabled for future TM4 exports. Save the project to keep this setting."); }
                catch (error) { alert(error.message); }
            }},
            {text: "Disable", click: function() {
                if (trans.project.options.init.halfWidthFont) trans.project.options.init.halfWidthFont.enabled = false;
                trans.gridIsModified(true); dialog.dialog("close");
            }},
            {text: "Cancel", click: function() { dialog.dialog("close"); }}
        ]});
};
function hasImageEdits(file) {
    return file.layerVisibility?.original === false || hasImageText(file) ||
        ["inpaint", "krita", "aiInpaint", "burnIn"].some(name => file[name + "Layer"]?.imageStagingPath && file.layerVisibility?.[name] !== false);
}
thisAddon.exportToFolder = async function(directory, data, options = {}) {
    data ||= trans.getSaveData();
    const init = data.project.options.init;
    if (init.halfWidthFont?.enabled) ui.log("Half-width alphabet enabled: ASCII uses 8×16 glyphs, " + (init.halfWidthFont.weight || "regular") + " weight; Japanese keeps its original width.");
    const sourceIso = await parser.resolveSourceIso(init.entryPoint, {manifest: init.sourceManifest,
        sourceMaterial: options.tm4SourceMaterial, searchDirs: [data.project.loc, directory]});
    // Remember a checksum-verified move even if a translation later needs
    // correction. getSaveData() returns a clone, so update the matching live
    // project too; never alter any translation cells here.
    const projects = new Set([data.project]);
    if (trans.project?.projectId === data.project.projectId &&
        trans.project.options.init?.sourceManifest?.isoSha256 === init.sourceManifest.isoSha256) projects.add(trans.project);
    for (const project of projects) {
        const settings = project.options.init;
        const changed = settings.entryPoint !== sourceIso || settings.sourceManifest.iso !== sourceIso;
        settings.entryPoint = settings.sourceManifest.iso = sourceIso;
        project.loc = nwPath.dirname(sourceIso);
        if (changed && project === trans.project) trans.gridIsModified(true);
    }
    const translationDatas = options.translationDatas || trans.getTranslationData(data, options);
    const files = options.files?.length ? options.files : trans.getAllFiles(data, true);
    const translations = {}, images = {};
    const cache = trans.getStagingPath(data), stage = trans.getStagingDataPath(data);
    for (const id of files) {
        const name = id.replace(/^[\\/]+/, "");
        if (init.sourceManifest.files.includes(name)) translations[name] = thisAddon.selectTranslationData(translationDatas, id);
    }
    const selected = options.files?.length ? new Set(options.files) : null;
    for (const [id, file] of Object.entries({...data.project.files, ...options.imageTranslatorFiles})) {
        if (selected && !selected.has(id)) continue;
        if (file?.tm4Image && hasImageEdits(file)) {
            const it = imageTranslator(), relative = "tm4-export/" + nwPath.basename(file.tm4Image.file);
            const target = parser.resourcePath(cache, relative);
            await fs.promises.mkdir(nwPath.dirname(target), {recursive: true});
            const layers = it.getImageLayerVisibility(file);
            const onlyKrita = !layers.original && layers.krita && !layers.inpaint && !layers.aiInpaint && !layers.burnIn && !hasImageText(file);
            const png = onlyKrita ? await fs.promises.readFile(it.getKritaLayerAbsPath(file)) : await it.renderImageToBuffer(file);
            await fs.promises.writeFile(target, png); images[file.tm4Image.file] = target;
        }
    }
    const stem = nwPath.basename(sourceIso, nwPath.extname(sourceIso)) + ".translated";
    let target = nwPath.join(directory, stem + ".iso"), version = 2;
    while (fs.existsSync(target)) target = nwPath.join(directory, stem + "-" + version++ + ".iso");
    ui.log("Validating text and images, rebuilding archives, and writing a separate PSP ISO.");
    const result = await parser.exportIso(sourceIso, target, {manifest: init.sourceManifest, stage, translations, images, init, skipSourceCrc:options.custom?.tm4SkipCrc===true,signal:options.signal});
    if(result.sourceChecksum?.skipped)ui.log("Optional source CRC32 check was explicitly skipped for this injection.");
    else if(result.sourceChecksum?.matched)ui.log("Source CRC32 verified: "+result.sourceChecksum.actual);
    options.imageTranslatorHandled = true;
    ui.log("Exported " + result.path + ". Changed archive members: " + result.changedMembers);
    return [result.path, result.path + ".report.json"];
};
thisAddon.injectCopyMaterials = async function(sourceMaterial, _targetDir, options = {}) {
    // The common Inject handler passes its selected source through this hook.
    // Staged text remains the resourcePath; the ISO is resolved separately.
    options.tm4SourceMaterial = sourceMaterial || undefined;
};
thisAddon.exportAsZip = async function(target, data, options = {}) {
    if (fs.existsSync(target)) throw new Error("Choose a new ZIP output filename.");
    const temp = await fs.promises.mkdtemp(nwPath.join(require("os").tmpdir(), "tpp-tm4-zip-"));
    try {
        const paths = await thisAddon.exportToFolder(temp, data, options);
        await new Promise((resolve, reject) => require("7zip-min").cmd(["a", "-tzip", target, ...paths], error => error ? reject(error) : resolve()));
        return target;
    } finally {
        for (const name of await fs.promises.readdir(temp)) await fs.promises.unlink(nwPath.join(temp, name));
        await fs.promises.rmdir(temp);
    }
};
thisAddon.handleExport = async function(target, options = {}) {
    ui.showLoading();
    try {
        if (options.mode === "zip") await thisAddon.exportAsZip(target, undefined, options);
        else await thisAddon.exportToFolder(target, undefined, options);
        await ui.log.showOpenDirButton(target);
    } finally { ui.loadingEnd(); }
};

// Updating creates a fresh cache. Carry editable layers and corrected OCR boxes
// across only when their original texture pixels still match.
const updateProject = thisAddon.updateProject;
thisAddon.updateProject = async function(...args) {
    const oldData = trans.getSaveData(), oldProject = trans.project, oldCache = trans.getStagingPath(oldData);
    const result = await updateProject.apply(thisAddon, args);
    if (trans.project === oldProject) return result;
    const newCache = trans.getStagingPath(), copied = new Set();
    for(const key of ["translationPrompts","translationConstraints"])if(oldData.project.options[key]!==undefined)trans.project.options[key]=JSON.parse(JSON.stringify(oldData.project.options[key]));
    if(oldData.project.options.init.sourceChecksum)trans.project.options.init.sourceChecksum=JSON.parse(JSON.stringify(oldData.project.options.init.sourceChecksum));
    const oldActors=oldData.project.files["Actor Reference"] || oldData.project.references?.["Actor Reference"];
    if(oldActors) {
        trans.project.files["Actor Reference"]=JSON.parse(JSON.stringify(oldActors));
        trans.project.references ||= {};trans.project.references["Actor Reference"]=trans.project.files["Actor Reference"];
    }
    thisAddon.applyTranslationGuidance(trans.project);
    const oldFont = oldData.project.options.init.halfWidthFont;
    if (oldFont) {
        const source = parser.resourcePath(trans.getStagingDataPath(oldData), oldFont.file);
        if (fs.existsSync(source)) {
            const settings = await parser.stageHalfWidthFont(source, trans.getStagingDataPath(), {init: trans.project.options.init});
            trans.project.options.init.halfWidthFont = {...oldFont, ...settings, enabled: oldFont.enabled};
        } else if (oldFont.enabled) throw new Error("The previous project's staged half-width executable is missing.");
    }
    async function copyLayers(value) {
        if (!value || typeof value !== "object") return;
        for (const [key, item] of Object.entries(value)) {
            if (/StagingPath$/.test(key) && typeof item === "string" && item && !copied.has(item)) {
                const source = parser.resourcePath(oldCache, item), target = parser.resourcePath(newCache, item);
                await fs.promises.mkdir(nwPath.dirname(target), {recursive: true});
                if (!fs.existsSync(target)) await fs.promises.copyFile(source, target, fs.constants.COPYFILE_EXCL);
                else if (!(await fs.promises.readFile(source)).equals(await fs.promises.readFile(target))) throw new Error("Conflicting image layer: " + item);
                copied.add(item);
            } else if (item && typeof item === "object") await copyLayers(item);
        }
    }
    for (const [id, oldFile] of Object.entries(oldData.project.files)) {
        const file = trans.project.files[id];
        if(oldFile.tm4Resource && file?.tm4Resource && oldFile.tm4Resource.sha256===file.tm4Resource.sha256 && oldFile.translationConstraints!==undefined)file.translationConstraints=JSON.parse(JSON.stringify(oldFile.translationConstraints));
        if (!oldFile.tm4Image || file?.tm4Image?.pixelSha256 !== oldFile.tm4Image.pixelSha256) continue;
        for (const key of ["kritaLayer", "inpaintLayer", "aiInpaintLayer", "burnInLayer", "aiInpaint"]) await copyLayers(oldFile[key]);
        for (const key of ["data", "context", "parameters", "tags", "comments", "cellInfo", "indexIds", "layerVisibility", "kritaLayer", "inpaintLayer", "aiInpaintLayer", "burnInLayer", "aiInpaint"]) {
            if (oldFile[key] !== undefined) file[key] = JSON.parse(JSON.stringify(oldFile[key]));
        }
    }
    trans.syncFileNavigator("tm4-update-images"); trans.refreshGrid(); trans.gridIsModified(true);
    return result;
};

thisAddon.configureTranslationSettings = async function(values) {
    const project=trans.project;
    if(project?.gameEngine!=="tm4Psp")throw new Error("Open a Tokimeki Memorial 4 PSP project first.");
    const settings=JSON.parse(JSON.stringify(project.options.translationConstraints || guidance.profile.constraints));
    settings.enabled=values.enabled===true;settings.types ||= {};settings.types.scenario ||= {};
    settings.types.messageBox ||= {preserveLineCount:false};
    if(Object.hasOwn(values,'messageBoxPreserveLineCount'))settings.types.messageBox.preserveLineCount=values.messageBoxPreserveLineCount===true;
    for(const [input,key] of [["scenarioCharsPerLine","maxCharsPerLine"],["scenarioMaxLines","maxLines"]]) {
        const value=values[input];
        if(value==null || value==='')delete settings.types.scenario[key];
        else if(Number.isInteger(Number(value)) && Number(value)>0)settings.types.scenario[key]=Number(value);
        else throw new Error("Line limits must be positive whole numbers, or blank for no maximum.");
    }
    let expected=String(values.expectedCrc32 || '').trim();
    if(values.checkSourceCrc===true && !expected) {
        expected=project.options.init.sourceManifest.isoCrc32;
        if(!expected) {
            const source=await parser.resolveSourceIso(project.options.init.entryPoint,{manifest:project.options.init.sourceManifest});
            expected=await SourceChecksum.crc32File(source);
        }
    }
    if(expected)expected=SourceChecksum.normalize(expected);
    if(trans.project!==project)throw new Error("The active project changed; settings were not applied.");
    project.options.translationConstraints=settings;
    guidance.applyProjectDefaults(project);
    project.options.init.sourceChecksum={enabled:values.checkSourceCrc===true,algorithm:'crc32',expected};
    trans.gridIsModified(true);trans.refreshGrid();
    return {constraints:settings,sourceChecksum:project.options.init.sourceChecksum};
};
thisAddon.showTranslationSettingsDialog = function() {
    if(trans.project?.gameEngine!=="tm4Psp")return alert("Open a Tokimeki Memorial 4 PSP project first.");
    const constraints=trans.project.options.translationConstraints || guidance.profile.constraints,checksum=trans.project.options.init.sourceChecksum || {};
    const fields=new CustomFields($("<form></form>"),{jsonForm:{
        schema:{enabled:{type:'boolean',title:'Send and validate parser limits for automatic translations',default:constraints.enabled!==false},
            scenarioCharsPerLine:{type:'number',title:'Scenario: maximum stored characters per line (blank = unrestricted)',default:constraints.types?.scenario?.maxCharsPerLine},
            scenarioMaxLines:{type:'number',title:'Scenario: maximum lines per message (blank = unrestricted)',default:constraints.types?.scenario?.maxLines},
            messageBoxPreserveLineCount:{type:'boolean',title:'Message boxes: require the exact original number of lines',default:constraints.types?.messageBox?.preserveLineCount===true},
            checkSourceCrc:{type:'boolean',title:'Check source ISO CRC32 before Export / Inject',default:checksum.enabled===true},
            expectedCrc32:{type:'string',title:'Expected CRC32 (blank uses the imported source checksum)',default:checksum.expected || ''}},
        form:[{key:'enabled'},{key:'scenarioCharsPerLine'},{key:'scenarioMaxLines'},{key:'messageBoxPreserveLineCount'},{key:'checkSourceCrc'},{key:'expectedCrc32'}]
    }});
    const dialog=$("<div></div>").append($("<p></p>").text("Fixed ASB byte budgets are taken from each occurrence. Growable text has no original-length byte cap. Message boxes may use fewer or more lines within the configured maximum (default 3) and width (default 44 stored characters per line). Enable exact line counts only if desired. Unclassified ASB text and tables keep their original line structure. Check rendered layout in PPSSPP."))
        .append($("<p></p>").text("AI validation uses the translator's Number of retry setting and includes its previous response in corrective turns. Edit game/engine instructions in Translator → Prompts and character voices in Actor Reference. A skipped CRC check affects only that injection."))
        .append(fields.getElm()).appendTo(document.body);
    dialog.dialog({title:'TM4 translation limits and source CRC',width:720,modal:true,close:function(){$(this).dialog('destroy').remove();},buttons:[
        {text:'Save',click:async function(){try{await thisAddon.configureTranslationSettings(fields.getValues());dialog.dialog('close');}catch(error){alert(error.message);}}},
        {text:'Cancel',click:()=>dialog.dialog('close')}
    ]});
    return dialog;
};

thisAddon.registerProjectWizard = function() {
    const $slide = $("<div><h2>Tokimeki Memorial 4 (PSP)</h2><p>Import dialogue, message tables, CSV text and editable interface images from the Japanese PSP ISO. Export and Inject create a separate patched ISO.</p><p>Message-box dialogue may reflow within its line and width limits. Preserve other control codes. Most dialogue can grow; rows with a fixed byte budget must fit. GIM images retain their dimensions and original palette. Python 3.10+ is required; image import also uses Pillow.</p><div class='parserFields'></div></div>");
    ui.newProjectDialog.addMenu({icon: thisAddon.getWebLocation() + "/" + thisAddon.package.icon, descriptionBar: "<h2>Tokimeki Memorial 4 (PSP)</h2>",
        actionBar: "", goToSlide: thisAddon.package.name, at: 8, slides: {parser: ui.newProjectDialog.newSlide(thisAddon.package.name, $slide, {
            buttons: [{text: t("Create Project"), click: async function() {
                try { await thisAddon.prepareNewProject(thisAddon.projectField?.getValues()); ui.newProjectDialog.close(); }
                catch (error) { ui.log.error(error.stack || String(error)); alert(error.message); }
            }}], onActive: () => {
                thisAddon.projectField = new CustomFields($("<form></form>"), {jsonForm: {
                    schema: {
                        entryPoint: {type: "string", title: "Japanese PSP ISO", required: true},
                        projectTitle: {type: "string", title: "Project title", default: parserTitle},
                        includeImages: {type: "boolean", title: "Include editable interface images", default: true},
                        ocrImages: {type: "boolean", title: "Recognize image text with the configured OCR engine", default: true},
                        pythonPath: {type: "string", title: "Python executable (blank uses python from PATH)"},
                        halfWidthEboot: {type: "string", title: "Optional decrypted EBOOT.BIN: enable half-width alphabet (PPSSPP/CFW)"},
                        checkSourceCrc: {type:"boolean",title:"Check source ISO CRC32 before Export / Inject",default:false},
                        expectedCrc32: {type:"string",title:"Expected source CRC32 (blank records this disc's CRC32)"}
                    }, form: [{key: "entryPoint", type: "selectfile", accept: ".iso"}, {key: "projectTitle"}, {key: "includeImages"}, {key: "ocrImages"},
                        {type: "advancedfieldset", title: "Advanced", items: [{key: "pythonPath", type: "selectfile", accept: ".exe"}, {key: "halfWidthEboot", type: "selectfile", accept: ".bin,.elf"}, {key:"checkSourceCrc"}, {key:"expectedCrc32"}]}]
                }});
                $slide.find(".parserFields").empty().append(thisAddon.projectField.getElm());
            }
        })}});
};
thisAddon.registerEngineDetector = function() {
    const registry = window.engineDetectionRegistry;
    if (!registry || registry.definitions.has("tm4Psp")) return;
    registry.register({id: "tm4Psp", addonId: thisAddon.id || thisAddon.package.name, engineIds: supportedEngines,
        displayName: parserTitle, priority: 100, detect: async request => {
            const entryPoint = request.entryPoint || request.selectedPath;
            if (!entryPoint || !await parser.detecttm4Psp(entryPoint)) return {matches: []};
            return {matches: [{engineId: "tm4Psp", confidence: 1, evidence: ["TM4 PSP disc serial and PIDX resource layout."], entryPoint,
                gameRoot: nwPath.dirname(entryPoint), preferredInput: "entryPoint"}]};
        }, openProjectWizard: async (_candidate, launchContext) => {
            ui.newProjectDialog.gotoSlide(thisAddon.package.name, "engineDetectResult");
            registry.setFieldValue(thisAddon.projectField.getElm().find("[name='entryPoint']"), launchContext.entryPoint);
        }});
};
$(document).ready(() => ui.onReady(() => {
    thisAddon.registerProjectWizard(); thisAddon.registerEngineDetector();
    AddonUtils.applyCommonHandlers(supportedEngines, thisAddon);
    engines.getEngine("tm4Psp").addProperty("injectOptionFields",SourceChecksum.injectOptionFields("tm4SkipCrc"));
    engines.addHandler(supportedEngines, "onOpenInjectDialog", async function($dialog) {
        $dialog.find(".copyOptionsBlock").addClass("hidden");
        $dialog.find("[name='tm4SkipCrc']").prop("checked",false).trigger("change");
    });
    ui.mainMenu.addChild("tools", {id: "tm4PspImages", label: "Tokimeki Memorial 4 (PSP)"});
    ui.mainMenu.addChild("tm4PspImages", {id: "tm4PspHalfWidth", label: "Configure half-width alphabet"}).on("select", () => thisAddon.showHalfWidthFontDialog());
    ui.mainMenu.addChild("tm4PspImages", {id:"tm4TranslationSettings",label:"Translation limits and source CRC"}).on("select",()=>thisAddon.showTranslationSettingsDialog());
    ui.mainMenu.addChild("tm4PspImages", {label: "Recognize text in game images"}).on("select", async () => {
        ui.showLoading();
        try {
            const result = await thisAddon.recognizeGameImages();
            trans.syncFileNavigator("tm4-image-ocr"); trans.gridIsModified(true); trans.refreshGrid();
            ui.log("Recognized " + result.blocks + " text blocks in " + result.withText + " images.");
            if (result.failures.length) ui.log.error(result.failures.length + " images could not be recognized; they remain editable.");
        } catch (error) { ui.log.error(error.message); } finally { ui.loadingEnd(); }
    });

}));
