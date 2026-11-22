import {openTaskStore} from '../../lib/task-store.mjs';
import {createRookRuntime} from '../../lib/workroom-rook.mjs';

// An IPC disconnect models process exit without a graceful Rook pause.
if (process.send) {
  process.once('disconnect', () => process.exit(0));
  const [, , filename, at] = process.argv;
  const {workroom} = openTaskStore(filename);
  const runtime = createRookRuntime({store: workroom.rook, flow: workroom.flow, board: () => workroom.list(),
    enabled: true, identity: {id: 'rook', approvalRef: 'fixture'}, verifyIdentity: () => true,
    now: () => Number(at), transport: workroom.rook.relayInbox});
  runtime.start();
  const result = await runtime.tick();
  process.send({pid: process.pid, result: result.status, claimed: result.taskId});
}
