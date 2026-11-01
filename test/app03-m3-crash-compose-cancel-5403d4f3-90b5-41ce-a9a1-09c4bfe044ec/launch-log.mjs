import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
    const original = cp.spawn; cp.spawn = (...args) => { const child = original(...args);
      console.error('M3_COMPOSE_NATIVE_SPAWN ' + child.pid); return child; }; syncBuiltinESMExports();