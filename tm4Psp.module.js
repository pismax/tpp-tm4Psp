"use strict";
const fs = require("fs"), path = require("path"), os = require("os");
const {spawn} = require("child_process");
const crypto = require("crypto");
const bridgePath = path.join(__dirname, "python", "tm4_bridge.py");
const speakerRoles = require("./speaker-roles.json");
const SourceChecksum = require("../../js/SourceChecksum.js");

function applySpeakerRole(meta) {
    // Match only verified numeric character-table IDs. Keep user-supplied labels
    // and metadata; never infer a speaker from the wording of a dialogue line.
    const role = Number.isInteger(meta.speakerId) && Object.prototype.hasOwnProperty.call(speakerRoles, meta.speakerId)
        ? speakerRoles[meta.speakerId] : undefined;
    let changed = false;
    for (const [key, value] of Object.entries(role || {})) {
        if (meta[key] === undefined || meta[key] === null || meta[key] === "") { meta[key] = value; changed = true; }
    }
    return changed;
}
function upgradeSpeakerMetadata(project) {
    if (project?.gameEngine !== "tm4Psp") return 0;
    let changed = 0;
    for (const file of Object.values(project.files || {})) {
        if (!["ASB", "TSID"].includes(file.tm4Resource?.kind)) continue;
        for (const parameters of file.parameters || []) for (const meta of parameters || []) {
            if (meta && applySpeakerRole(meta)) changed++;
        }
    }
    return changed;
}

async function bridge(command, request, options = {}) {
    const temp = await fs.promises.mkdtemp(path.join(options.tempRoot || os.tmpdir(), "tpp-tm4-call-"));
    const input = path.join(temp, "request.json"), output = path.join(temp, "response.json");
    try {
        await fs.promises.writeFile(input, JSON.stringify(request));
        const python = options.pythonPath || options.init?.pythonPath || "python";
        const code = await new Promise((resolve, reject) => {
            const proc = spawn(python, ["-B", bridgePath, command, input, output], {windowsHide: true, stdio: ["ignore", "ignore", "pipe"], env: {...process.env, PYTHONIOENCODING: "utf-8"}});
            let stderr = "";
            proc.stderr.on("data", chunk => { stderr = (stderr + chunk.toString()).slice(-12000); });
            proc.once("error", error => reject(new Error("TM4 requires Python 3.10 or newer. Select a Python executable in New Project. " + error.message)));
            proc.once("close", status => resolve({status, stderr}));
        });
        const result = await fs.promises.readFile(output, "utf8").then(JSON.parse).catch(() => null);
        if (code.status !== 0 || result?.error) throw new Error(result?.error || code.stderr || "TM4 helper failed: " + code.status);
        if (!result || !Object.prototype.hasOwnProperty.call(result, "result")) throw new Error("Invalid TM4 helper response.");
        return result.result;
    } finally {
        for (const name of [input, output]) await fs.promises.unlink(name).catch(() => {});
        await fs.promises.rmdir(temp).catch(() => {});
    }
}
function resourcePath(root, name) {
    const target = path.resolve(root, String(name).replace(/^[\\/]+/, ""));
    const relative = path.relative(path.resolve(root), target);
    if (!relative || relative === ".." || relative.startsWith(".." + path.sep) || path.isAbsolute(relative)) throw new Error("Invalid TM4 resource path: " + name);
    return target;
}
async function sha256File(filename) {
    const hash = crypto.createHash("sha256");
    for await (const chunk of fs.createReadStream(filename)) hash.update(chunk);
    return hash.digest("hex");
}

/** Resolve only user-selected sources and nearby known filenames, never a
 * recursive ROM-library search. Every replacement must be the imported disc. */
