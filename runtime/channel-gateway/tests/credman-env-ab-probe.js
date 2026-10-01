// credman-env-ab-probe.js — D3 LAYER-ISOLATION DIAGNOSTIC
// NO CREDENTIAL ACCESS
// NO REPO RUNTIME MUTATION
// BOUNDED EPHEMERAL OS-TEMP MUTATION

const cp = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

function main() {
  const sr = process.env.SystemRoot || 'C:\\Windows';
  const ps = path.join(
    sr,
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );
  const csc = path.join(
    sr,
    'Microsoft.NET',
    'Framework64',
    'v4.0.30319',
    'csc.exe'
  );

  const stripped = {
    SystemRoot: sr,
    SystemDrive: process.env.SystemDrive || 'C:',
    PATH: process.env.PATH || `${sr}\\System32;${sr}`,
    PATHEXT: process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC',
    TEMP: process.env.TEMP || `${sr}\\Temp`,
    TMP: process.env.TMP || `${sr}\\Temp`,
  };

  const envs = {
    STRIPPED: stripped,
    INHERITED: undefined,
  };

  const psCmds = {
    L0_NOOP: '$null = 1',
    L1_CODEDOM_INIT: "$p = [System.CodeDom.Compiler.CodeDomProvider]::CreateProvider('CSharp'); $p.Dispose(); exit 0",
    L2_CODEDOM_COMPILE: "$p = [System.CodeDom.Compiler.CodeDomProvider]::CreateProvider('CSharp'); $c = [System.CodeDom.Compiler.CompilerParameters]::new(); $c.GenerateExecutable = $false; $c.GenerateInMemory = $true; $c.IncludeDebugInformation = $false; $r = $p.CompileAssemblyFromSource($c, [string[]]@('public static class HhaiRkD3CodeDom { public static int V() { return 1; } }')); $p.Dispose(); if ($r.Errors.HasErrors) { exit 1 }; exit 0",
    L4_EMIT_PINVOKE: "$n = [System.Reflection.AssemblyName]::new('HhaiRkD3Emit'); $a = [System.Reflection.Emit.AssemblyBuilder]::DefineDynamicAssembly($n, [System.Reflection.Emit.AssemblyBuilderAccess]::Run); $m = $a.DefineDynamicModule('HhaiRkD3Emit'); $t = $m.DefineType('HhaiRkD3EmitT', [System.Reflection.TypeAttributes]'Public,Class'); $d = $t.DefinePInvokeMethod('GetTickCount64', 'kernel32.dll', [System.Reflection.MethodAttributes]'Public,Static,PinvokeImpl', [System.Reflection.CallingConventions]::Standard, [UInt64], [Type[]]@(), [System.Runtime.InteropServices.CallingConvention]::Winapi, [System.Runtime.InteropServices.CharSet]::Auto); $d.SetImplementationFlags([System.Reflection.MethodImplAttributes]::PreserveSig); $k = $t.CreateType(); $null = $k.GetMethod('GetTickCount64').Invoke($null, $null); exit 0",
  };

  const csharpSource = 'public static class HhaiRkD3Csc {\n  public static int V() { return 1; }\n}\n';

  const layers = [
    'L0_NOOP',
    'L1_CODEDOM_INIT',
    'L2_CODEDOM_COMPILE',
    'L3_CSC_START',
    'L3_CSC_COMPILE',
    'L4_EMIT_PINVOKE',
  ];

  for (let r = 1; r <= 3; r++) {
    for (const e of ['STRIPPED', 'INHERITED']) {
      for (const layer of layers) {
        let res;
        let t0;
        let t1;

        if (layer === 'L3_CSC_START') {
          t0 = process.hrtime.bigint();
          res = cp.spawnSync(
            csc,
            ['/nologo', '/help'],
            {
              stdio: ['ignore', 'ignore', 'ignore'],
              env: envs[e],
              windowsHide: true,
              timeout: 120000,
            }
          );
          t1 = process.hrtime.bigint();
        } else if (layer === 'L3_CSC_COMPILE') {
          const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-d3-'));
          try {
            const srcPath = path.join(tempDir, 'HhaiRkD3Csc.cs');
            const outPath = path.join(tempDir, 'HhaiRkD3Csc.dll');
            fs.writeFileSync(srcPath, csharpSource, 'utf8');

            t0 = process.hrtime.bigint();
            res = cp.spawnSync(
              csc,
              [
                '/nologo',
                '/target:library',
                '/debug-',
                `/out:${outPath}`,
                srcPath,
              ],
              {
                stdio: ['ignore', 'ignore', 'ignore'],
                env: envs[e],
                windowsHide: true,
                timeout: 120000,
              }
            );
            t1 = process.hrtime.bigint();
          } finally {
            fs.rmSync(tempDir, {
              recursive: true,
              force: true,
              maxRetries: 5,
              retryDelay: 100,
            });
          }
        } else {
          const cmd = psCmds[layer];
          t0 = process.hrtime.bigint();
          res = cp.spawnSync(
            ps,
            [
              '-NoLogo',
              '-NoProfile',
              '-NonInteractive',
              '-ExecutionPolicy',
              'Bypass',
              '-Command',
              cmd,
            ],
            {
              stdio: ['ignore', 'ignore', 'ignore'],
              env: envs[e],
              windowsHide: true,
              timeout: 120000,
            }
          );
          t1 = process.hrtime.bigint();
        }

        const ms = Math.round(Number(t1 - t0) / 1e6);
        const timedout =
          res.error && res.error.code === 'ETIMEDOUT' ? 1 : 0;
        const status = res.status !== null && res.status !== undefined ? res.status : 'null';

        process.stdout.write(
          `PROBE round=${r} env=${e} layer=${layer} ms=${ms} status=${status} timedout=${timedout}\n`
        );
      }
    }
  }
}

try {
  main();
} catch {
  process.stderr.write('PROBE_INFRASTRUCTURE_FAILURE\n');
  process.exit(1);
}
