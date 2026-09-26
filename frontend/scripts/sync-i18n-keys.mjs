/**
 * Comprueba que todos los locales tengan las mismas claves que en.ts.
 * Uso: node scripts/sync-i18n-keys.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const messagesDir = path.join(__dirname, "../src/i18n/messages");

const LOCALES = ["en", "en-gb", "es", "pt", "it", "fr", "de"];

function extractKeys(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const keys = new Set();
  for (const m of text.matchAll(/^\s+"([^"]+)":/gm)) {
    keys.add(m[1]);
  }
  return keys;
}

const enPath = path.join(messagesDir, "en.ts");
const enKeys = extractKeys(enPath);

let exitCode = 0;

for (const locale of LOCALES) {
  if (locale === "en") continue;
  const filePath = path.join(messagesDir, `${locale}.ts`);
  const keys = extractKeys(filePath);
  const missing = [...enKeys].filter((k) => !keys.has(k));
  if (missing.length > 0) {
    console.log(`\n${locale}: faltan ${missing.length} claves (fallback a en en runtime)`);
    missing.slice(0, 8).forEach((k) => console.log(`  - ${k}`));
    if (missing.length > 8) console.log(`  ... y ${missing.length - 8} más`);
    exitCode = 1;
  }
}

console.log(`\nBase en.ts: ${enKeys.size} claves`);
console.log(exitCode === 0 ? "OK: todos los locales tienen las claves de en." : "AVISO: hay claves faltantes (getDictionary hace fallback a en).");
process.exit(exitCode);