async function resolveSourceIso(savedIso, options = {}) {
    const manifest = options.manifest || {}, expectedName = path.basename(savedIso || manifest.iso || "game.iso");
    const explicit = typeof options.sourceMaterial === "string" && options.sourceMaterial.trim();
    const candidates = [], seen = new Set();
    async function candidate(filename) {
        const absolute = path.resolve(filename), key = process.platform === "win32" ? absolute.toLowerCase() : absolute;
        if (seen.has(key)) return;
        seen.add(key);
        try {
            const stat = await fs.promises.stat(absolute);
            if (stat.isFile()) candidates.push({path: absolute, size: stat.size});
        } catch (error) { if (error.code !== "ENOENT" && error.code !== "ENOTDIR") throw error; }
    }
    if (explicit) {
        const source = path.resolve(options.sourceMaterial);
        const stat = await fs.promises.stat(source).catch(error => {
            if (error.code === "ENOENT" || error.code === "ENOTDIR") return null;
            throw error;
        });
        if (stat?.isDirectory()) {
            await candidate(path.join(source, expectedName));
            const entries = await fs.promises.readdir(source, {withFileTypes: true});
            for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
                if (entry.isFile() && /\.iso$/i.test(entry.name)) await candidate(path.join(source, entry.name));
            }
        } else if (stat?.isFile()) await candidate(source);
    } else {
        if (savedIso) await candidate(savedIso);
        if (manifest.iso) await candidate(manifest.iso);
        for (const original of [savedIso, manifest.iso].filter(Boolean)) {
            const directory = path.dirname(original), stem = path.basename(original, path.extname(original));
            await candidate(path.join(directory, stem, expectedName));
        }
        for (const directory of options.searchDirs || []) if (directory) await candidate(path.join(directory, expectedName));
    }
    if (!candidates.length) throw new Error("The original Tokimeki Memorial 4 ISO could not be found" +
        (explicit ? " in the selected source: " + options.sourceMaterial : ". Saved path: " + (savedIso || manifest.iso || "(none)")) +
        ". In Inject, select the folder containing the original ISO, or select the ISO file itself.");
    if (!/^[a-f0-9]{64}$/i.test(manifest.isoSha256 || "")) throw new Error("The project is missing its source ISO checksum. Recreate the project from the original disc before exporting.");
    for (const entry of candidates) {
        if (Number.isFinite(manifest.isoSize) && entry.size !== manifest.isoSize) continue;
        if ((await sha256File(entry.path)).toLowerCase() === manifest.isoSha256.toLowerCase()) return entry.path;
    }
    throw new Error("The " + (explicit ? "selected source" : "located ISO") + " does not match the original disc used to create this project. Choose the original Japanese ISO; translated or different disc images cannot be used as the source.");
}
async function readDescriptor(sourcePath) {
    const obj = JSON.parse(await fs.promises.readFile(sourcePath, "utf8"));
    if (obj.version !== 1 || !["ASB", "TSID", "CSV"].includes(obj.kind) || !Array.isArray(obj.rows) || !Array.isArray(obj.destinations)) throw new Error("Invalid TM4 staged text resource.");
    return obj;
}
class tm4PspProject {
    constructor(sourceDir, options = {}) { this.sourceDir = sourceDir; this.options = options; this.files = []; }
    static async scan(entryPoint, options = {}) {
        const root = options.outputDir || await fs.promises.mkdtemp(path.join(options.tempRoot || os.tmpdir(), "tpp-tm4-source-"));
        const result = await bridge("scan", {iso: entryPoint, out: root, includeImages: options.init?.includeImages !== false}, options);
        return Object.assign(new tm4PspProject(result.sourceDir, options), result);
    }
}
async function parseFile(sourcePath) {
    const obj = await readDescriptor(sourcePath);
    const filename = path.basename(obj.destinations[0]).replace(/^\d{5}_/, "");
    const result = {data: [], context: [], parameters: [], tags: [], indexIds: {}, filename, basename: filename,
        translationConstraintType: obj.kind === "ASB" ? "scenario" : "table",
        tm4Resource: {kind: obj.kind, sha256: obj.sha256, destinations: obj.destinations}};
    // Translator++ sanitizes duplicate source rows on load. Merge their
    // contexts/parameters here first so no occurrence or speaker is discarded.
    const indices = new Map();
    for (const row of obj.rows) {
        let index = indices.get(row.text);
        if (index === undefined) {
            index = result.data.length; indices.set(row.text, index);
            result.data.push([row.text, ""]); result.context.push([]);
            result.parameters.push([]); result.tags.push([]);
        }
        result.context[index].push(row.context);
        const {text, context, ...meta} = row;
        if(obj.kind==='ASB'){
            if(!meta.messageType){meta.messageType=meta.canGrow===true?'messageBox':'unknown';meta.messageTypeEvidence=meta.canGrow===true?'ASB direct display function 0 (saved reference evidence)':'No verified single display-function use';}
            if(meta.messageType==='messageBox')meta.translationConstraintType='messageBox';
        }
        if (["ASB", "TSID"].includes(obj.kind)) applySpeakerRole(meta);
        result.parameters[index].push({...meta, contextStr: context});
        if (!Object.prototype.hasOwnProperty.call(result.indexIds, row.text)) Object.defineProperty(result.indexIds, row.text, {value: index, enumerable: true, writable: true, configurable: true});
    }
    return result;
}
function resolveTranslation(row, selected = {}) {
    const pair = selected.translationPair || {}, info = selected.info || selected.translationInfo || {};
    const keys = [row.context + "\n" + row.text];
    if (info.groupLevel > 0) keys.push(row.context.split("/").slice(0, info.groupLevel).join("/") + "\n" + row.text);
    keys.push(row.text);
    for (const key of keys) if (Object.prototype.hasOwnProperty.call(pair, key) && typeof pair[key] === "string") return pair[key] || undefined;
    return undefined;
}
async function resolvedRows(sourcePath, selected) {
    const obj = await readDescriptor(sourcePath), translations = {};
    for (const row of obj.rows) {
        const value = resolveTranslation(row, selected);
        if (value !== undefined) translations[row.context] = value;
    }
    return translations;
}
async function writeFile(sourcePath, destinationPath, options = {}) {
    if (path.resolve(sourcePath).toLowerCase() === path.resolve(destinationPath).toLowerCase()) throw new Error("Cannot overwrite staged source resource.");
    return bridge("write", {source: sourcePath, target: destinationPath, translations: await resolvedRows(sourcePath, options), messageBoxLayout:options.init?.messageBoxLayout,validationPolicy:options.init?.validationPolicy}, options);
}
async function exportIso(iso, target, options = {}) {
    const sourceChecksum=await SourceChecksum.verify(iso,options.init?.sourceChecksum,{skip:options.skipSourceCrc===true,signal:options.signal});
    const translations = {};
    for (const [name, selected] of Object.entries(options.translations || {})) translations[name] = await resolvedRows(resourcePath(options.stage, name), selected);
    const font = options.init?.halfWidthFont;
    const halfWidthEboot = font?.enabled ? resourcePath(options.stage, font.file) : undefined;
    const halfWidthWeight = font?.enabled ? (font.weight || "regular") : "regular";
    return bridge("build", {iso, target, stage: options.stage, manifest: options.manifest, translations, images: options.images || {}, halfWidthEboot, halfWidthWeight, sourceChecksum, messageBoxLayout:options.init?.messageBoxLayout,validationPolicy:options.init?.validationPolicy}, options);
}
async function stageHalfWidthFont(source, stage, options = {}) {
    // Validate before changing project settings. Cache the original executable
    // with the project so export/reopen/update never depend on the selected path.
    if (typeof source !== "string" || !source.trim()) throw new Error("Select a decrypted EBOOT.BIN dumped from your original game first.");
    const info = await bridge("font", {source}, options);
    const file = "font/tm4-decrypted-eboot.bin", target = resourcePath(stage, file);
    await fs.promises.mkdir(path.dirname(target), {recursive: true});
    const raw = await fs.promises.readFile(source);
    if (crypto.createHash("sha256").update(raw).digest("hex") !== info.sourceSha256) throw new Error("The selected executable changed during validation.");
    await fs.promises.writeFile(target, raw);
    return {enabled: true, file, ...info};
}
async function detecttm4Psp(entryPoint, options = {}) {
    if (!/\.iso$/i.test(entryPoint) || !fs.existsSync(entryPoint)) return false;
    return bridge("detect", {iso: entryPoint}, options);
}
module.exports = {tm4PspProject, parseFile, writeFile, detecttm4Psp, exportIso, stageHalfWidthFont, upgradeSpeakerMetadata, resourcePath, readDescriptor, resolveTranslation, resolvedRows, resolveSourceIso, bridge};
