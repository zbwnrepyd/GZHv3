#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

function usage() {
  console.log(`Usage:
  node canvas/screenshot.js --company <name> [--set v1|v2|v3|v4] [--base-url http://127.0.0.1:5050] [--out output/cards/<name>] [--bg-image <path>] [--shots 3] [--scale 3] [--params <json>] [--params-file <path>]

Options:
  --company      Company name to export. Required.
  --set          Card set key. Default: v4.
  --base-url     Flask base URL. Default: http://127.0.0.1:5050
  --out          Output directory. Default: output/cards/<company>
  --bg-image     Path to local watermark image (PNG/JPEG). Injected as base64 data URL.
  --shots        Number of screenshots per card. Default: 3.
  --scale        deviceScaleFactor for high-resolution PNGs. Default: 3.
  --shot-delay   Milliseconds between repeated shots. Default: 350.
  --params       Inline JSON string of card parameter overrides.
  --params-file  Path to a JSON file containing card parameter overrides.
  --help         Show this help.
`);
}

function positiveInt(value, fallback) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function parseArgs(argv) {
  const args = {
    baseUrl: 'http://127.0.0.1:5050',
    company: '',
    set: 'v4',
    out: '',
    bgImage: null,
    shots: 3,
    scale: 3,
    shotDelay: 350,
    params: null,
    paramsFile: null,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const item = argv[i];
    if (item === '--help' || item === '-h') {
      args.help = true;
    } else if (item === '--company') {
      args.company = argv[++i] || '';
    } else if (item === '--set') {
      args.set = argv[++i] || args.set;
    } else if (item === '--base-url') {
      args.baseUrl = argv[++i] || args.baseUrl;
    } else if (item === '--out') {
      args.out = argv[++i] || '';
    } else if (item === '--bg-image' || item === '-b') {
      args.bgImage = argv[++i] || null;
    } else if (item === '--shots') {
      args.shots = positiveInt(argv[++i], args.shots);
    } else if (item === '--scale') {
      args.scale = positiveInt(argv[++i], args.scale);
    } else if (item === '--shot-delay') {
      args.shotDelay = positiveInt(argv[++i], args.shotDelay);
    } else if (item === '--params') {
      args.params = argv[++i] || null;
    } else if (item === '--params-file') {
      args.paramsFile = argv[++i] || null;
    }
  }
  return args;
}

function safeName(value) {
  return String(value || 'company').replace(/[/\\?%*:|"<>]/g, '_');
}

function buildCardUrl(baseUrl, company, cardId, setKey, bgImagePath, params) {
  let url = `${baseUrl.replace(/\/$/, '')}/canvas/card/${encodeURIComponent(company)}/${encodeURIComponent(cardId)}`;
  const query = [];
  if (setKey) {
    query.push(`set=${encodeURIComponent(setKey)}`);
  }
  if (bgImagePath) {
    const mime = bgImagePath.endsWith('.png') ? 'image/png' : 'image/jpeg';
    const b64 = fs.readFileSync(bgImagePath).toString('base64');
    const dataUrl = `data:${mime};base64,${b64}`;
    query.push(`bg=${encodeURIComponent(dataUrl)}`);
  }
  if (params) {
    const encoded = Buffer.from(JSON.stringify(params)).toString('base64');
    query.push(`params=${encodeURIComponent(encoded)}`);
  }
  if (query.length) url += `?${query.join('&')}`;
  return url;
}

function loadParams(args) {
  if (args.params) {
    try { return JSON.parse(args.params); } catch (e) {
      console.warn('Failed to parse --params JSON:', e.message);
      return null;
    }
  }
  if (args.paramsFile) {
    if (!fs.existsSync(args.paramsFile)) {
      console.warn('Params file not found:', args.paramsFile);
      return null;
    }
    try { return JSON.parse(fs.readFileSync(args.paramsFile, 'utf-8')); } catch (e) {
      console.warn('Failed to parse params file:', e.message);
      return null;
    }
  }
  return null;
}

async function resolveFetch() {
  if (typeof globalThis.fetch === 'function') {
    return globalThis.fetch.bind(globalThis);
  }
  try {
    const mod = await import('node-fetch');
    return mod.default || mod;
  } catch (error) {
    throw new Error(`Fetch is unavailable. Use Node.js 18+ or install node-fetch. ${error.message}`);
  }
}

async function waitForCard(page) {
  await page.waitForSelector('.knowledge-card', { timeout: 10000 });
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) {
      await document.fonts.ready;
    }
    const images = Array.from(document.images || []);
    await Promise.all(images.map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        image.addEventListener('load', resolve, { once: true });
        image.addEventListener('error', resolve, { once: true });
      });
    }));
  });
  await page.waitForFunction(() => {
    const card = document.querySelector('.knowledge-card');
    if (!card) return false;
    const rect = card.getBoundingClientRect();
    return rect.width >= 899 && rect.height >= 1199;
  }, { timeout: 10000 });
}

