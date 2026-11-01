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
        if (String(args[0]).endsWith('owned-command.py') && fs.existsSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-3b8b89bd-56b1-40b7-aebd-6fdc8964dfa5\\preparation-gate.json")) {
          fs.writeFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-3b8b89bd-56b1-40b7-aebd-6fdc8964dfa5\\preparation-entered.txt", 'entered');
          while (JSON.parse(fs.readFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-idempotent-3b8b89bd-56b1-40b7-aebd-6fdc8964dfa5\\preparation-gate.json", 'utf8')).hold)
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        return access(...args);
      }; syncBuiltinESMExports();