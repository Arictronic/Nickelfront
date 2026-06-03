const fs = require('fs');
const path = require('path');

const frontendDir = path.resolve(process.argv[2] || process.cwd());
const pkgPath = path.join(frontendDir, 'package.json');
const nodeModulesDir = path.join(frontendDir, 'node_modules');
const viteCmd = path.join(nodeModulesDir, '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');

function fail(message, code = 1) {
  console.error(message);
  process.exit(code);
}

if (!fs.existsSync(pkgPath)) {
  fail(`frontend package.json not found: ${pkgPath}`, 2);
}

let pkg;
try {
  pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
} catch (error) {
  fail(`failed to read frontend package.json: ${error.message}`, 2);
}

const deps = Object.assign({}, pkg.dependencies || {}, pkg.devDependencies || {});
const missing = Object.keys(deps).filter((name) => {
  return !fs.existsSync(path.join(nodeModulesDir, ...name.split('/'), 'package.json'));
});

if (missing.length) {
  fail(`missing frontend deps: ${missing.join(', ')}`);
}

if ((deps.vite || (pkg.scripts && String(pkg.scripts.dev || '').includes('vite'))) && !fs.existsSync(viteCmd)) {
  fail(`vite binary not found: ${viteCmd}`);
}

console.log(`frontend deps ok: ${Object.keys(deps).length}; vite=${fs.existsSync(viteCmd) ? 'ok' : 'not-required'}`);
