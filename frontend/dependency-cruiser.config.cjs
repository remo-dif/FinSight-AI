/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      comment: "Circular dependencies make modules harder to change and initialize safely.",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-unresolvable",
      comment: "Every import must resolve to an existing module.",
      severity: "error",
      from: {},
      to: { couldNotResolve: true },
    },
    {
      name: "no-undeclared-packages",
      comment: "Imported npm packages must be declared in package.json.",
      severity: "error",
      from: {},
      to: { dependencyTypes: ["npm-no-pkg", "npm-unknown"] },
    },
    {
      name: "not-to-dev-dependencies",
      comment: "Application code must not rely on packages only available during development.",
      severity: "error",
      from: { path: "^src" },
      to: { dependencyTypes: ["npm-dev"] },
    },
    {
      name: "components-not-to-app",
      comment: "Reusable components must not depend on route entry points.",
      severity: "error",
      from: { path: "^src/components/" },
      to: { path: "^src/app/" },
    },
    {
      name: "libraries-not-to-components",
      comment: "Libraries and state modules must remain independent of the UI layer.",
      severity: "error",
      from: { path: "^src/(lib|store)/" },
      to: { path: "^src/components/" },
    },
    {
      name: "i18n-not-to-components",
      comment: "Shared i18n configuration must not depend on feature components.",
      severity: "error",
      from: { path: "^src/i18n/" },
      to: { path: "^src/components/" },
    },
    {
      name: "no-orphans",
      comment: "Warn about source modules that are not imported by another source module.",
      severity: "warn",
      from: {
        orphan: true,
        pathNot: [
          "^src/middleware\\.ts$",
          "^src/app/",
        ],
      },
      to: {},
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
      dependencyTypes: ["npm", "npm-dev", "npm-optional", "npm-peer", "npm-bundled", "npm-no-pkg"],
    },
    tsConfig: {
      fileName: "tsconfig.json",
    },
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["types", "import", "require", "default"],
    },
    exclude: {
      path: "(^|/)(?:\\.next|node_modules|playwright-report|test-results)(?:/|$)",
    },
  },
};
