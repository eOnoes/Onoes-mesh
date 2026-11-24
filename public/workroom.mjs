import {bindCardDrag} from './workroom-drag.mjs';
import {captureBoardView,restoreBoardView} from './workroom-view.mjs';
import {saveCardBrief} from './workroom-edit.mjs';
import {createBoardLoader,createCardOpener} from './workroom-load.mjs';
import {handoffStatus,handoffDisplayState,recoveredHandoff,taskTimeline,cardNextAction,nativeWorkerStatus} from './workroom-status.mjs';
import {nimsPlanningBrief} from './lead-policy.mjs';
import {createPlanEditor,scopedTeamStatus,teamRequestNotice} from './workroom-plan.mjs';
import {paintMemoryState} from './workroom-memory-state.mjs';
import {workroomGuide} from './workroom-guide.mjs';
const root=document.getElementById('workroom-board');
const request=(...args)=>window.meshWorkroom.request(...args);
const stages=[['backlog','Backlog'],['ready','Ready'],['working','Working'],['needs_you','Needs you'],['done','Done']];
const lanes=[{key:'ready',label:'To do',stages:['backlog','ready']},{key:'working',label:'In progress',stages:['working','needs_you']},{key:'done',label:'Done',stages:['done']}];
let tasks=[], selected=null, agents=[], pending=null, busy=false,teamPolicy=null,agentsKnown=false;
let followTimer=null,viewEpoch=0;
const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
if(root){
  const heading=el('h1','Project board.');
  const description=el('p','Keep your work moving. Tap a card to inspect the goal and next steps.');
  const refresh=el('button','Refresh board');refresh.type='button';
  const projectFilter=el('input');projectFilter.placeholder='Filter by project';projectFilter.setAttribute('aria-label','Filter board by project');
  const status=el('p');status.setAttribute('role','status');
  const maintenanceNotice=el('p');maintenanceNotice.setAttribute('role','status');maintenanceNotice.hidden=true;
  let paintCardPolicy=null;
  const paintMaintenance=()=>{maintenanceNotice.textContent=teamRequestNotice(teamPolicy);maintenanceNotice.hidden=!maintenanceNotice.textContent;paintCardPolicy?.();};
  const board=el('div');board.className='workroom-lanes';
  const createLead=document.getElementById('create-owner');
  const createLeadLabel=document.querySelector('label[for="create-owner"]');
  const createLeadHint=createLead?.nextElementSibling;
  const originalLead=createLead?{required:createLead.required,hidden:createLead.hidden,labelHidden:createLeadLabel?.hasAttribute('hidden')||false,hint:createLeadHint?.textContent}:null;
  function paintCreateLead(){
    if(!createLead)return;
    const managed=teamPolicy?.simpleFlow===true;
    createLead.required=managed?false:originalLead.required;
    createLead.hidden=managed||originalLead.hidden;
    createLeadLabel?.toggleAttribute('hidden',managed||originalLead.labelHidden);
    if(createLeadHint)createLeadHint.textContent=managed?'Ideas stay unassigned in To do. Move to In progress for the team to inspect them.':originalLead.hint;
  }
  let checkingStatus='';
  const boardLoader=createBoardLoader({request,onBoard(result){
    tasks=result.tasks;teamPolicy=result.teamPolicy||null;agentsKnown=false;paintMaintenance();draw();if(guide.open)paintGuide(false);
    root.dataset.managedFlow=teamPolicy?.simpleFlow?'1':'0';
    paintCreateLead();
    checkingStatus=`${tasks.length} saved tasks · Checking agent connections…`;status.textContent=checkingStatus;
    const linkedId=window.meshWorkroom.linkedTask;
    if(linkedId && !document.querySelector('dialog[open]')){
      const task=tasks.find(item=>item.id===linkedId);
      window.meshWorkroom.finishTaskLink(task);
      if(task)cardOpener.request(task.id);
      else status.textContent='This card is unavailable. Choose another card from the board.';
    }
  },onAgents(peers,available){
    agents=peers;agentsKnown=available;paintCardPolicy?.();draw();
    if(status.textContent===checkingStatus)status.textContent=`${tasks.length} saved tasks · ${available?'Plan / build / review handoffs':'Agent connections unavailable; saved cards remain usable'}`;
  }});
  const dragHelp=el('p','Drag anywhere on a card with your mouse. On your phone, hold briefly, then drag. Tap once for details; swipe without holding to scroll.');
  const details=el('dialog');details.className='workroom-sheet';details.setAttribute('aria-label','Task details');
  let preserveDraft=false;
  details.addEventListener('input',()=>{preserveDraft=true;});
  details.addEventListener('change',()=>{preserveDraft=true;});
  details.addEventListener('mesh-leave-workroom',()=>{
    if(!busy && !pending && !preserveDraft)closeDetails();
  });
  let returnFocus=null;
  function closeDetails(){
    viewEpoch++;paintCardPolicy=null;clearTimeout(followTimer);
    const id=selected?.id;
    window.meshWorkroom.dismissTaskLink?.(id);
    details.close();selected=null;pending=null;
    (Array.from(board.querySelectorAll('[data-task-id]')).find(node=>node.dataset.taskId===id)||returnFocus)?.focus();
  }
  details.addEventListener('cancel',event=>{if(busy){event.preventDefault();return;}event.preventDefault();closeDetails();});
  root.append(heading,description,refresh,projectFilter,dragHelp,maintenanceNotice,status,board,details);
  // Keep the existing admission control visible when the board is locked.
  root.insertBefore(document.getElementById('workroom-session-recovery'),board);
  const createButton=el('button','+ New task');createButton.type='button';
  refresh.before(createButton);
  const helpButton=el('button','? Help');helpButton.type='button';helpButton.setAttribute('aria-label','Workroom walkthrough');
  helpButton.setAttribute('aria-haspopup','dialog');refresh.after(helpButton);
  const guide=el('dialog');guide.className='workroom-sheet';guide.setAttribute('aria-labelledby','workroom-guide-title');
  const guideTitle=el('h2','How to use Workroom');guideTitle.id='workroom-guide-title';
  const guideCount=el('p');guideCount.setAttribute('role','status');
  const guideBody=el('section');guideBody.tabIndex=-1;
  const guideActions=el('div');guideActions.className='actions';
  const guideBack=el('button','Back');guideBack.type='button';
  const guideNext=el('button','Next');guideNext.type='button';
  const guideClose=el('button','Close help');guideClose.type='button';
  let guideStep=0;
  function paintGuide(focus=true){
    const walkthrough=workroomGuide(teamPolicy);
    guideCount.textContent=`Step ${guideStep+1} of ${walkthrough.length}`;
    guideBody.replaceChildren(el('h3',walkthrough[guideStep][0]),el('p',walkthrough[guideStep][1]));
    guideBack.disabled=guideStep===0;guideNext.textContent=guideStep===walkthrough.length-1?'Done':'Next';
    if(focus)guideBody.focus();
  }
  guideActions.append(guideBack,guideNext,guideClose);guide.append(guideTitle,guideCount,guideBody,guideActions);root.append(guide);
  helpButton.addEventListener('click',()=>{guideStep=0;guide.showModal();paintGuide();});
  guideBack.addEventListener('click',()=>{if(guideStep>0){guideStep--;paintGuide();}});
  guideNext.addEventListener('click',()=>{if(guideStep<workroomGuide(teamPolicy).length-1){guideStep++;paintGuide();}else guide.close();});
  guideClose.addEventListener('click',()=>guide.close());guide.addEventListener('close',()=>helpButton.focus());
  const createDialog=el('dialog');createDialog.className='workroom-sheet';createDialog.setAttribute('aria-label','New task');
  const createClose=el('button','Cancel');createClose.type='button';
  const createStatus=el('p');createStatus.id='workroom-create-status';createStatus.setAttribute('role','status');
  const createForm=document.getElementById('create-form');
  createForm.closest('article').hidden=true;
  createDialog.append(el('h2','New task'),createForm,createStatus,createClose);
  root.append(createDialog);
  createButton.addEventListener('click',()=>{createStatus.textContent='';createDialog.showModal();if(!document.getElementById('create-title').disabled)document.getElementById('create-title').focus();});
  createClose.addEventListener('click',()=>createDialog.close());
  createDialog.addEventListener('close',()=>createButton.focus());
  window.addEventListener('mesh-task-created',event=>{createDialog.close();projectFilter.value='';act(async()=>{await load();status.textContent='Task created and saved. Tap its card to add a goal and steps.';});});
  const moveDialog=el('dialog');moveDialog.className='workroom-sheet';moveDialog.setAttribute('aria-label','Choose task owner');
  let pendingMove=null;
  const moveTitle=el('h2','Who owns this task?');
  const moveNote=el('p');
  const moveOwnerLabel=el('label','Task owner');const moveOwner=el('select');moveOwnerLabel.append(moveOwner);
  const moveNotice=el('p');moveNotice.setAttribute('role','status');
  const moveSave=el('button','Assign and move');moveSave.type='button';
  const moveCancel=el('button','Cancel');moveCancel.type='button';
  moveDialog.append(moveTitle,moveNote,moveOwnerLabel,moveNotice,moveSave,moveCancel);root.append(moveDialog);
  moveCancel.addEventListener('click',()=>{if(!busy){pendingMove=null;moveDialog.close();}});
  moveDialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();else pendingMove=null;});
  moveSave.addEventListener('click',()=>act(async()=>{
    if(!pendingMove || !moveOwner.value)throw new Error('Choose who owns the task.');
    moveSave.disabled=true;
    try{await saveMove(pendingMove.task,pendingMove.key,moveOwner.value);pendingMove=null;moveDialog.close();}
    finally{moveSave.disabled=false;}
  }));
  async function saveMove(task,key,owner){
    const {project,criteria,team,revision}=task.workroom;
    await request('/api/workroom/'+task.id,{method:'PATCH',body:JSON.stringify({project,criteria,owner,team,revision,stage:key})});
    await load();
    status.textContent=teamPolicy?.simpleFlow&&key==='working'?'Request queued for the team. Missing information will appear on the card.':`Moved to ${stages.find(stage=>stage[0]===key)[1]}.`;
  }
  async function move(task,key){
    if(key===task.workroom.stage)return;
    if(teamPolicy?.simpleFlow&&task.workroom.stage==='done'&&key!=='done')throw Error('Open the completed card and choose Request changes so the team knows what to fix.');
    if(key==='working' && !task.workroom.owner&&!teamPolicy?.simpleFlow){
      pendingMove={task,key};moveNotice.textContent='';moveOwner.replaceChildren();
      for(const [value,name] of [['','Choose a project lead'],['nims','Nims (Codex)'],['echo','Echo']]){
        const option=el('option',name);option.value=value;moveOwner.append(option);
      }
      moveNote.textContent=`Choose one owner for “${task.title}” before moving it to In progress. This only organizes the board; it does not send a message or start work.`;
      moveDialog.showModal();moveOwner.focus();return;
    }
    await saveMove(task,key,task.workroom.owner);
  }
  function handleDrag(handle,card,task){
    bindCardDrag({handle,card,board,onMove:key=>act(()=>move(task,key)),isBusy:()=>busy,document});
    // Keyboard users have the same stage choices without needing a pointer.
    handle.addEventListener('keydown',event=>{
      const delta=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;if(!delta)return;
      event.preventDefault();const next=lanes[lanes.findIndex(lane=>lane.stages.includes(task.workroom.stage))+delta];
      if(next)act(()=>move(task,next.key));
    });
  }
  window.meshWorkroom.onClear(()=>{
    boardLoader.clear();cardOpener.clear();agentsKnown=false;root.dataset.managedFlow='0';
    viewEpoch++;paintCardPolicy=null;clearTimeout(followTimer);
    tasks=[];selected=null;agents=[];pending=null;teamPolicy=null;paintMaintenance();paintCreateLead();
    details.close();details.replaceChildren();board.replaceChildren();
    createDialog.close();createForm.reset();createStatus.textContent='';
    pendingMove=null;moveDialog.close();moveNote.textContent='';moveNotice.textContent='';moveOwner.replaceChildren();
    status.textContent='Start a session to view the board.';
  });
  const act=async operation=>{if(busy)return;busy=true;refresh.disabled=true;try{await operation();}catch(error){status.textContent=error.message;if(moveDialog.open)moveNotice.textContent=error.message;const planNotice=details.querySelector('.workroom-plan [role=status]');if(planNotice)planNotice.textContent=error.message;const notice=details.querySelector('[role="status"]');if(notice)notice.textContent=error.message;const dockNotice=details.querySelector('.workroom-sheet-footer [role=status]');if(dockNotice)dockNotice.textContent=error.message;}finally{busy=false;refresh.disabled=false;void cardOpener.drain();}};
  const cardOpener=createCardOpener({isBusy:()=>busy,open:id=>act(()=>open(id))});
  function draw(){
    const view=captureBoardView(board,document);
    board.replaceChildren();
    for(const {key,label,stages:members} of lanes){
      const column=el('article');column.className='workroom-lane';column.dataset.workroomStage=key;
      const visible=tasks.filter(task=>members.includes(task.workroom.stage) && task.workroom.project.toLowerCase().includes(projectFilter.value.toLowerCase()));
      column.append(el('h3',`${label} · ${visible.length}`));
      column.dataset.density=visible.length<=4?'1':visible.length<=8?'2':'3';
      const stack=el('div');stack.className='workroom-stack';stack.setAttribute('aria-label',label+' tasks');
      column.append(stack);
      if(!visible.length)stack.append(el('p','No tasks'));
      for(const task of visible){
        const button=el('button');button.type='button';button.dataset.taskId=task.id;button.className='workroom-card-open';button.setAttribute('aria-label','Open '+task.title);button.title=task.title;
        button.append(el('b',task.title));
        const gestures='Tap to open. Hold and drag to move, or use left and right arrow keys.';
        button.setAttribute('aria-description',gestures);
        if(task.flow?.state==='clarification'){
          const question=task.flow.question?.trim() || 'Clarification requested';
          const preview=el('small','? '+question);
          preview.className='workroom-card-question';
          button.append(preview);
          button.title=task.title+' — '+question;
          button.setAttribute('aria-description','Clarification requested. '+question+' '+gestures);
        }else if(!teamPolicy?.simpleFlow){
          const completed=task.progress.checklist.filter(step=>step.status==='done').length;
          button.append(el('small',`${completed}/${task.progress.checklist.length} steps`));
        }
        if(teamPolicy?.simpleFlow&&task.workroom.stage==='done')button.append(el('small',task.flow?.ownerDecision==='accepted'?'Accepted by Eddie':'Ready for your review'));
        if(!teamPolicy?.simpleFlow){
        const report=task.agentUpdates?.at(-1);if(report && !report.applied)button.append(el('small',`Agent: ${report.update.checklist.filter(step=>step.status==='done').length}/${report.update.checklist.length} · unreviewed`));
        if(task.workroom.stage==='needs_you')button.append(el('small','Needs you'));
        const handoff=task.messages.filter(message=>['plan','work','review'].includes(message.phase)).at(-1);
        if(handoff)button.append(el('small',`${handoff.phase} → ${handoff.agentId} · ${handoffDisplayState(handoff)}`));
        const signal=agentsKnown&&!recoveredHandoff(handoff)?handoffStatus(task,agents):null;if(signal)button.append(el('small',signal.label));
        }
        button.addEventListener('click',()=>{returnFocus=button;cardOpener.request(task.id);});
        const card=el('div');card.className='workroom-card';
        handleDrag(button,card,task);card.append(button);stack.append(card);
      }
      board.append(column);
    }
    restoreBoardView(board,view);
  }
  async function load(){
    return boardLoader.load();
  }
  function field(form,label,value,multiline=false){
    const wrapper=el('label',label);const input=el(multiline?'textarea':'input');input.value=value;wrapper.append(input);form.append(wrapper);return input;
  }
  async function open(id){
    const epoch=++viewEpoch;clearTimeout(followTimer);
    const opened=await request('/api/workroom/'+id);
    if(epoch!==viewEpoch || document.getElementById('panel-workroom')?.hidden)return;
    preserveDraft=false;
    paintCardPolicy=null;selected=opened.task;teamPolicy=opened.teamPolicy||null;paintMaintenance();
    // Never carry an uncertain message into another task.
    pending=null;details.replaceChildren();details.classList.add('workroom-task-sheet');details.classList.toggle('workroom-simple-flow',Boolean(teamPolicy?.simpleFlow));
    const content=el('div');content.className='workroom-sheet-content';
    const actionBar=el('section');actionBar.className='workroom-sheet-footer';actionBar.setAttribute('aria-label','Card actions');
    let actionTask=selected,finishAction=null,recordAction=null,reviewAnchor=null,renderActions=()=>{};
    const toolbar=el('div');toolbar.className='workroom-sheet-toolbar';
    const stageBadge=el('span');stageBadge.className='workroom-sheet-stage';
    const close=el('button','Close card');close.type='button';close.addEventListener('click',()=>{if(!busy)closeDetails();});toolbar.append(stageBadge,close);details.append(toolbar);
    details.append(content,actionBar);
    const dialogStatus=el('p');dialogStatus.setAttribute('role','status');content.append(dialogStatus);
    const memoryState=el('p');memoryState.className='workroom-memory-state';memoryState.setAttribute('role','status');
    paintMemoryState(memoryState,opened.memorySync);content.append(memoryState);
    const cardNotice=el('p');cardNotice.setAttribute('role','status');content.append(cardNotice);
    const title=el('h2'),writeup=el('p'),flowNote=el('div');
    writeup.className='workroom-writeup';content.append(title,writeup,flowNote);
    const summary=el('section');summary.className='workroom-card-summary';content.append(summary);
    const edit=el('button','Edit card');edit.type='button';toolbar.insertBefore(edit,close);
    finishAction=el('button','Move to Done');finishAction.type='button';
    finishAction.addEventListener('click',()=>act(async()=>{await move(actionTask,'done');closeDetails();}));
    let summaryKey;
    function paintSummary(task){
      const {workroom,progress,flow}=task;
      const key=JSON.stringify([task.title,task.description,workroom.project,workroom.owner,workroom.stage,progress,
        flow?.question,flow?.askedAt,flow?.state,flow?.ownerNote,Boolean(teamPolicy?.simpleFlow)]);
      if(key===summaryKey)return;
      summaryKey=key;
      const stageName=teamPolicy?.simpleFlow&&['working','needs_you'].includes(workroom.stage)?'In progress':stages.find(stage=>stage[0]===workroom.stage)?.[1]||'Unknown';
      stageBadge.textContent=(workroom.stage==='done'?'✓ ':'')+stageName.toUpperCase();
      stageBadge.setAttribute('aria-label','Card status: '+stageName);
      title.textContent=task.title;writeup.textContent=task.description;
      flowNote.replaceChildren();
      if(flow?.state==='clarification')flowNote.append(el('h3','Clarification requested · '+new Date(flow.askedAt).toLocaleString()),el('p',flow.question));
      if(teamPolicy?.simpleFlow&&flow?.ownerNote)flowNote.append(el('h3','Your requested changes'),el('p',flow.ownerNote));
      flowNote.hidden=!flowNote.childElementCount;
      summary.replaceChildren(el('p',`${workroom.project||'No project'} · ${workroom.owner||'Unassigned'} · ${stageName}`),el('h3','Goal'),el('p',progress.goal||'No goal saved yet.'));
      const checklist=el('ul');
      for(const step of progress.checklist)checklist.append(el('li',`${step.status==='done'?'✓':step.status==='working'?'→':'○'} ${step.text} — ${step.status}`));
      summary.append(checklist,el('h3','Result'),el('p',progress.result||'No result recorded yet.'),el('p',teamPolicy?.simpleFlow?(workroom.stage==='done'?'Independent checks passed. Your acceptance is separate.':'Team verification: '+progress.decision):'Review: '+progress.decision));
      finishAction.disabled=progress.decision!=='approved';
      if(workroom.stage!=='done'&&finishAction.disabled&&!teamPolicy?.simpleFlow)summary.append(el('p','Record an approved review before moving this card to Done.'));
    }
    paintSummary(selected);
    const advanced=el('details');advanced.className='workroom-advanced-controls';advanced.open=!teamPolicy?.simpleFlow;advanced.append(el('summary','Advanced controls and history'));content.append(advanced);
    const timeline=el('section');timeline.className='workroom-timeline';advanced.append(timeline);
    let timelineSignature='';
    function paintTimeline(task){
      const events=taskTimeline(task),signature=JSON.stringify(events);if(signature===timelineSignature)return;timelineSignature=signature;
      timeline.replaceChildren(el('h3','Work timeline'));
      if(!events.length){timeline.append(el('p','No agent work has been sent. Saving or moving a card does not start an agent.'));return;}
      const list=el('ol');for(const event of events){const item=el('li');const when=el('time',Number.isFinite(Date.parse(event.at))?new Date(event.at).toLocaleString():'Time unavailable');if(Number.isFinite(Date.parse(event.at)))when.dateTime=new Date(event.at).toISOString();item.append(el('b',event.label),when);if(event.evidence||event.detail.length>180){const evidence=el('details');evidence.append(el('summary','Details and verification evidence'),el('p',event.detail));if(event.evidence)evidence.append(el('p',event.evidence));item.append(evidence);}else item.append(el('p',event.detail));list.append(item);}timeline.append(list);
    }
    paintTimeline(selected);
    const editor=el('section');editor.hidden=true;
    edit.addEventListener('click',()=>{
      const answering=cardNextAction(actionTask,Boolean(teamPolicy?.simpleFlow))==='clarify';
      beginEdit(actionTask);summary.hidden=true;editor.hidden=false;renderActions(actionTask);
      if(answering){
        goal.focus();
        goal.setSelectionRange(goal.value.length,goal.value.length);
      }else editor.querySelector('input')?.focus();
    });
    const cancel=el('button','Cancel edits');cancel.type='button';cancel.addEventListener('click',()=>{if(!busy)closeDetails();});content.append(editor);
    const reports=el('section');reports.className='agent-reports';(teamPolicy?.simpleFlow?advanced:content).append(reports);
    let reportSignature=null;
    function paintReports(task){
      const latest=task.agentUpdates?.at(-1);
      const signature=JSON.stringify([task.revision,task.workroom.revision,task.progress.revision,task.plan?.revision,latest?.hash,latest?.applied,task.progress.decision,task.agentReviews?.at(-1)?.hash,task.agentReviews?.at(-1)?.applied,task.assignments?.map(a=>a.hash)]);
      if(signature===reportSignature)return;
      reportSignature=signature;
      recordAction=null;reviewAnchor=null;
      reports.replaceChildren(el('h3','Agent-reported updates'));
      for(const offer of task.assignments||[]){
        const p=offer.proposal,box=el('details');box.append(el('summary','Lead assignment proposal · '+offer.agentId),el('p',p.spec),el('p','Workspace: '+p.workspace),el('p','Allowed files: '+p.allowedFiles),el('p','Checks: '+p.checks),el('p','Builder: '+p.workerId+' · Reviewer: '+p.reviewerId));
        const apply=el('button','Use proposed scope and team');apply.type='button';apply.disabled=task.status==='done'||task.progress.decision==='approved';apply.addEventListener('click',()=>act(async()=>{if(!editor.hidden)throw new Error('Save or cancel card edits first.');await request('/api/workroom/'+id+'/apply-assignment',{method:'POST',body:JSON.stringify({sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,revision:task.plan?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision})});await load();await open(id);}));box.append(apply);reports.append(box);
      }
      if(!latest){reports.append(el('p','No structured update yet. New task messages request a plan or progress report.'));}
      else{
        reports.append(el('p',`${latest.agentId} · ${latest.applied?'Applied · review: '+task.progress.decision:'Unreviewed report'}`),el('b',latest.update.goal));
        const list=el('ul');for(const step of latest.update.checklist)list.append(el('li',`${step.status} · ${step.text}`));reports.append(list);
        if(latest.update.result)reports.append(el('p','Reported result: '+latest.update.result));
        if(latest.update.evidence)reports.append(el('p','Reported evidence: '+latest.update.evidence));
        if(!latest.applied){
          const apply=el('button','Apply update to checklist');apply.type='button';
          apply.disabled=task.status==='done'||task.progress.decision==='approved';
          if(apply.disabled)reports.append(el('p','This card is completed or approved. This update cannot replace its saved checklist.'));
          apply.addEventListener('click',()=>act(async()=>{
            if(!editor.hidden)throw new Error('Save or cancel your edits before applying an agent update.');
            await request('/api/workroom/'+id+'/apply-update',{method:'POST',body:JSON.stringify({sendId:latest.sendId,messageId:latest.messageId,hash:latest.hash,
              revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision})});
            await load();await open(id);status.textContent='Agent update applied. The result still needs review.';
          }));reports.append(apply);
        }
      }
      const review=task.agentReviews?.at(-1);
      if(review){
        reviewAnchor=el('h3','Independent review');
        reports.append(reviewAnchor,el('p',`${review.agentId} · ${review.review.verdict}${review.applied?' · recorded':''}`),el('p',review.review.summary),el('p','Review evidence: '+review.review.evidence));
        if(!review.applied){const record=el('button','Record this review');recordAction=record;record.type='button';record.addEventListener('click',()=>act(async()=>{
          if(!editor.hidden)throw new Error('Save or cancel your edits before recording a review.');
          await request('/api/workroom/'+id+'/apply-review',{method:'POST',body:JSON.stringify({sendId:review.sendId,messageId:review.messageId,hash:review.hash,
            revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision})});
          await load();await open(id);status.textContent='Independent review recorded. Move to Done only when approved.';
        }));reports.append(record);}
      }
    }
    paintReports(selected);
    const form=el('form');
    const project=field(form,'Project',selected.workroom.project);
    const criteria=field(form,'Acceptance criteria',selected.workroom.criteria,true);
    const ownerLabel=el('label','Project lead');const owner=el('select');owner.setAttribute('aria-label','Project lead');
    for(const [value,name] of [['','Choose a project lead'],['nims','Nims (Codex)'],['echo','Echo'],...(!['','nims','echo'].includes(selected.workroom.owner)?[[selected.workroom.owner,'Existing owner: '+selected.workroom.owner]]:[])]){const option=el('option',name);option.value=value;owner.append(option);}
    owner.value=selected.workroom.owner;ownerLabel.append(owner);form.append(ownerLabel);
    const stageLabel=el('label','Board stage');const stage=el('select');
    for(const [value,label] of stages){const option=el('option',label);option.value=value;stage.append(option);}stage.value=selected.workroom.stage;stageLabel.append(stage);form.append(stageLabel);
    form.append(el('p','Your lead plans and scopes the job, then recommends builders and an independent reviewer. Available workers depend on connected, qualified adapters. Choosing a lead does not launch work.'));
    const save=el('button','Save changes');save.type='button';save.addEventListener('click',()=>act(()=>saveCard()));
    form.addEventListener('submit',event=>{event.preventDefault();act(()=>saveCard());});editor.append(form);
    const plan=el('details');plan.open=true;
    plan.append(el('summary','Checklist and verification details'));
    plan.open=!teamPolicy?.simpleFlow;
    plan.append(el('p','These are saved task updates. Checklist changes are recorded here; they are not inferred from an agent conversation.'));
    const progressForm=el('form');
    const goal=field(progressForm,'Goal',selected.progress.goal,true);
    if(teamPolicy?.simpleFlow)form.append(goal.parentElement);
    goal.maxLength=2000;
    const stepList=el('div');progressForm.append(stepList);
    const steps=selected.progress.checklist.map(step=>({...step}));
    function drawSteps(){
      stepList.replaceChildren();
      for(const step of steps){
        const row=el('div');
        const label=el('label','Step');const input=el('input');input.value=step.text;input.maxLength=300;
        input.addEventListener('input',()=>{step.text=input.value;});label.append(input);
        const state=el('select');state.setAttribute('aria-label','Status for '+step.text);
        for(const [value,name] of [['pending','Pending'],['working','Working'],['done','Done'],['blocked','Blocked']]){const option=el('option',name);option.value=value;state.append(option);}
        state.value=step.status;state.addEventListener('change',()=>{step.status=state.value;});
        const remove=el('button','Remove step');remove.type='button';remove.addEventListener('click',()=>{steps.splice(steps.indexOf(step),1);drawSteps();});
        row.append(label,state,remove);stepList.append(row);
      }
    }
    drawSteps();
    const add=el('button','Add checklist step');add.type='button';add.addEventListener('click',()=>{if(steps.length<30){steps.push({id:crypto.randomUUID(),text:'',status:'pending'});drawSteps();}});progressForm.append(add);
    const result=field(progressForm,'Result summary',selected.progress.result,true);
    const evidence=field(progressForm,'Verification evidence',selected.progress.evidence,true);
    const reviewer=field(progressForm,'Reviewed by',selected.progress.reviewer);
    const reviewStatus=el('p',`Review: ${selected.progress.decision==='stale'?'Needs a new review because the brief changed':selected.progress.decision}. Checking every step does not finish the task.`);
    progressForm.append(reviewStatus);
    function beginEdit(task){
      preserveDraft=true;
      if(selected.revision===task.revision&&selected.workroom.revision===task.workroom.revision&&selected.progress.revision===task.progress.revision)return;
      selected=task;
      project.value=task.workroom.project;criteria.value=task.workroom.criteria;stage.value=task.workroom.stage;
      if(task.workroom.owner&&!Array.from(owner.options).some(option=>option.value===task.workroom.owner))owner.add(new Option('Existing owner: '+task.workroom.owner,task.workroom.owner));
      owner.value=task.workroom.owner;
      goal.value=task.progress.goal;result.value=task.progress.result;evidence.value=task.progress.evidence;reviewer.value=task.progress.reviewer;
      steps.splice(0,steps.length,...task.progress.checklist.map(step=>({...step})));drawSteps();
      reviewStatus.textContent='Review: '+task.progress.decision;
    }
    async function saveEditedFields(progress){
      const body={project:project.value,criteria:criteria.value,owner:owner.value,stage:stage.value,team:'local_build',revision:selected.workroom.revision};
      selected=await saveCardBrief(selected,body,request,progress);
    }
    async function saveCard(){
      const answering=teamPolicy?.simpleFlow&&selected.flow?.state==='clarification';
      const changed=goal.value!==selected.progress.goal || JSON.stringify(steps)!==JSON.stringify(selected.progress.checklist) || result.value!==selected.progress.result || evidence.value!==selected.progress.evidence || reviewer.value!==selected.progress.reviewer;
      if(changed){await persist('pending',answering);return;}
      await saveEditedFields();
      await finishSave(teamPolicy?.simpleFlow?'Request saved.':'Card saved. No agent was started.',answering);
    }
    async function finishSave(message,answering){
      await load();closeDetails();
      const state=answering&&tasks.find(task=>task.id===id)?.flow?.state;
      if(state==='clarification')message='The question is still open. Update the goal or acceptance criteria to answer it.';
      if(state==='queued')message='Answer saved. The updated request is queued for another look.';
      status.textContent=message;
    }
    async function persist(decision,answering=false){
      await saveEditedFields({goal:goal.value,checklist:steps,
        result:result.value,evidence:evidence.value,reviewer:reviewer.value,decision,revision:selected.progress.revision,
        taskRevision:selected.revision,briefRevision:selected.workroom.revision});
      await finishSave(decision==='approved'?'Review approved and saved. You can now move this task to Done.':decision==='changes_requested'?'Changes requested. The task remains open.':'Goal and checklist saved.',answering);
    }
    progressForm.addEventListener('submit',event=>{event.preventDefault();act(()=>saveCard());});
    const approve=el('button','Record approved review');approve.type='button';approve.addEventListener('click',()=>act(()=>persist('approved')));
    const changes=el('button','Request changes');changes.type='button';changes.addEventListener('click',()=>act(()=>persist('changes_requested')));
    progressForm.append(approve,changes);plan.append(progressForm);editor.append(plan);
    const conversation=el('details');conversation.append(el('summary','Conversation and history'));content.append(conversation);
    const messageForm=el('form');messageForm.append(el('h3','Task conversation'));
    const destination=el('select');destination.setAttribute('aria-label','Agent for this task message');
    try{agents=await request('/api/relay/native/api/agents');}catch{agents=[];}
    if(epoch!==viewEpoch)return;
    for(const agent of agents.filter(agent=>agent.conversation_id && ['hermes','a2a'].includes(agent.backend))){const option=el('option',agent.name||agent.id);option.value=agent.id;destination.append(option);}
    const team=el('section');team.className='agent-reports';team.append(el('h3','Team handoffs'));
    const recovery=el('section');recovery.setAttribute('aria-label','Handoff status');team.append(recovery);
    function paintRecovery(){
      recovery.replaceChildren();const signal=handoffStatus(selected,agents);if(!signal)return;
      const latest=selected.messages.filter(m=>['plan','work','review'].includes(m.phase)).at(-1);
      recovery.append(el('b',signal.label),el('p',signal.next));
      if(recoveredHandoff(latest)){
        recovery.append(el('small','Recovery recorded '+new Date(latest.legacyRecovery.recordedAt).toLocaleString()));
        return;
      }
      recovery.append(el('small',`Last handoff: ${new Date(latest.at).toLocaleString()} · Status checked: ${new Date().toLocaleTimeString()}`));
      if(latest.outcome)recovery.append(el('small',`Native outcome verified: ${new Date(latest.outcome.verifiedAt).toLocaleString()}`));
      const relayButton=el('button','Open Relay');relayButton.type='button';relayButton.addEventListener('click',()=>{closeDetails();document.getElementById('tab-relay').click();});recovery.append(relayButton);
    }
    paintRecovery();
    if(selected.messages.some(message=>message.agentId==='dsh' && message.state==='accepted' && !message.outcome && !recoveredHandoff(message))){
      const permissionPanel=el('section');permissionPanel.className='agent-reports';
      const permissionStatus=el('p','If DeepSeek is waiting for permission, inspect the exact request here.');permissionStatus.setAttribute('role','status');
      const permissionBody=el('div');
      const inspectPermission=el('button','Check DeepSeek approval');inspectPermission.type='button';
      permissionPanel.append(el('h3','DeepSeek permissions'),permissionStatus,inspectPermission,permissionBody);team.append(permissionPanel);
      inspectPermission.addEventListener('click',()=>act(async()=>{
        if(!editor.hidden)throw new Error('Save or cancel edits before inspecting an approval.');
        permissionBody.replaceChildren();permissionStatus.textContent='Checking the existing request…';
        const state=await request('/api/workroom/'+id+'/approval');
        if(epoch!==viewEpoch || !details.open)return;
        if(state.task){selected={...selected,messages:state.task.messages,replies:state.task.replies,agentUpdates:state.task.agentUpdates,agentReviews:state.task.agentReviews,worker:state.task.worker};paintReports(state.task);paintReplies(state.task);paintTimeline(state.task);if(followLabel.parentElement!==reports)reports.append(followLabel,liveStatus);}
        const permission=state.pending;
        if(!permission){permissionStatus.textContent=state.reason||'No active approval was exposed for this task. Refresh agent replies to check its result.';return;}
        permissionStatus.textContent=permission.canApprove?'Inspect the full tool and arguments before choosing. Allow once grants only this request.':'Exact arguments are unavailable or the task changed. You can deny this request; allowing it is disabled.';
        const argumentsView=el('pre',permission.arguments===null?'Exact arguments unavailable.':permission.arguments);argumentsView.style.whiteSpace='pre-wrap';argumentsView.style.overflowWrap='anywhere';
        permissionBody.append(el('b',permission.toolName),el('p',permission.reason),argumentsView,el('small',`Request: ${permission.requestId}`));
        const allow=el('button','Allow this tool once');allow.type='button';allow.disabled=!permission.canApprove;
        const deny=el('button','Deny this request');deny.type='button';
        for(const [button,decision] of [[allow,'allow_once'],[deny,'reject']])button.addEventListener('click',()=>act(async()=>{
          allow.disabled=true;deny.disabled=true;permissionStatus.textContent='Submitting this exact decision. If interrupted, check the request again before taking another action.';
          const receipt=await request('/api/workroom/'+id+'/approval',{method:'POST',body:JSON.stringify({sendId:state.sendId,requestId:permission.requestId,decision})});
          if(epoch!==viewEpoch || !details.open)return;
          await load();await open(id);
          const notice=receipt.decisionStatus==='unconfirmed'?'Decision not yet confirmed. Check DeepSeek approval again before taking another action; do not send a new copy.':'Decision recorded. Any tool result or review still needs inspection.';
          status.textContent=notice;const dialogNotice=details.querySelector('[role="status"]');if(dialogNotice)dialogNotice.textContent=notice;
        }));
        permissionBody.append(allow,deny);
      }));
    }
    const workerLabel=el('label','Worker');const workerAgent=el('select');workerAgent.setAttribute('aria-label','Worker agent');workerLabel.append(workerAgent);
    const reviewerLabel=el('label','Reviewer');const reviewerAgent=el('select');reviewerAgent.setAttribute('aria-label','Reviewer agent');reviewerLabel.append(reviewerAgent);
    for(const agent of agents.filter(agent=>agent.conversation_id && ['hermes','a2a','codex'].includes(agent.backend))){
      for(const select of [workerAgent,reviewerAgent]){if(select===workerAgent&&agent.backend==='codex')continue;const option=el('option',`${agent.name||agent.id} · ${agent.status}`);option.value=agent.id;select.append(option);}
    }
    workerAgent.value=Array.from(workerAgent.options).some(option=>option.value===selected.workroom.owner)?selected.workroom.owner:workerAgent.value;
    reviewerAgent.value=agents.find(agent=>agent.id==='dsh' && agent.id!==workerAgent.value)?.id||agents.find(agent=>agent.id!==workerAgent.value && ['hermes','a2a'].includes(agent.backend))?.id||reviewerAgent.value;
    const planEditor=(selected.plan||['nims','echo'].includes(selected.workroom.owner))?createPlanEditor({task:selected,agents,document,onSave:body=>act(async()=>{
      if(!editor.hidden)throw new Error('Save or cancel card edits before saving its plan.');
      await request('/api/workroom/'+id+'/plan',{method:'PATCH',body:JSON.stringify(body)});
      await load();await open(id);status.textContent=body.state==='locked'?'Scope and team locked. No agent started.':'Plan proposal saved. Work is not started.';
    })}):null;
    if(planEditor)team.append(planEditor.node);
    if(selected.plan?.state==='locked'){
      workerAgent.value=selected.plan.workerId;reviewerAgent.value=selected.plan.reviewerId;
      workerAgent.disabled=true;reviewerAgent.disabled=true;
    }
    team.append(workerLabel,reviewerLabel,el('p','Each button sends one task message. Worker results and independent reviews return here; recording a review is a separate action.'));
    team.append(el('p','Lead flow: clarify → proposed plan/spec → scope locked with you → choose builder → independent review. Use Start scoped team below for the bounded automatic build/review cycle; individual handoffs remain available.'));
    if(selected.workroom.owner==='nims'&&!agents.some(a=>a.id==='nims'&&a.conversation_id)){
      const brief=el('details');brief.append(el('summary','Planning brief for Nims'));
      brief.append(el('p','Nims is not connected as a Mesh executor. Copy this into your Nims chat to continue planning.'));
      const text=el('textarea');text.readOnly=true;text.rows=10;text.setAttribute('aria-label','Nims planning brief');text.value=nimsPlanningBrief(selected);brief.append(text);team.append(brief);
    }
    const handoffHistory=selected.messages.filter(message=>['plan','work','review'].includes(message.phase));
    for(const message of handoffHistory.slice(-3))team.append(el('p',`${message.phase} → ${message.agentId} · ${handoffDisplayState(message)}`));
    const pendingHandoffs=new Map(),handoffButtons=new Map();
    for(const [phase,label] of [['plan','Ask for a plan · no edits'],['work','Prepare worker request'],['review','Request independent review']]){
      const button=el('button',phase==='plan'&&['echo','nims'].includes(selected.workroom.owner)?'Ask '+(selected.workroom.owner==='nims'?'Nims':'Echo')+' to plan · no edits':label);button.type='button';button.disabled=(phase==='plan'?(!agents.some(a=>a.id===selected.workroom.owner&&a.conversation_id)&&!workerAgent.options.length):!workerAgent.options.length)||selected.status==='done'||selected.progress.decision==='approved'||(phase==='plan'&&selected.workroom.owner==='nims'&&!agents.some(a=>a.id==='nims'&&a.conversation_id))||(phase!=='plan'&&selected.plan&&selected.plan.state!=='locked')||(phase==='review'&&(!selected.worker||!selected.progress.result.trim()||!selected.progress.evidence.trim()||selected.progress.checklist.some(step=>step.status!=='done')));
      const dispatch=()=>act(async()=>{
        if(teamRequestNotice(teamPolicy))throw new Error(teamRequestNotice(teamPolicy));
        if(!editor.hidden)throw new Error('Save or cancel edits before sending a handoff.');
        if(planEditor?.isDirty())throw new Error('Save or lock the plan changes before sending a handoff.');
        const choice=phase==='review'?reviewerAgent:workerAgent;const agent=agents.find(agent=>agent.id===(phase==='plan'&&['echo','nims'].includes(selected.workroom.owner)?selected.workroom.owner:choice.value));
        if(!agent)throw new Error('Choose an available agent.');
        let body=pendingHandoffs.get(phase);
        if(body && body.agentId!==agent.id)throw new Error('Retry the existing handoff to its original agent before changing agents.');
        if(!body){body={id:crypto.randomUUID(),agentId:agent.id,conversationId:agent.conversation_id,phase};pendingHandoffs.set(phase,body);}
        await request('/api/workroom/'+id+'/handoff',{method:'POST',body:JSON.stringify(body)});
        pendingHandoffs.delete(phase);await load();await open(id);status.textContent=`${phase} handoff accepted. Acceptance is not completion.`;
      });
      handoffButtons.set(button,button.disabled);
      if(phase==='work')button.addEventListener('click',()=>{
        if(teamRequestNotice(teamPolicy)){dialogStatus.textContent=teamRequestNotice(teamPolicy);return;}
        if(!editor.hidden){dialogStatus.textContent='Save or cancel edits before preparing worker execution.';return;}
        if(planEditor?.isDirty()){dialogStatus.textContent='Save or lock the plan changes before preparing worker execution.';return;}
        team.querySelector('.worker-preview')?.remove();
        const preview=el('section');preview.className='worker-preview';const chosen=workerAgent.value;
        preview.append(el('h4','Start work on '+selected.title+'?'),el('p','Worker: '+chosen+'. This can edit the workspace named in your saved brief.'),el('p','Goal: '+(selected.progress.goal||'No goal saved.')),el('p','Acceptance: '+(selected.workroom.criteria||'No acceptance criteria saved.')));
        if(selected.plan)preview.append(el('p','Locked workspace: '+selected.plan.workspace),el('p','Allowed files: '+selected.plan.allowedFiles),el('p','Checks: '+selected.plan.checks));
        const confirm=el('button','Start this worker');confirm.type='button';confirm.addEventListener('click',()=>{if(workerAgent.value!==chosen){preview.remove();dialogStatus.textContent='Worker changed. Prepare the request again.';return;}dispatch();});
        const cancelStart=el('button','Cancel request');cancelStart.type='button';cancelStart.addEventListener('click',()=>preview.remove());preview.append(confirm,cancelStart);team.append(preview);
      });else button.addEventListener('click',dispatch);
      team.append(button);
    }
    let paintAuto=()=>{},paintScopedAvailability=()=>{};
    if(selected.plan){
      const auto=el('section'),completion=el('p');
      auto.append(el('h3','Automatic scoped team'),completion);
      const teamState=el('p'),qualification=el('p'),recheck=el('button','Check connections');
      recheck.type='button';recheck.hidden=true;
      recheck.addEventListener('click',()=>act(load));
      auto.append(qualification,recheck,teamState);let visible=selected;const buttons=new Map(),originalPlanRevision=selected.plan.revision;
      for(const [action,label] of [['start','Start scoped team'],['resume','Resume saved team'],['pause','Pause next team steps'],['close','Close saved team attempt']]){
        const b=el('button',label);b.type='button';buttons.set(action,b);b.addEventListener('click',()=>act(async()=>{
          if(!editor.hidden||planEditor?.isDirty())throw new Error('Save or cancel edits before team actions.');
          const basis={revision:visible.automation?.revision??0,planRevision:visible.plan.revision,taskRevision:visible.revision,briefRevision:visible.workroom.revision,progressRevision:visible.progress.revision};
          await request('/api/workroom/'+id+'/automation',{method:'POST',body:JSON.stringify({action,...basis})});await load();await open(id);
        }));auto.append(b);
      }
      paintScopedAvailability=()=>{const task=visible,state=task.automation?.state,changed=task.plan?.revision!==originalPlanRevision;
        const locked=!changed&&task.plan?.state==='locked';
        const canResume=locked&&state==='paused';
        const canStart=locked&&!['active','paused','needs_review'].includes(state)&&task.status!=='done'&&task.progress.decision!=='approved';
        const peers=agentsKnown?agents:null;
        const qualified=scopedTeamStatus(task.plan,teamPolicy,canStart||canResume?peers:undefined);qualification.textContent=qualified.message;
        recheck.hidden=!qualified.recheck;
        completion.textContent=teamPolicy?.simpleFlow
          ? 'After the builder finishes, an independent reviewer checks the work. An approved result moves to Done for your acceptance. Pausing stops the next step; accepted work can continue.'
          : 'After the builder finishes, inspect the independent review. Record the review, then move the card to Done when approved. Pausing stops the next step; accepted work can continue.';
        buttons.get('resume').disabled=!qualified.matches||!canResume;
        buttons.get('start').disabled=!qualified.matches||!canStart;
      };
      paintAuto=task=>{visible=task;const state=task.automation?.state,changed=task.plan?.revision!==originalPlanRevision;
        teamState.textContent='Team: '+(state||'not started')+' · '+(task.automation?.reason||'One build → one review, no automatic rework loop.')+(changed?' Scope changed; reopen this card before starting/resuming.':'');
        buttons.get('pause').disabled=state!=='active';buttons.get('close').disabled=!['paused','needs_review'].includes(state);
        paintScopedAvailability();
      };paintAuto(selected);team.append(auto);
    }
    if(teamPolicy?.simpleFlow){advanced.append(team,conversation);}else content.insertBefore(team,conversation);
    messageForm.append(destination);
    const compose=field(messageForm,'Message', '',true);
    const handoffs=el('div');handoffs.append(el('p','Local Build handoffs: prepare a message, choose an available agent, then send. You control each handoff.'));
    for(const [label,instruction] of [
      ['Prepare planning handoff','Plan this bounded task. Return a short checklist, acceptance checks, and any blocker. Do not edit files or start other agents.'],
      ['Prepare implementation handoff','Work only on the saved goal and checklist. Follow the repository instructions. Return the changed files, checks actually run, result and blockers. Do not purchase, publish, push or change credentials. If repository access is unavailable, report it; do not claim completion.'],
      ['Prepare review handoff','Review the implementation and evidence for this task. Check the actual changes if you have repository access. Return APPROVED or CHANGES REQUESTED with reasons and checks actually run. Do not treat checked boxes or an agent summary as proof. If evidence is missing, request it.']
    ]){const button=el('button',label);button.type='button';button.addEventListener('click',()=>{compose.value=instruction;compose.focus();});handoffs.append(button);}
    messageForm.append(handoffs);
    const send=el('button','Send in this task');send.type='submit';
    // Keep the task gate independent of the app's session-wide form lock.
    const sendGate=el('fieldset');sendGate.className='workroom-send-gate';sendGate.append(send);
    const sendHelp=el('p');messageForm.append(sendGate,sendHelp);
    paintCardPolicy=()=>{
      const notice=teamRequestNotice(teamPolicy);
      cardNotice.textContent=notice;cardNotice.hidden=!notice;
      sendGate.disabled=Boolean(notice)||!destination.options.length;
      sendHelp.textContent=notice?'Sending is paused. You can keep drafting here.':
        destination.options.length?'Accepted messages are queued by Relay.':'No connected agent is available for this task message.';
      for(const [button,unavailable] of handoffButtons)button.disabled=unavailable||Boolean(notice);
      if(notice)team.querySelector('.worker-preview')?.remove();
      paintScopedAvailability();
    };
    paintCardPolicy();
    const unresolved=selected.messages.filter(message=>['unknown','prepared'].includes(message.state));
    for(const message of unresolved){
      const retry=el('button',`Retry uncertain message to ${message.agentId}`);retry.type='button';
      retry.addEventListener('click',()=>{pending={id:message.id,agentId:message.agentId,conversationId:message.conversationId,text:message.text,phase:message.phase};compose.value=message.text;destination.value=message.agentId;status.textContent='Original message selected. Send retries the same message identity.';});
      messageForm.append(retry);
    }
    messageForm.addEventListener('submit',event=>{event.preventDefault();if(teamRequestNotice(teamPolicy))return;act(async()=>{
      const agent=agents.find(agent=>agent.id===destination.value);
      if(!agent)throw new Error('Refresh and choose an available agent.');
      if(pending && (pending.text!==compose.value || pending.agentId!==agent.id))throw new Error('Retry the original message unchanged before sending a new one.');
      pending??={id:crypto.randomUUID(),agentId:agent.id,conversationId:agent.conversation_id,text:compose.value};
      const handoff=['plan','work','review'].includes(pending.phase);
      const body=handoff?{id:pending.id,agentId:pending.agentId,conversationId:pending.conversationId,phase:pending.phase}:{id:pending.id,agentId:pending.agentId,conversationId:pending.conversationId,text:pending.text};
      const result=await request('/api/workroom/'+id+(handoff?'/handoff':'/message'),{method:'POST',body:JSON.stringify(body)});
      pending=null;await load();await open(id);status.textContent=result.duplicate?'Existing send confirmed; no new task created.':'Message accepted by Relay and attached to this task.';
    });});
    conversation.append(messageForm,el('h3','Saved messages'));
    const savedMessages=el('div');conversation.append(savedMessages);
    function paintSavedMessages(task){
      savedMessages.replaceChildren();
      for(const message of task.messages||[]){
        const item=el('article');item.append(el('p',`${message.agentId} · ${handoffDisplayState(message)} · ${message.text}`));
        const worker=nativeWorkerStatus(message);
        if(worker){item.append(el('strong',worker.label),el('p',worker.next));
          const checked=message.nativeReceipt.lastCheckedAt;
          if(typeof checked==='string'&&Number.isFinite(Date.parse(checked)))item.append(el('small','Last checked '+new Date(checked).toLocaleString()));}
        savedMessages.append(item);
      }
    }
    paintSavedMessages(selected);
    const replies=el('section');replies.append(el('h3','Agent replies'));
    const replyStatus=el('p');const replyList=el('div');const sync=el('button','Refresh agent replies');sync.type='button';
    function paintReplies(task){replyList.replaceChildren();for(const reply of task.replies||[]){const item=el('article');item.append(el('b',reply.agentId),el('p',reply.text));replyList.append(item);}if(!task.replies?.length)replyList.append(el('p','No saved replies yet.'));}
    paintReplies(selected);
    const followLabel=el('label');const follow=el('input');follow.type='checkbox';follow.checked=true;followLabel.append(follow,document.createTextNode(' Follow agent replies while this card is open'));reports.append(followLabel);
    const liveStatus=el('p');liveStatus.setAttribute('role','status');reports.append(liveStatus);
    let refreshVersion=0;
    async function refreshCard({replies=false,background=false}={}){
      const version=++refreshVersion;
      const current=()=>version===refreshVersion&&epoch===viewEpoch&&details.open&&editor.hidden&&ownerPanel.hidden&&!(background&&busy);
      const response=replies
        ?await request('/api/workroom/'+id+'/sync',{method:'POST',body:'{}'})
        :await request('/api/workroom/'+id);
      if(!current())return;
      if(replies){
        let peers;
        try{peers=await request('/api/relay/native/api/agents');}catch{peers=[];}
        if(!current())return;
        agents=peers;
      }else{
        teamPolicy=response.teamPolicy||null;paintMaintenance();
      }
      const task=response.task;
      selected={...selected,messages:task.messages,replies:task.replies,agentUpdates:task.agentUpdates,agentReviews:task.agentReviews,worker:task.worker};
      paintSummary(task);paintRecovery();paintMemoryState(memoryState,response.memorySync);
      paintSavedMessages(task);paintReplies(task);paintReports(task);paintTimeline(task);paintAuto(task);renderActions(task);
      if(followLabel.parentElement!==reports)reports.append(followLabel,liveStatus);
      const index=tasks.findIndex(item=>item.id===id);if(index>=0){tasks[index]=task;draw();}
      const message=replies?'Replies checked':'Saved progress checked';
      liveStatus.textContent=message+' '+new Date().toLocaleTimeString()+'.';
      if(!replies)dialogStatus.textContent=liveStatus.textContent;
    }
    sync.addEventListener('click',()=>act(async()=>{await refreshCard({replies:true});replyStatus.textContent='Replies refreshed and saved.';}));
    async function followReplies(){
      if(epoch!==viewEpoch || !details.open)return;
      if(follow.checked && !document.hidden && editor.hidden && !busy && selected.messages.some(message=>message.state==='accepted')){
        try{await refreshCard({replies:true,background:true});}catch(error){if(epoch===viewEpoch)liveStatus.textContent='Live replies paused: '+error.message;}
      }
      if(epoch===viewEpoch && details.open)followTimer=setTimeout(followReplies,7000);
    }
    replies.append(sync,replyStatus,replyList);conversation.append(replies);
    conversation.append(el('h3','Task history'));
    for(const entry of selected.history)conversation.append(el('p',`${entry.at} · ${entry.detail}`));
    const inspectReview=el('button','Read review');inspectReview.type='button';inspectReview.addEventListener('click',()=>reviewAnchor?.scrollIntoView({block:'start'}));
    const checkProgress=el('button','Check progress');checkProgress.type='button';checkProgress.addEventListener('click',()=>act(()=>refreshCard()));
    const back=el('button','Back to board');back.type='button';back.addEventListener('click',()=>{if(!busy)closeDetails();});
    const ownerPanel=el('section');ownerPanel.hidden=true;content.append(ownerPanel);
    const ownerNote=field(ownerPanel,'What needs to change?','',true);ownerNote.maxLength=2000;
    const sendOwnerReview=decision=>act(async()=>{const task=actionTask;await request('/api/workroom/'+id+'/owner-review',{method:'POST',body:JSON.stringify({decision,note:decision==='accepted'?'':ownerNote.value,revision:task.flow?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision})});await load();await open(id);});
    const acceptResult=el('button','Accept result');acceptResult.type='button';acceptResult.addEventListener('click',()=>sendOwnerReview('accepted'));
    const requestChanges=el('button','Request changes');requestChanges.type='button';requestChanges.addEventListener('click',()=>{ownerPanel.hidden=false;renderActions(actionTask);ownerNote.focus();});
    const submitChanges=el('button','Send changes to team');submitChanges.type='button';submitChanges.addEventListener('click',()=>sendOwnerReview('changes_requested'));
    const cancelOwner=el('button','Cancel');cancelOwner.type='button';cancelOwner.addEventListener('click',()=>{ownerPanel.hidden=true;renderActions(actionTask);});
    const startIdea=el('button','Work on this');startIdea.type='button';startIdea.addEventListener('click',()=>act(async()=>{await move(actionTask,'working');closeDetails();}));
    renderActions=task=>{
      actionTask=task;actionBar.replaceChildren();toolbar.insertBefore(edit,close);edit.hidden=!editor.hidden;
      edit.textContent='Edit card';
      let primary,secondary,note;
      if(!ownerPanel.hidden){primary=submitChanges;secondary=cancelOwner;note='Explain what should be different';}
      else if(!editor.hidden){primary=save;secondary=cancel;note='Editing card';}
      else{
        const next=cardNextAction(task,Boolean(teamPolicy?.simpleFlow));
        if(next==='owner_review'){primary=acceptResult;secondary=requestChanges;note='Finished · ready for your review';}
        else if(next==='clarify'){primary=edit;edit.textContent='Answer question';note='Add the missing detail to the goal or acceptance criteria.';}
        else if(next==='idea'){primary=startIdea;secondary=edit;note='Idea · send it to the team when ready';}
        else if(next==='close'){primary=back;note=teamPolicy?.simpleFlow?'Done · accepted by you':'Done · review recorded';}
        else if(next==='finish'&&finishAction){primary=finishAction;primary.disabled=false;secondary=reviewAnchor?inspectReview:null;note='Review recorded · ready to finish';}
        else if(next==='record'&&recordAction){primary=recordAction;secondary=inspectReview;note='Independent review: '+task.agentReviews.at(-1).review.verdict.replaceAll('_',' ');}
        else if(next==='progress'){primary=checkProgress;note=teamPolicy?.simpleFlow?(task.flow?.state==='queued'?'Queued · waiting for the assigned lead':task.flow?.state==='planning'?'Lead is reviewing the request':task.automation?.state==='paused'?'Team paused · check the saved blocker':task.automation?.state==='active'?(task.automation.phase==='reviewer'?'Independent review in progress':'Build in progress'):'Check the latest saved progress'):'Team working · completion still needs review';}
        else{primary=edit;note=task.progress.decision==='changes_requested'?'Changes requested · update and review again':'Edit the task or use its team tools below';}
      }
      const actionNote=el('p',note);actionNote.setAttribute('role','status');actionBar.append(actionNote);const row=el('div');row.className='workroom-sheet-action-row';if(secondary)row.append(secondary);primary.classList.add('workroom-primary-action');row.append(primary);actionBar.append(row);
    };
    renderActions(selected);
    if(!details.open)details.showModal();
    followTimer=setTimeout(followReplies,1000);
  }
  refresh.addEventListener('click',()=>act(load));
  window.addEventListener('mesh-open-task',event=>{
    if(typeof event.detail?.id==='string' && /^[0-9a-f-]{36}$/.test(event.detail.id))cardOpener.request(event.detail.id);
  });
  projectFilter.addEventListener('input',draw);
  document.getElementById('tab-workroom')?.addEventListener('click',()=>act(load));
  // Loading cards is read-only; a busy editor must not lose this notification.
  // The loader's epoch/read guards discard responses after a lock or newer read.
  window.addEventListener('mesh-tasks-refreshed',()=>{void load().catch(error=>{status.textContent=error.message;});});
  // Wait for admission and let an open editor keep its draft until the user closes it.
  function loadTaskLink(){
    if(window.meshWorkroom.linkedTask && !document.querySelector('dialog[open]')){
      void load().catch(error=>{status.textContent=error.message;});
    }
  }
  window.addEventListener('hashchange',loadTaskLink);
  document.addEventListener('close',loadTaskLink,true);
  loadTaskLink();
  if(location.hash==='#workroom')document.getElementById('tab-workroom')?.click();
}
