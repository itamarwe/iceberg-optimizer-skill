"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "..");
const cliPath = path.join(repoRoot, "bin", "iceberg-optimizer-skill.js");

function runCli(args, env = {}) {
  return spawnSync(process.execPath, [cliPath, ...args], {
    cwd: repoRoot,
    env: { ...process.env, ...env },
    encoding: "utf8"
  });
}

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "iceberg-skill-install-"));
}

test("installs the skill into a target skills directory", () => {
  const target = tempDir();
  const result = runCli(["install", "--target", target]);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Installed iceberg-optimizer skill/);
  assert.ok(fs.existsSync(path.join(target, "iceberg-optimizer", "SKILL.md")));
  assert.ok(fs.existsSync(path.join(target, "iceberg-optimizer", "scripts", "profile_table.py")));
});

test("refuses to replace an existing install unless --force is used", () => {
  const target = tempDir();
  assert.equal(runCli(["install", "--target", target]).status, 0);

  const second = runCli(["install", "--target", target]);
  assert.notEqual(second.status, 0);
  assert.match(second.stderr, /already exists/);

  const forced = runCli(["install", "--target", target, "--force"]);
  assert.equal(forced.status, 0, forced.stderr);
});

test("supports dry-run without writing files", () => {
  const target = tempDir();
  const result = runCli(["install", "--target", target, "--dry-run"]);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Would install iceberg-optimizer/);
  assert.equal(fs.existsSync(path.join(target, "iceberg-optimizer")), false);
});

test("supports Codex home installation layout", () => {
  const codexHome = tempDir();
  const result = runCli(["install", "--codex"], { CODEX_HOME: codexHome });

  assert.equal(result.status, 0, result.stderr);
  assert.ok(fs.existsSync(path.join(codexHome, "skills", "iceberg-optimizer", "SKILL.md")));
});
