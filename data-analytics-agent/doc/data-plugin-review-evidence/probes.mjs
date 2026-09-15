import { createHash } from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const pluginRoot = process.argv[2];
if (!pluginRoot) throw new Error('Usage: node probes.mjs /absolute/path/to/plugin-copy');
const load = file => import(pathToFileURL(path.join(pluginRoot,file)).href);
const {createDataAppWorker} = await load('templates/data-app/base/src/data-app-worker.js');
const {serializeDashboardUrlState} = await load('templates/data-app/base/src/dashboard-url-state.js');
const {assembleDataAppHtml} = await load('scripts/data-app-build.mjs');
const worker=createDataAppWorker({html:'<html><head></head><body></body></html>',seedSnapshot:{queries:{}}});
const email='reviewer@example.invalid';
const env={DATA_APP_OWNER_EMAIL_SHA256:createHash('sha256').update(email).digest('hex')};
let malformed;
try {const r=await worker.fetch(new Request('https://review.invalid/api/queries',{method:'PUT',headers:{'oai-authenticated-user-email':email,'content-type':'application/json'},body:'{'}),env); malformed={status:r.status};}catch(e){malformed={thrown:e.name,message:e.message};}
const snap={filters:[{id:'account',field:'account',shareInUrl:false}],queries:{q:{rows:[{account:'PRIVATE-FIXTURE-ACCOUNT'}]}}};
const url=serializeDashboardUrlState(snap,[],{filters:{account:'PRIVATE-FIXTURE-ACCOUNT'},complete:true},'https://review.invalid/');
const min=assembleDataAppHtml({appCode:'',protectedStyles:'',printStyles:'',authored:{factorySource:'(() => ({}))',themeCss:'',conventionalCss:'',importedCss:''},snapshotBytes:Buffer.from('{"queries":{"q":{"rows":[{"value":1}]}}}'),runtimeSha256:'a'.repeat(64)});
const noOwner=await worker.fetch(new Request('https://review.invalid/api/queries',{method:'PUT',body:'{}'}),{});
console.log(JSON.stringify({malformedOwnerQueryUpdate:malformed,completeViewPrivateFilter:url.toString(),metadataFreeSnapshotAccepted:Boolean(min),unconfiguredOwnerStatus:noOwner.status},null,2));
