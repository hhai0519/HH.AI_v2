// credman-env-ab-probe.js — READ-ONLY / NO-MUTATION hosted timing probe (Windows only).
// 不呼叫 Credential Manager API、不讀憑證、不列舉 process.env、不輸出任何環境變數內容。
// 子程序 stdout/stderr 全部丟棄。
const cp = require('child_process');
const path = require('path');

const sr = process.env.SystemRoot || 'C:\\Windows';
const ps = path.join(sr, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');

const stripped = {
  SystemRoot: sr,
  SystemDrive: process.env.SystemDrive || 'C:',
  PATH: process.env.PATH || `${sr}\\System32;${sr}`,
  PATHEXT: process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC',
  TEMP: process.env.TEMP || `${sr}\\Temp`,
  TMP: process.env.TMP || `${sr}\\Temp`,
};

const strippedPsModulePath = {
  ...stripped,
  PSModulePath: path.join(
    sr,
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'Modules'
  ),
};

const cmds = {
  NOOP: '$null = 1',
  ADDTYPE: "Add-Type -TypeDefinition 'public static class HhaiProbeT { public static int V() { return 1; } }'",
};

const envs = {
  STRIPPED: stripped,
  STRIPPED_PSMODULEPATH: strippedPsModulePath,
  INHERITED: undefined,
};

for (let r = 1; r <= 3; r++) {
  for (const e of ['STRIPPED', 'STRIPPED_PSMODULEPATH', 'INHERITED']) {
    for (const c of ['NOOP', 'ADDTYPE']) {
      const t0 = process.hrtime.bigint();

      const res = cp.spawnSync(
        ps,
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-Command',
          cmds[c],
        ],
        {
          stdio: ['ignore', 'ignore', 'ignore'],
          env: envs[e],
          windowsHide: true,
          timeout: 120000,
        }
      );

      const ms = Number(process.hrtime.bigint() - t0) / 1e6;
      const timedout =
        res.error && res.error.code === 'ETIMEDOUT' ? 1 : 0;

      console.log(
        `PROBE round=${r} env=${e} cmd=${c} ms=${ms.toFixed(0)} status=${res.status} timedout=${timedout}`
      );
    }
  }
}
