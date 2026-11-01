import cp from 'node:child_process'; import fs from 'node:fs';
      import {syncBuiltinESMExports} from 'node:module';
      let remaining = 0; const spawn = cp.spawn;
      cp.spawn = (...args) => {
        if (remaining-- <= 0) { console.error('M3_TRIPWIRE'); throw new Error('replay executor tripwire'); }
        console.error('M3_EXECUTOR_SPAWN'); return spawn(...args);
      };
      for (const name of ['spawnSync','exec','execSync','execFile','execFileSync','fork'])
        cp[name] = () => { console.error('M3_TRIPWIRE'); throw new Error('replay executor tripwire'); };
      const access = fs.promises.access;
      fs.promises.access = async (...args) => {
        if (String(args[0]).endsWith('owned-command.py') && fs.existsSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-bb6260ac-f5c7-4736-9b21-07c8c717f95b\\preparation-gate.json")) {
          fs.writeFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-bb6260ac-f5c7-4736-9b21-07c8c717f95b\\preparation-entered.txt", 'entered');
          while (JSON.parse(fs.readFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-bb6260ac-f5c7-4736-9b21-07c8c717f95b\\preparation-gate.json", 'utf8')).hold)
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        return access(...args);
      }; syncBuiltinESMExports();