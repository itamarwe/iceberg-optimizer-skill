#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const SKILL_NAME = "iceberg-optimizer";
const SKILL_SOURCE = path.join(PACKAGE_ROOT, "skills", SKILL_NAME);
const PACKAGE_JSON = require(path.join(PACKAGE_ROOT, "package.json"));

const SKIP_NAMES = new Set([
  ".DS_Store",
  ".pytest_cache",
  ".tmp",
  "__pycache__"
]);

function usage() {
  return `iceberg-optimizer-skill ${PACKAGE_JSON.version}

Usage:
  iceberg-optimizer-skill install [options]
  iceberg-optimizer-skill --help

Options:
  --target, -t <dir>  Skills directory to install into.
  --claude           Install into ~/.claude/skills (default).
  --codex            Install into \${CODEX_HOME:-~/.codex}/skills.
  --force, -f        Replace an existing iceberg-optimizer skill directory.
  --dry-run          Print the install destination without writing files.
  --help, -h         Show help.
  --version, -v      Show version.

Examples:
  npx iceberg-optimizer-skill install
  npx iceberg-optimizer-skill install --codex
  npx github:itamarwe/iceberg-optimizer-skill install --target .claude/skills
`;
}

function expandHome(input) {
  if (!input) {
    return input;
  }
  if (input === "~") {
    return os.homedir();
  }
  if (input.startsWith("~/")) {
    return path.join(os.homedir(), input.slice(2));
  }
  return input;
}

function defaultSkillsDir(mode) {
  if (mode === "codex") {
    return path.join(process.env.CODEX_HOME || path.join(os.homedir(), ".codex"), "skills");
  }
  return path.join(process.env.CLAUDE_HOME || path.join(os.homedir(), ".claude"), "skills");
}

function parseArgs(argv) {
  const args = [...argv];
  let command = "install";
  if (args[0] && !args[0].startsWith("-")) {
    command = args.shift();
  }

  const opts = {
    command,
    dryRun: false,
    force: false,
    mode: "claude",
    target: null
  };

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") {
      opts.command = "help";
    } else if (arg === "--version" || arg === "-v") {
      opts.command = "version";
    } else if (arg === "--dry-run") {
      opts.dryRun = true;
    } else if (arg === "--force" || arg === "-f") {
      opts.force = true;
    } else if (arg === "--codex") {
      opts.mode = "codex";
    } else if (arg === "--claude") {
      opts.mode = "claude";
    } else if (arg === "--target" || arg === "-t") {
      const value = args[i + 1];
      if (!value || value.startsWith("-")) {
        throw new Error(`${arg} requires a directory`);
      }
      opts.target = value;
      i += 1;
    } else {
      throw new Error(`unknown option: ${arg}`);
    }
  }

  return opts;
}

function shouldSkip(name) {
  return SKIP_NAMES.has(name) || name.endsWith(".pyc");
}

function copyRecursive(src, dest) {
  const stat = fs.lstatSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true, mode: stat.mode });
    for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
      if (shouldSkip(entry.name)) {
        continue;
      }
      copyRecursive(path.join(src, entry.name), path.join(dest, entry.name));
    }
    return;
  }

  if (stat.isSymbolicLink()) {
    fs.symlinkSync(fs.readlinkSync(src), dest);
    return;
  }

  fs.copyFileSync(src, dest);
  fs.chmodSync(dest, stat.mode);
}

function install(opts) {
  if (!fs.existsSync(SKILL_SOURCE)) {
    throw new Error(`skill source not found: ${SKILL_SOURCE}`);
  }

  const skillsDir = path.resolve(expandHome(opts.target || defaultSkillsDir(opts.mode)));
  const destination = path.join(skillsDir, SKILL_NAME);

  if (opts.dryRun) {
    console.log(`Would install ${SKILL_NAME} to ${destination}`);
    return;
  }

  if (fs.existsSync(destination)) {
    if (!opts.force) {
      throw new Error(
        `${destination} already exists. Re-run with --force to replace it.`
      );
    }
    fs.rmSync(destination, { recursive: true, force: true });
  }

  fs.mkdirSync(skillsDir, { recursive: true });
  copyRecursive(SKILL_SOURCE, destination);

  console.log(`Installed ${SKILL_NAME} skill to ${destination}`);
  console.log("Restart or reload your agent so it can discover the skill.");
}

function main(argv = process.argv.slice(2)) {
  let opts;
  try {
    opts = parseArgs(argv);
    if (opts.command === "help") {
      console.log(usage());
      return 0;
    }
    if (opts.command === "version") {
      console.log(PACKAGE_JSON.version);
      return 0;
    }
    if (opts.command !== "install") {
      throw new Error(`unknown command: ${opts.command}`);
    }
    install(opts);
    return 0;
  } catch (err) {
    console.error(`Error: ${err.message}`);
    console.error("Run `iceberg-optimizer-skill --help` for usage.");
    return 1;
  }
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { main, parseArgs };
