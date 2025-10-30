const charts = {};
const history = {};

async function fetchStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();

  const sum = document.getElementById('summary');
  sum.textContent = `Realized Today: ${data.realized_today_usd.toFixed(2)} USDT`;

  const container = document.getElementById('cards');
  container.innerHTML = '';
  data.symbols.forEach(s => {
    const id = s.symbol.replace('/', '_');
    if (!history[id]) history[id] = [];
    history[id].push({ t: Date.now(), price: s.price, avg: s.avg_entry });
    if (history[id].length > 100) history[id].splice(0, history[id].length - 100);

    const pnlClass = s.unrealized_pct > 0 ? 'text-green-600' : (s.unrealized_pct < 0 ? 'text-red-600' : 'text-zinc-700');

    const card = document.createElement('div');
    card.className = 'bg-white rounded-2xl p-4 shadow';
    card.innerHTML = `
      <div class="flex items-center justify-between mb-2">
        <div class="font-semibold">${s.symbol}</div>
        <div class="text-sm ${pnlClass}">${s.unrealized_pct.toFixed(2)}%</div>
      </div>
      <div class="grid grid-cols-2 gap-2 text-sm mb-3">
        <div><span class="text-zinc-500">Price:</span> ${s.price}</div>
        <div><span class="text-zinc-500">Avg Entry:</span> ${s.avg_entry}</div>
        <div><span class="text-zinc-500">Position:</span> ${s.position}</div>
        <div><span class="text-zinc-500">Unrealized:</span> ${s.unrealized_usd.toFixed(4)} USDT</div>
      </div>
      <canvas id="chart_${id}" height="120"></canvas>
    `;
    container.appendChild(card);

    const ctx = document.getElementById(`chart_${id}`).getContext('2d');
    const labels = history[id].map(p => new Date(p.t).toLocaleTimeString());
    const prices = history[id].map(p => p.price);
    const avgs = history[id].map(p => p.avg);

    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'Price', data: prices, borderWidth: 2, tension: 0.2, pointRadius: 0 },
          { label: 'Avg Entry', data: avgs, borderWidth: 1, tension: 0.2, pointRadius: 0 }
        ]
      },
      options: { responsive: true, plugins: { legend: { display: true } }, scales: { x: { display: false } } }
    });
  });
}

async function init() { await fetchStatus(); setInterval(fetchStatus, 5000); }
init();
