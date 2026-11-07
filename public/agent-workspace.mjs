// A projection of existing Relay identity and saved Workroom receipts, never a scheduler.
export function agentWorkspace(snapshot, tasks) {
  return (snapshot?.agents || []).map(agent => ({
    id: agent.id, name: agent.name || agent.id,
    backend: agent.backend || 'Backend not declared',
    status: agent.status || 'Unknown', session: agent.conversation_id || null,
    approval: Boolean(agent.approval),
    tasks: (tasks || []).flatMap(task => {
      const attempts = (task.messages || []).filter(send => send.agentId === agent.id);
      const latest = attempts.at(-1);
      return latest ? [{id:task.id, title:task.title, phase:latest.phase,
        delivery:latest.state, sameSession:Boolean(agent.conversation_id && latest.conversationId === agent.conversation_id),
        decision:task.progress?.decision || 'pending'}] : [];
    })
  }));
}

export function renderAgentWorkspace(root, snapshot, tasks, openTask) {
  root.replaceChildren();
  const add = (parent, tag, text) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; };
  const rows = agentWorkspace(snapshot, tasks);
  if (!rows.length) add(root, 'p', snapshot?.error || 'No current agent observation. Refresh app status to reconnect. Saved tasks remain in Workroom.');
  else add(root, 'p', 'Relay observation checked ' + new Date().toLocaleTimeString() + '. Agent status is separate from task completion. Refresh to check again.');
  for (const row of rows) {
    const card = add(root, 'article', ''); card.className = 'box section-gap';
    add(card, 'h2', row.name);
    add(card, 'p', `${row.backend} · ${row.status}${row.approval ? ' · needs permission' : ''}`);
    add(card, 'p', row.session ? `Session: ${row.session}` : 'No active session reported.');
    add(card, 'p', 'Relay peer. Coding tools and repository access are not declared by this adapter; inspect a scoped task’s evidence.');
    if (tasks === undefined) add(card, 'p', 'Task receipts unavailable. Refresh to try again.');
    else if (!row.tasks.length) add(card, 'p', 'No saved Workroom handoff for this peer.');
    for (const task of row.tasks) {
      const button = add(card, 'button', task.title); button.type = 'button';
      button.addEventListener('click', () => openTask(task.id));
      add(card, 'p', `${task.phase || 'message'} · delivery ${task.delivery} · review ${task.decision} · ${task.sameSession ? 'current session' : 'historical session'}`);
    }
  }
}