async function cardClip(page) {
  return page.evaluate(() => {
    const card = document.querySelector('.knowledge-card');
    const rect = card.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  });
}

function shotFileName(safeCompany, cardIndex, shotIndex, shotCount) {
  const card = String(cardIndex).padStart(2, '0');
  if (shotCount <= 1) {
    return `${safeCompany}_card_${card}.png`;
  }
  return `${safeCompany}_card_${card}_shot_${String(shotIndex).padStart(2, '0')}.png`;
}

async function run() {
  const args = parseArgs(process.argv);
  if (args.help) {
    usage();
    return;
  }
  if (!args.company) {
    usage();
    process.exitCode = 1;
    return;
  }

  let puppeteer;
  try {
    puppeteer = require('puppeteer');
  } catch (error) {
    console.error('Puppeteer is not installed. Run: npm install');
    process.exitCode = 1;
    return;
  }

  const company = args.company;
  const safeCompany = safeName(company);
  const outDir = path.resolve(args.out || path.join('output', 'cards', safeCompany));
  fs.mkdirSync(outDir, { recursive: true });

  const params = loadParams(args);
  if (params) {
    console.log('Loaded card parameter overrides.');
  }

  // 从 render-data API 获取启用的卡片列表（GZHv2 动态卡片数）
  let cards = [];
  try {
    const fetch = await resolveFetch();
    const renderDataUrl = `${args.baseUrl.replace(/\/$/, '')}/api/render-data/${encodeURIComponent(company)}?set=${encodeURIComponent(args.set)}`;
    const resp = await fetch(renderDataUrl);
    if (resp.ok) {
      const data = await resp.json();
      cards = (data.cards || []).filter(c => c.enabled !== false).sort((a, b) => (a.card_index || 0) - (b.card_index || 0));
      console.log(`Loaded ${cards.length} enabled cards from render-data API.`);
    } else {
      console.warn('render-data API returned', resp.status, '- falling back to legacy 1-8');
    }
  } catch (e) {
    console.warn('Failed to load render-data:', e.message, '- falling back to legacy 1-8');
  }

  // Fallback: 如果没有从 API 获取到卡片，使用旧的 1..8
  if (!cards.length) {
    cards = Array.from({ length: 8 }, (_, i) => ({ card_id: String(i + 1), card_index: i + 1, card_title: `卡片${i + 1}` }));
  }

  const browser = await puppeteer.launch({ headless: 'new' });
  try {
    const page = await browser.newPage();
    await page.setViewport({
      width: 900,
      height: 1200,
      deviceScaleFactor: args.scale,
    });

    for (const card of cards) {
      const cardId = card.card_id || String(card.card_index);
      const url = buildCardUrl(args.baseUrl, company, cardId, args.set, args.bgImage, params);
      await page.goto(url, { waitUntil: 'networkidle0' });
      await waitForCard(page);
      const clip = await cardClip(page);
      for (let shotIndex = 1; shotIndex <= args.shots; shotIndex += 1) {
        if (shotIndex > 1 && args.shotDelay > 0) {
          await new Promise((resolve) => setTimeout(resolve, args.shotDelay));
        }
        const filePath = path.join(outDir,
          `${safeCompany}_${String(card.card_index).padStart(2, '0')}_${safeName(card.card_title || card.card_id)}_${String(shotIndex).padStart(2, '0')}.png`);
        await page.screenshot({ path: filePath, clip });
        console.log(`exported ${filePath}`);
      }
    }
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
