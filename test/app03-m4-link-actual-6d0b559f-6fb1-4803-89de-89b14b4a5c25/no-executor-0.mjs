import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
      const realSpawn = cp.spawn;
      cp.spawn = (exe, args, options) => {
        if (exe !== 'C:\\Python314\\python.exe' || args.length !== 5 || args[0] !== '-I' || args[1] !== '-S' || args[2] !== '-B' || args[3] !== '-c' || !args[4]?.includes('mesh_runtime')) {
          console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden');
        }
        console.error(JSON.stringify({event:'M4_RELAY_RUNTIME_SPAWN',executable:exe,args,environmentKeys:Object.keys(options.env).sort()})); return realSpawn(exe,args,options);
      };
      for (const name of ['spawnSync','exec','execSync','execFile','execFileSync','fork']) cp[name] = () => { console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden'); };
      syncBuiltinESMExports();