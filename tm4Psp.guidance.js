'use strict';
const profile=require('./translation-guidance.json');
const clone=value=>JSON.parse(JSON.stringify(value));
function applyProjectDefaults(project) {
    if (project?.gameEngine!=='tm4Psp') return false;
    project.options ||= {};project.options.init ||= {};project.files ||= {};project.references ||= {};
    let changed=false;
    if (!project.options.translationConstraints) {project.options.translationConstraints=clone(profile.constraints);changed=true;}
    const constraints=project.options.translationConstraints;
    if(!constraints.optionalNamePattern){constraints.optionalNamePattern=profile.constraints.optionalNamePattern;changed=true;}
    const validationPolicy=require('../../js/TranslationValidation.js').capture(project);
    if(JSON.stringify(project.options.init.validationPolicy)!==JSON.stringify(validationPolicy)){project.options.init.validationPolicy=validationPolicy;changed=true;}
    constraints.types ||= {};
    if(!constraints.types.messageBox){constraints.types.messageBox=clone(profile.constraints.types.messageBox);changed=true;}
    if (!project.options.init.sourceChecksum) {
        project.options.init.sourceChecksum={enabled:false,algorithm:'crc32',expected:project.options.init.sourceManifest?.isoCrc32 || ''};changed=true;
    }
    for (const file of Object.values(project.files)) if (file.tm4Resource && !file.translationConstraintType) {
        file.translationConstraintType=file.tm4Resource.kind==='ASB'?'scenario':'table';changed=true;
    }
    for(const file of Object.values(project.files))if(file.tm4Resource?.kind==='ASB'){
        for(const occurrences of file.parameters || [])for(const p of occurrences || []){
            if(!p || typeof p!=='object')continue;
            // canGrow was emitted only when every reference was the verified
            // direct call to display function 0. Reuse that evidence on reopen.
            if(!p.messageType){p.messageType=p.canGrow===true?'messageBox':'unknown';p.messageTypeEvidence=p.canGrow===true?'ASB direct display function 0 (saved reference evidence)':'No verified single display-function use';changed=true;}
            if(p.messageType==='messageBox' && !p.translationConstraintType){p.translationConstraintType='messageBox';changed=true;}
        }
    }
    const messageSettings={...constraints,...constraints.types.scenario,...constraints.types.messageBox};
    const layout={preserveLineCount:messageSettings.preserveLineCount!==false,
        maxLines:messageSettings.maxLines ?? null,maxCharsPerLine:messageSettings.maxCharsPerLine ?? null};
    if(JSON.stringify(project.options.init.messageBoxLayout)!==JSON.stringify(layout)){project.options.init.messageBoxLayout=layout;changed=true;}
    for(const file of Object.values(project.files)) if(file.tm4Image && !file.translationConstraintType){file.translationConstraintType='image';changed=true;}
    let reference=project.files['Actor Reference'] || project.references['Actor Reference'];
    if (!reference) {
        reference={type:'reference',translationConstraintType:'reference',originalFormat:'TM4 PSP CHARACTER REFERENCE',dirname:'*',basename:'Actor Reference',filename:'Actor Reference',
            path:'Actor Reference',relPath:'Actor Reference',extension:'',data:[],context:[],parameters:[],tags:[],indexIds:{},
            actorInfoColumn:2,note:'Column 1: English name (editable transliteration). Column 2: gender, personality and suggested translation voice. Voice directions are editorial guidance, not additional dialogue. Sources are in row parameters.'};
        project.files['Actor Reference']=reference;project.references['Actor Reference']=reference;changed=true;
    }
    if(!project.files['Actor Reference']){project.files['Actor Reference']=reference;changed=true;}
    if(!project.references['Actor Reference']){project.references['Actor Reference']=reference;changed=true;}
    reference.data ||= [];
    // Existing reference layouts/edits are preserved. Only add absent names.
    const infoColumn=Number.isInteger(reference.actorInfoColumn) && reference.actorInfoColumn>0 ? reference.actorInfoColumn : Math.max(2,...reference.data.map(row=>row?.length || 0));
    if (reference.actorInfoColumn===undefined) {reference.actorInfoColumn=infoColumn;changed=true;}
    reference.parameters ||= [];reference.context ||= [];reference.tags ||= [];reference.indexIds ||= {};
    for (const actor of profile.actors) {
        const index=reference.data.findIndex(row=>row?.[0]===actor.name);
        const info=`${actor.gender}; ${actor.personality} Voice guidance: ${actor.voice}`;
        if (index>=0) {
            const cells=reference.data[index],nameColumn=infoColumn===1?2:1;
            if(!cells[nameColumn]){cells[nameColumn]=actor.translation;changed=true;}
            if(!cells[infoColumn]){cells[infoColumn]=info;changed=true;}
            continue;
        }
        const row=reference.data.length, cells=[actor.name,actor.translation];
        if(infoColumn===1)cells[2]=actor.translation;
        cells[infoColumn]=info;
        reference.data.push(cells);reference.context[row]=['tm4/actor/'+actor.name];reference.tags[row]=[];
        reference.parameters[row]=[{speakerGender:actor.gender,sources:actor.sources,aliases:actor.aliases || [],voiceGuidanceIsEditorial:true}];
        Object.defineProperty(reference.indexIds,actor.name,{value:row,writable:true,configurable:true,enumerable:true});
        changed=true;
    }
    if (changed) {reference.indexIsBuilt=false;reference.cacheResetOnChange={};}
    return changed;
}
module.exports={profile,applyProjectDefaults};
