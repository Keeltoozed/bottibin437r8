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
  const BASE = 'https://demo-fapi.binance.com';

  // 1. Check leverage brackets
  const brackets = await req(BASE, 'GET', '/fapi/v1/leverageBracket', { symbol: 'VANAUSDT' }, true);
  console.log('VANA leverage bracket:', JSON.stringify(brackets, null, 2));

  // 2. Set leverage
  const lev = await req(BASE, 'POST', '/fapi/v1/leverage', { symbol: 'VANAUSDT', leverage: 75 }, true);
  console.log('\nSet leverage 75x:', JSON.stringify(lev));

  // 3. Set margin type
  const margin = await req(BASE, 'POST', '/fapi/v1/marginType', { symbol: 'VANAUSDT', marginType: 'ISOLATED' }, true);
  console.log('Set margin ISOLATED:', JSON.stringify(margin));

  // 4. Get price
  const price = await req(BASE, 'GET', '/fapi/v1/ticker/price', { symbol: 'VANAUSDT' });
  console.log('\nVANA price:', price.price);

  // 5. Get exchange info for precision
  const info = await req(BASE, 'GET', '/fapi/v1/exchangeInfo');
  const vana = info.symbols.find(s => s.symbol === 'VANAUSDT');
  console.log('VANA precision:', JSON.stringify(vana?.precision));
  for (const f of vana?.filters || []) {
    console.log(`  ${f.filterType}:`, JSON.stringify(f));
  }

  // 6. Open market order
  const qty = 100;
  const order = await req(BASE, 'POST', '/fapi/v1/order', {
    symbol: 'VANAUSDT', side: 'BUY', type: 'MARKET', quantity: qty
  }, true);
  console.log('\nMarket BUY 100 VANA:', JSON.stringify(order));

  // 7. Check position
  const pos = await req(BASE, 'GET', '/fapi/v2/positionRisk', { symbol: 'VANAUSDT' }, true);
  console.log('\nPosition:', JSON.stringify(pos, null, 2));

  // 8. Set SL
  const slPrice = parseFloat(price.price) * 0.96;
  const slOrder = await req(BASE, 'POST', '/fapi/v1/order', {
    symbol: 'VANAUSDT', side: 'SELL', type: 'STOP_MARKET',
    stopPrice: slPrice.toFixed(4), reduceOnly: 'true', workingType: 'MARK_PRICE'
  }, true);
  console.log('\nSL order:', JSON.stringify(slOrder));

  // 9. Set TP
  const tpPrice = parseFloat(price.price) * 1.06;
  const tpOrder = await req(BASE, 'POST', '/fapi/v1/order', {
    symbol: 'VANAUSDT', side: 'SELL', type: 'TAKE_PROFIT_MARKET',
    stopPrice: tpPrice.toFixed(4), reduceOnly: 'true', workingType: 'MARK_PRICE'
  }, true);
  console.log('TP order:', JSON.stringify(tpOrder));

  // 10. Check all orders
  const orders = await req(BASE, 'GET', '/fapi/v1/openOrders', { symbol: 'VANAUSDT' }, true);
  console.log('\nOpen orders:', JSON.stringify(orders, null, 2));

  // 11. Cancel all and close position
  console.log('\n=== CLEANUP ===');
  const cancelAll = await req(BASE, 'DELETE', '/fapi/v1/allOpenOrders', { symbol: 'VANAUSDT' }, true);
  console.log('Cancel all:', JSON.stringify(cancelAll));

  const close = await req(BASE, 'POST', '/fapi/v1/order', {
    symbol: 'VANAUSDT', side: 'SELL', type: 'MARKET', quantity: qty, reduceOnly: 'true'
  }, true);
  console.log('Close:', JSON.stringify(close));

  // 12. Final balance
  const bal = await req(BASE, 'GET', '/fapi/v2/balance', {}, true);
  for (const b of bal) {
    if (parseFloat(b.balance) > 0) console.log(`\nFinal ${b.asset}: ${b.balance}`);
  }
}

main().catch(e => console.error('ERR:', e.message));
