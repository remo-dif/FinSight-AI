import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const parserRequire = createRequire(require.resolve("@typescript-eslint/typescript-estree"));
const modern = parserRequire("minimatch");

test("TypeScript parser glob preprocessing respects the expansion limit", () => {
  const matcher = new modern.Minimatch(Array(7).fill("**/../a/b").join("/"), {
    optimizationLevel: 2,
    braceExpandMax: 8
  });
  assert.ok(matcher.set.length <= 8, `Generated ${matcher.set.length} patterns; expected at most 8`);
});

test("TypeScript parser default-project matching retains dotfile and glob behavior", () => {
  for (const [path, pattern, expected] of [
    ["eslint.config.mjs", "*.mjs", true],
    [".config.ts", "*.ts", true],
    ["src/example.ts", "*.ts", false],
    ["src/example.ts", "src/*.ts", true],
    ["src/example.js", "src/*.ts", false]
  ]) {
    assert.equal(modern.minimatch(path, pattern, { dot: true }), expected);
  }
});

test("legacy ESLint consumers retain their callable CommonJS API", () => {
  const legacy = require("minimatch");
  assert.equal(typeof legacy, "function");
  assert.equal(legacy("src/example.tsx", "**/*.tsx"), true);
  assert.equal(legacy("src/example.ts", "**/*.tsx"), false);
  assert.equal(new legacy.Minimatch("**/*.tsx").match("src/example.tsx"), true);
});
