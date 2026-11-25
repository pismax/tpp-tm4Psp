"use strict";

// Optional Node worker entry. UI objects and callbacks cannot cross the
// structured-clone boundary. Send paths/options/plain datasets, not instances.
const {isMainThread, parentPort, workerData} = require("worker_threads");
const parser = require("./tm4Psp.module.js");

if (!isMainThread) {
    void (async () => {
        try {
            let result;
            switch (workerData?.command) {
                case "ping": result = "ok"; break;
                case "scan": {
                    const project = await parser.tm4PspProject.scan(workerData.sourceDir, workerData.options);
                    result = {sourceDir: project.sourceDir, files: project.files, manifest: project.manifest};
                    break;
                }
                case "parse":
                    result = await parser.parseFile(workerData.sourcePath, workerData.options);
                    break;
                case "write":
                    result = await parser.writeFile(workerData.sourcePath, workerData.destinationPath, workerData.options);
                    break;
                default: throw new Error("Unknown parser worker command: " + workerData?.command);
            }
            parentPort.postMessage({result, errors: []});
        } catch (error) {
            parentPort.postMessage({result: null, errors: [error.stack || String(error)]});
        }
    })();
}

// Node usage: new Worker(require.resolve("./tm4Psp.worker.js"), {
//     workerData: {command: "parse", sourcePath, options: {init: {}}}
// });
// Listen for message/error/exit. An errors[] response is a failure even if the
// worker exits normally. Keep this file uncompiled; the business module is the
// compile.modules target. Verify worker module loading in a published build too.
