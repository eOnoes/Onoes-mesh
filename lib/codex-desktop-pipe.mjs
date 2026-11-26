import {readdir} from 'node:fs/promises';
const directory='\\\\.\\pipe\\';
export const CODEX_DESKTOP_NAMESPACE=directory+'codex-app-tools';
const nativeName=/^codex-app-tools-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;

// Local OS discovery only. An ambiguous instance never becomes a guessed route.
// Caller and project verification still happen through the first-party app API.
export async function resolveCodexDesktopPipe(pinned,{list=()=>readdir(directory)}={}){
  if(typeof pinned!=='string'||!pinned.startsWith(directory)||pinned!==CODEX_DESKTOP_NAMESPACE&&!nativeName.test(pinned.slice(directory.length)))throw Error('Native desktop discovery requires its reviewed local endpoint.');
  const names=[...new Set((await list()).filter(name=>nativeName.test(name)))];
  const prior=pinned.slice(directory.length);
  if(names.includes(prior))return pinned;
  if(names.length!==1)throw Error('Codex desktop is unavailable or ambiguous. Open the intended desktop instance and refresh.');
  return directory+names[0];
}
