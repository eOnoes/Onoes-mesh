import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
      const realSpawn = cp.spawn;
      cp.spawn = (exe, args, options) => {
        if (!["D:\\Dev\\Onoes-Mesh-wt\\m4-link\\test\\app03-m4-link-runtime\\Scripts\\python.exe",'C:\\Python314\\python.exe'].includes(exe) || args.length !== 4 || args[0] !== '-I' || args[1] !== '-B' || args[2] !== '-c' || !args[3]?.includes('mesh_runtime')) {
          console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden');
        }
        console.error('M4_RELAY_RUNTIME_SPAWN'); return realSpawn(exe,args,options);
      };
      for (const name of ['spawnSync','exec','execSync','execFile','execFileSync','fork']) cp[name] = () => { console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden'); };
      syncBuiltinESMExports();