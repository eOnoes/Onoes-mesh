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
        if (String(args[0]).endsWith('owned-command.py') && fs.existsSync("D:\\Dev\\Onoes-Mesh-wt\\m3-crash-compose\\test\\app03-m3-idempotent-c82f0891-cd2b-43f3-a713-f3acdcdade7c\\preparation-gate.json")) {
          fs.writeFileSync("D:\\Dev\\Onoes-Mesh-wt\\m3-crash-compose\\test\\app03-m3-idempotent-c82f0891-cd2b-43f3-a713-f3acdcdade7c\\preparation-entered.txt", 'entered');
          while (JSON.parse(fs.readFileSync("D:\\Dev\\Onoes-Mesh-wt\\m3-crash-compose\\test\\app03-m3-idempotent-c82f0891-cd2b-43f3-a713-f3acdcdade7c\\preparation-gate.json", 'utf8')).hold)
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        return access(...args);
      }; syncBuiltinESMExports();