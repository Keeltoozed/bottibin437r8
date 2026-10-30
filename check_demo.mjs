import crypto from 'crypto';
import dotenv from 'dotenv';
dotenv.config();

const API_KEY = process.env.BINANCE_API_KEY || '';
const SECRET = process.env.BINANCE_SECRET || '';

function sign(p) {
  const q = Object.entries(p).map(([k,v]) => `${k}=${v}`).join('&');
  return q + '&signature=' + crypto.createHmac('sha256', SECRET).update(q).digest('hex');
}

async function req(base, m, path, params = {}, signed = false) {
  const ts = Date.now();
  let url = base + path;
  const h = { 'X-MBX-APIKEY': API_KEY };
  if (signed) url += '?' + sign({ ...params, timestamp: ts });
  else if (Object.keys(params).length) url += '?' + Object.entries(params).map(([k,v]) => `${k}=${v}`).join('&');
  const r = await fetch(url, { method: m, headers: h });
  return r.json();
}

async function main() {
  // Test demo-fapi.binance.com
  console.log('=== DEMO-FAPI ===');
  const demoBal = await req('https://demo-fapi.binance.com', 'GET', '/fapi/v2/balance', {}, true);
  if (Array.isArray(demoBal)) {
    for (const b of demoBal) {
      if (parseFloat(b.balance) > 0) console.log(`  ${b.asset}: ${b.balance}`);
    }
  } else {
    console.log('  ERR:', JSON.stringify(demoBal));
  }

  // Test exchangeInfo on demo
  const demoInfo = await req('https://demo-fapi.binance.com', 'GET', '/fapi/v1/exchangeInfo');
  if (demoInfo.symbols) {
    const saga = demoInfo.symbols.find(s => s.symbol === 'SAGAUSDT');
    if (saga) {
      console.log('\nSAGAUSDT on demo:');
      const filters = saga.filters;
      for (const f of filters) {
        if (f.filterType === 'MARKET_LOT_SIZE' || f.filterType === 'LOT_SIZE' || f.filterType === 'NOTIONAL') {
          console.log(`  ${f.filterType}:`, JSON.stringify(f));
        }
      }
    }
    // Check max leverage for several coins
    console.log('\n=== MAX LEVERAGE (demo) ===');
    for (const sym of ['SAGAUSDT','DYMUSDT','VICUSDT','BTCUSDT','ETHUSDT','VANAUSDT','XRPUSDT']) {
      const s = demoInfo.symbols.find(x => x.symbol === sym);
      if (s) {
        const maxLev = s.filters.find(f => f.filterType === 'NOTIONAL');
        console.log(`  ${sym}: maxNotional=${maxLev?.notionalCap || 'N/A'}`);
      }
    }
  }

  // Test exchangeInfo on testnet
  console.log('\n=== TESTNET EXCHANGE INFO ===');
  const tnInfo = await req('https://testnet.binancefuture.com', 'GET', '/fapi/v1/exchangeInfo');
  if (tnInfo.symbols) {
    for (const sym of ['SAGAUSDT','DYMUSDT','VICUSDT','BTCUSDT','ETHUSDT','VANAUSDT']) {
      const s = tnInfo.symbols.find(x => x.symbol === sym);
      if (s) {
        console.log(`  ${sym}: maxLeverage=${s.maxLeverage || 'N/A'}`);
      }
    }
  }

  // Try opening on demo
  console.log('\n=== TRY OPEN ON DEMO ===');
  const ts = Date.now();
  const orderParams = {
    symbol: 'VANAUSDT',
    side: 'BUY',
    type: 'MARKET',
    quantity: 100,
    timestamp: ts
  };
  const sig = sign(orderParams);
  const orderUrl = `https://demo-fapi.binance.com/fapi/v1/order?${sig}`;
  const orderR = await fetch(orderUrl, { method: 'POST', headers: { 'X-MBX-APIKEY': API_KEY } });
  const orderD = await orderR.json();
  console.log('Demo order result:', JSON.stringify(orderD));
}

main().catch(e => console.error('ERR:', e.message));
