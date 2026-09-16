/**
 * runtime/channel-gateway/core/local-config-loader.js
 *
 * ADR-0022 D24: Repo-External Config Loader + Startup Path Validation.
 *
 * Invariants:
 * - Reads Wave 2C data-location config from an explicitly provided repo-external JSON path.
 * - Strict repoRoot containment enforcement: config file must NOT reside within repoRoot (both nominal and canonical realpath checked).
 * - Symlinks outside repo resolving into repo are strictly rejected.
 * - Fail-closed error handling on any missing file, directory, or invalid schema/JSON.
 * - Startup data path validation:
 *   - Four singleton data roots (archiveRoot, attachmentTempRoot, stateRoot, logsRoot):
 *     must exist, be directories, and be readable and writable.
 *   - Protected roots (protectedRoots):
 *     must contain at least 1 entry; each must exist, be a directory, and be readable.
 * - Returns a new canonical config object with all data paths resolved via fs.realpathSync.
 * - Zero auto-creation: NEVER calls fs.mkdirSync or creates missing directories.
 * - Zero process.env or OS desktop/known-folder approximation.
 * - Zero credentials, bot tokens, secrets, network ports, or listeners.
 * - Zero third-party dependencies (Node.js built-ins node:fs and node:path only).
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {
  validateResolvedDataLocationConfig,
  isAbsolutePath,
} = require('./data-location-config');

const REQUIRED_WRITABLE_ROOTS = [
  'archiveRoot',
  'attachmentTempRoot',
  'stateRoot',
  'logsRoot',
];

/**
 * Checks if childPath is located inside parentPath (or is identical to parentPath).
 * Handles cross-platform normalization and case-insensitivity on Windows.
 *
 * @param {string} childPath
 * @param {string} parentPath
 * @returns {boolean}
 */
function isPathInside(childPath, parentPath) {
  const resolvedParent = path.resolve(parentPath);
  const resolvedChild = path.resolve(childPath);

  const rel = path.relative(resolvedParent, resolvedChild);

  if (rel === '') {
    return true;
  }

  if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
    return false;
  }

  return true;
}

/**
 * Loads and validates a repo-external data location configuration file.
 *
 * @param {string} configPath - Absolute path to repo-external JSON config file.
 * @param {object} options - Options object containing at least repoRoot.
 * @param {string} options.repoRoot - Absolute path to repository root.
 * @param {boolean} [options.validateStartupLocations=false] - If true, also validate startup data paths.
 * @returns {object} Validated (and optionally canonicalized) configuration object.
 * @throws {TypeError|Error} If arguments, containment, file status, JSON, or schema fail.
 */
function loadDataLocationConfigFromFile(configPath, options) {
  // 1. Validate configPath contract
  if (typeof configPath !== 'string') {
    throw new TypeError('configPath must be a string');
  }

  const trimmedConfigPath = configPath.trim();
  if (!trimmedConfigPath) {
    throw new Error('configPath must be a non-empty string');
  }

  if (!isAbsolutePath(trimmedConfigPath)) {
    throw new Error(`configPath must be an absolute path: received '${configPath}'`);
  }

  // 2. Validate options and repoRoot contract
  if (!options || typeof options !== 'object' || Array.isArray(options)) {
    throw new TypeError('options must be a non-null object');
  }

  if (typeof options.repoRoot !== 'string') {
    throw new TypeError('options.repoRoot must be a string');
  }

  const trimmedRepoRoot = options.repoRoot.trim();
  if (!trimmedRepoRoot) {
    throw new Error('options.repoRoot must be a non-empty string');
  }

  if (!isAbsolutePath(trimmedRepoRoot)) {
    throw new Error(`options.repoRoot must be an absolute path: received '${options.repoRoot}'`);
  }

  const nominalRepoRoot = path.resolve(trimmedRepoRoot);
  let repoStat;
  try {
    repoStat = fs.statSync(nominalRepoRoot);
  } catch (err) {
    throw new Error(`Repository root does not exist or cannot be accessed: '${nominalRepoRoot}' (${err.message})`);
  }

  if (!repoStat.isDirectory()) {
    throw new Error(`Repository root must be a directory: '${nominalRepoRoot}'`);
  }

  const canonicalRepoRoot = fs.realpathSync(nominalRepoRoot);
  const nominalConfigPath = path.resolve(trimmedConfigPath);

  // 3. Nominal containment check: config file path must not be within repoRoot
  if (isPathInside(nominalConfigPath, nominalRepoRoot) || isPathInside(nominalConfigPath, canonicalRepoRoot)) {
    throw new Error(
      `Configuration file must be repo-external: nominal path '${nominalConfigPath}' is within repoRoot '${nominalRepoRoot}'`
    );
  }

  // 4. File existence and regular file check
  let configStat;
  try {
    configStat = fs.statSync(nominalConfigPath);
  } catch (err) {
    throw new Error(`Configuration file does not exist or cannot be accessed: '${nominalConfigPath}' (${err.message})`);
  }

  if (!configStat.isFile()) {
    throw new Error(`Configuration path must be a regular file: '${nominalConfigPath}'`);
  }

  // 5. Canonical realpath containment check (prevents symlinks resolving into repoRoot)
  let canonicalConfigPath;
  try {
    canonicalConfigPath = fs.realpathSync(nominalConfigPath);
  } catch (err) {
    throw new Error(`Failed to resolve realpath for configuration file: '${nominalConfigPath}' (${err.message})`);
  }

  if (isPathInside(canonicalConfigPath, canonicalRepoRoot) || isPathInside(canonicalConfigPath, nominalRepoRoot)) {
    throw new Error(
      `Configuration file must be repo-external: canonical path '${canonicalConfigPath}' resolves within repoRoot '${canonicalRepoRoot}'`
    );
  }

  // 6. Read UTF-8 content
  let rawContent;
  try {
    rawContent = fs.readFileSync(nominalConfigPath, 'utf8');
  } catch (err) {
    throw new Error(`Failed to read configuration file: '${nominalConfigPath}' (${err.message})`);
  }

  // 7. Parse JSON strictly without echoing full content in error
  let parsed;
  try {
    parsed = JSON.parse(rawContent);
  } catch (err) {
    throw new Error(`Failed to parse configuration file as JSON: '${nominalConfigPath}' (${err.message})`);
  }

  // 8. Wave 2C schema validation
  const validatedConfig = validateResolvedDataLocationConfig(parsed);

  // 9. Optional startup data location validation if requested
  if (options.validateStartupLocations === true) {
    return validateStartupDataLocations(validatedConfig);
  }

  return validatedConfig;
}

