import { readFileSync } from 'node:fs';

export class ProposalError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// This fixed file is the authority. No request, environment variable or task
// can supply a policy path. cwd '.' always denotes the application's repo root.
const config = JSON.parse(readFileSync(new URL('../config/commands.json', import.meta.url), 'utf8'));
if (Object.keys(config).join(',') !== 'commands' || !Array.isArray(config.commands) || !config.commands.length)
  throw new Error('Invalid command whitelist.');
const ids = new Set(); const commands = new Set();
const fixedChoices = config.commands.map(entry => {
  if (!entry || Object.keys(entry).sort().join(',') !== 'command,cwd,id' ||
      typeof entry.id !== 'string' || !/^[a-z][a-z0-9-]{0,63}$/.test(entry.id) || ids.has(entry.id) ||
      typeof entry.command !== 'string' || !entry.command || entry.command.length > 160 ||
      /[\u0000-\u001f]/u.test(entry.command) || commands.has(entry.command) || entry.cwd !== '.')
    throw new Error('Invalid command whitelist entry.');
  ids.add(entry.id); commands.add(entry.command);
  return Object.freeze({ id: entry.id, command: entry.command, cwd: entry.cwd });
});
export const commandChoices = Object.freeze(fixedChoices);
export const m3CommandChoice = fixedChoices.find(entry => entry.id === 'm3-slow');

export function validateProposal(proposal) {
  if (!proposal || typeof proposal !== 'object' || Array.isArray(proposal) ||
      Object.keys(proposal).sort().join(',') !== 'command,cwd')
    throw new ProposalError(400, 'Proposal must contain exactly command and cwd.');
  if (typeof proposal.command !== 'string' || !commands.has(proposal.command))
    throw new ProposalError(400, 'Choose an exact command from the server whitelist.');
  if (proposal.cwd !== '.')
    throw new ProposalError(400, 'cwd must be exactly "." (the fixed repository root).');
  return { command: proposal.command, cwd: proposal.cwd };
}

export function validateProposalRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body) ||
      Object.keys(body).sort().join(',') !== 'proposal,revision')
    throw new ProposalError(400, 'Provide exactly proposal and the current task revision.');
  if (!Number.isSafeInteger(body.revision) || body.revision < 1)
    throw new ProposalError(400, 'A valid current task revision is required.');
  return { proposal: validateProposal(body.proposal), revision: body.revision };
}
