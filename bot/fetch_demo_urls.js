// Asks the CS2 game coordinator for each match's demo download URL.
//
// First run (interactive, saves a login token so later runs need no password or Steam Guard code):
//   node bot/fetch_demo_urls.js --login
// Then:
//   node bot/fetch_demo_urls.js CSGO-xxxxx-... CSGO-yyyyy-...
// Prints one JSON line per share code: {"share_code": ..., "demo_url": ...} or {"share_code": ..., "error": ...}.
// Logs go to stderr so stdout stays machine-readable.

const fs = require('fs');
const path = require('path');
const SteamUser = require('steam-user');
const GlobalOffensive = require('globaloffensive');

const TOKEN_FILE = path.join(__dirname, '.refresh_token');
const REQUEST_DELAY_MS = Number(process.env.BOT_REQUEST_DELAY_MS || 3000);
const RESPONSE_TIMEOUT_MS = 20000;
const GC_CONNECT_TIMEOUT_MS = 60000;

try {
    process.loadEnvFile(path.join(__dirname, '..', '.env'));
} catch {
    // No .env: rely on the real environment.
}

const log = (...parts) => console.error('[bot]', ...parts);
const loginOnly = process.argv.includes('--login');
const codes = process.argv.slice(2).filter((arg) => arg.startsWith('CSGO-'));

const user = new SteamUser();
const cs2 = new GlobalOffensive(user);

user.on('refreshToken', (token) => {
    fs.writeFileSync(TOKEN_FILE, token, { mode: 0o600 });
    log('saved login token');
});

user.on('error', (error) => {
    log('Steam login failed:', error.message);
    if (fs.existsSync(TOKEN_FILE) && !loginOnly) {
        log('the saved token may have expired; run with --login again');
    }
    process.exit(2);
});

if (!loginOnly) {
    // Without a saved token a Steam Guard prompt would hang a scheduled run, so fail instead.
    user.on('steamGuard', () => {
        log('Steam Guard code needed: run "node bot/fetch_demo_urls.js --login" once in a terminal');
        process.exit(2);
    });
}

user.on('loggedOn', () => {
    log('logged on as', user.steamID.getSteamID64());
    if (loginOnly) {
        // Give steam-user a moment to emit refreshToken before exiting.
        setTimeout(() => {
            user.logOff();
            process.exit(0);
        }, 2000);
        return;
    }
    user.gamesPlayed([730]);
    setTimeout(() => {
        if (!cs2.haveGCSession) {
            log('could not connect to the CS2 game coordinator');
            process.exit(3);
        }
    }, GC_CONNECT_TIMEOUT_MS).unref();
});

function waitForMatchList() {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            cs2.removeListener('matchList', onList);
            reject(new Error('no response from the game coordinator'));
        }, RESPONSE_TIMEOUT_MS);
        function onList(matches) {
            clearTimeout(timer);
            resolve(matches);
        }
        cs2.once('matchList', onList);
    });
}

function demoUrl(matches) {
    for (const match of matches || []) {
        const stats = match.roundstatsall || [];
        for (let i = stats.length - 1; i >= 0; i--) {
            if (stats[i].map) return stats[i].map;
        }
    }
    return null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

cs2.on('connectedToGC', async () => {
    log('connected to the CS2 game coordinator');
    for (const [index, code] of codes.entries()) {
        if (index > 0) await sleep(REQUEST_DELAY_MS);
        let result;
        try {
            const reply = waitForMatchList();
            cs2.requestGame(code);
            const url = demoUrl(await reply);
            result = url ? { share_code: code, demo_url: url } : { share_code: code, error: 'no demo URL (expired or not recorded)' };
        } catch (error) {
            result = { share_code: code, error: error.message };
        }
        process.stdout.write(JSON.stringify(result) + '\n');
    }
    user.logOff();
    setTimeout(() => process.exit(0), 500);
});

if (!loginOnly && codes.length === 0) {
    log('no share codes given');
    process.exit(1);
}

if (!loginOnly && fs.existsSync(TOKEN_FILE)) {
    user.logOn({ refreshToken: fs.readFileSync(TOKEN_FILE, 'utf8').trim() });
} else {
    const accountName = process.env.BOT_STEAM_USERNAME;
    const password = process.env.BOT_STEAM_PASSWORD;
    if (!accountName || !password) {
        log('set BOT_STEAM_USERNAME and BOT_STEAM_PASSWORD in .env, then run with --login');
        process.exit(1);
    }
    user.logOn({ accountName, password });
}
