import cp from 'node:child_process'; import fs from 'node:fs';
      import {syncBuiltinESMExports} from 'node:module';
      let remaining = 2; const spawn = cp.spawn;
      cp.spawn = (...args) => {
        if (remaining-- <= 0) { console.error('RECOVERY_SPAWN_TRIPWIRE'); throw new Error('Unexpected replay spawn'); }
        const child = spawn(...args); console.error('RECOVERY_NATIVE_SPAWN ' + child.pid);
        let stdout = ''; child.stdout.on('data', chunk => { stdout += chunk; });
        const emit = child.emit;
        child.emit = function(name, ...values) {
          if (name === 'close' && fs.existsSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-crash-recovery-8f71fd92-1149-456c-aafd-4195bf852828\\hold-result") && fs.readFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-crash-recovery-8f71fd92-1149-456c-aafd-4195bf852828\\hold-result", 'utf8') === 'hold') {
            fs.writeFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-crash-recovery-8f71fd92-1149-456c-aafd-4195bf852828\\native-result.json", JSON.stringify({bridgePid: child.pid, bridgeExit: values[0], result: JSON.parse(stdout)}));
            const timer = setInterval(() => {
              if (fs.readFileSync("D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m3-crash-recovery-8f71fd92-1149-456c-aafd-4195bf852828\\hold-result", 'utf8') !== 'hold') { clearInterval(timer); emit.call(child, name, ...values); }
            }, 10); return true;
          }
          return emit.call(this, name, ...values);
        }; return child;
      }; syncBuiltinESMExports();