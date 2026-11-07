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
        sessionRelation:agent.conversation_id && latest.conversationId
          ? (latest.conversationId === agent.conversation_id ? 'matches observed session' : 'historical session')
          : 'session comparison unavailable',
        decision:task.progress?.decision || 'pending'}] : [];
    })
  }));
}

export function agentObservationLabel(snapshot) {
  const recorded = snapshot?.observedAt;
  const time = typeof recorded === 'string' && Number.isFinite(Date.parse(recorded)) ? recorded : null;
  return `${time ? 'Relay roster read at ' + time : 'Relay roster check time unavailable'}. Saved observation; refresh to check again. Agent status is separate from task completion.`;
}

export function agentAssignmentLabel(agentId, policy) {
  const valid = policy?.schema === 'mesh-team-policy/v1' &&
    typeof policy.workspace === 'string' && policy.workspace.trim() && policy.actionLimit === 50 &&
    [policy.builderIds, policy.reviewerIds].every(ids => Array.isArray(ids) && ids.every(id => typeof id === 'string' && id.trim()));
  if (!valid) return 'Scoped team roles unavailable. Refresh to check the server policy.';
  const roles = [];
  if (policy.builderIds.includes(agentId)) roles.push('builder');
  if (policy.reviewerIds.includes(agentId)) roles.push('reviewer');
  return roles.length
    ? `Configured team role: ${roles.join(' / ')}. Workspace: ${policy.workspace}. Limit: ${policy.actionLimit} actions. Connection, locked task scope and review checks still apply; this is not proof of current coding access.`
    : 'No automatic build or review role configured for this peer. Chat availability is separate.';
}

export function renderAgentWorkspace(root, snapshot, tasks, openTask, teamPolicy) {
  root.replaceChildren();
  const add = (parent, tag, text) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; };
  const rows = agentWorkspace(snapshot, tasks);
  if (!rows.length) add(root, 'p', snapshot?.error || 'No current agent observation. Refresh app status to reconnect. Saved tasks remain in Workroom.');
  else add(root, 'p', agentObservationLabel(snapshot));
  for (const row of rows) {
    const card = add(root, 'article', ''); card.className = 'box section-gap';
    add(card, 'h2', row.name);
    add(card, 'p', `${row.backend} · ${row.status}${row.approval ? ' · needs permission' : ''}`);
    add(card, 'p', row.session ? `Session: ${row.session}` : 'No active session reported.');
    add(card, 'p', 'Relay peer. Coding tools and repository access are not declared by this adapter; inspect a scoped task’s evidence.');
    add(card, 'p', agentAssignmentLabel(row.id, teamPolicy));
    if (tasks === undefined) add(card, 'p', 'Task receipts unavailable. Refresh to try again.');
    else if (!row.tasks.length) add(card, 'p', 'No saved Workroom handoff for this peer.');
    for (const task of row.tasks) {
      const button = add(card, 'button', task.title); button.type = 'button';
      button.addEventListener('click', () => openTask(task.id));
      add(card, 'p', `${task.phase || 'message'} · delivery ${task.delivery} · review ${task.decision} · ${task.sessionRelation}`);
    }
  }
}
