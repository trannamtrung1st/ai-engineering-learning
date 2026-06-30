{
  "name": "{{PRODUCT_SLUG}}",
  "version": "0.1.0",
  "private": true,
  "description": "{{PRODUCT_NAME}} MVP — npm workspaces monorepo",
  "workspaces": ["apps/*", "packages/*", "tests/*"],
  "engines": { "node": ">=20" },
  "scripts": {
    "test:playwright-ui": "npm run test:playwright-ui -w {{WORKSPACE_NAME}}playwright-ui --if-present",
    "aih:once": "./ai-harness/scripts/ralph-once.sh",
    "aih:loop": "./ai-harness/scripts/ralph-loop.sh"
  }
}