/**
 * Validates configured data location directories before gateway startup.
 *
 * Invariants:
 * - Input config must be a valid resolved data location configuration.
 * - archiveRoot, attachmentTempRoot, stateRoot, logsRoot must exist, be directories, and be readable and writable.
 * - protectedRoots must contain >= 1 directory; each must exist, be a directory, and be readable.
 * - Never creates directories (zero fs.mkdirSync).
 * - Returns a new canonical configuration object with paths canonicalized via fs.realpathSync.
 * - Does not mutate the input object.
 *
 * @param {object} resolvedConfig
 * @returns {object} Canonical configuration object
 * @throws {TypeError|Error} If any path does not exist, is not a directory, or lacks required permissions
 */
function validateStartupDataLocations(resolvedConfig) {
  // 1. Ensure Wave 2C schema compliance
  const validated = validateResolvedDataLocationConfig(resolvedConfig);
  const { dataLocations } = validated;

  // 2. Validate protectedRoots requirement: at least 1 entry
  if (!Array.isArray(dataLocations.protectedRoots) || dataLocations.protectedRoots.length === 0) {
    throw new Error("protectedRoots must contain at least one directory path");
  }

  // 3. Validate the four writable roots
  for (const field of REQUIRED_WRITABLE_ROOTS) {
    const rootPath = dataLocations[field];
    let stat;
    try {
      stat = fs.statSync(rootPath);
    } catch (err) {
      throw new Error(
        `Configured data location '${field}' does not exist or cannot be accessed: '${rootPath}' (${err.message})`
      );
    }

    if (!stat.isDirectory()) {
      throw new Error(`Configured data location '${field}' must be a directory: '${rootPath}'`);
    }

    try {
      fs.accessSync(rootPath, fs.constants.R_OK | fs.constants.W_OK);
    } catch (err) {
      throw new Error(
        `Configured data location '${field}' must be readable and writable: '${rootPath}' (${err.message})`
      );
    }
  }

  // 4. Validate protectedRoots
  for (let i = 0; i < dataLocations.protectedRoots.length; i++) {
    const protectedPath = dataLocations.protectedRoots[i];
    let stat;
    try {
      stat = fs.statSync(protectedPath);
    } catch (err) {
      throw new Error(
        `Configured protected root [${i}] does not exist or cannot be accessed: '${protectedPath}' (${err.message})`
      );
    }

    if (!stat.isDirectory()) {
      throw new Error(`Configured protected root [${i}] must be a directory: '${protectedPath}'`);
    }

    try {
      fs.accessSync(protectedPath, fs.constants.R_OK);
    } catch (err) {
      throw new Error(
        `Configured protected root [${i}] must be readable: '${protectedPath}' (${err.message})`
      );
    }
  }

  // 5. Build and return canonical configuration with realpathSync (without mutating input)
  const canonicalLocations = {
    archiveRoot: fs.realpathSync(dataLocations.archiveRoot),
    attachmentTempRoot: fs.realpathSync(dataLocations.attachmentTempRoot),
    stateRoot: fs.realpathSync(dataLocations.stateRoot),
    logsRoot: fs.realpathSync(dataLocations.logsRoot),
    protectedRoots: dataLocations.protectedRoots.map((p) => fs.realpathSync(p)),
  };

  return {
    schemaVersion: validated.schemaVersion,
    dataLocations: canonicalLocations,
  };
}

module.exports = {
  REQUIRED_WRITABLE_ROOTS,
  isPathInside,
  loadDataLocationConfigFromFile,
  validateStartupDataLocations,
};
