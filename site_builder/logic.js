class Component extends DCLogic {
  constructor(props) {
    super(props);
    this.state = { tab: 'start', src: 'pipeline', custom: null, csvError: '', dd: 0, cs: 0, m: 20, h: 10, sel: 5, role: 'all', vq: '', pm: 0.0, bk: '0.8', bm: '0.12', wcat: 'Laptops_current', ph: 120, ck: 'per_item', ca: 0.5, cc: 'ALL', vn: 'pallet_zone', vt: 'numeric', vk: 'receipt', vd: '', vm: { recovery: true, hazard: false, match: false, uplift: false } };
  }
  renderVals() {
    const CH = __CHARTS__;
    const D = __DATA__;
    const V = __VARS__;
    const S = this.state;
    const pad = (n) => (n < 10 ? '0' + n : '' + n);
    const fmt = (x, d) => (x === null || x === undefined || isNaN(x)) ? '-' : Number(x).toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
    const usd = (x, d) => (x < 0 ? '-$' : '$') + fmt(Math.abs(x), d === undefined ? 0 : d);
    const sgn = (x, d) => (x < 0 ? '-$' : '+$') + fmt(Math.abs(x), d === undefined ? 2 : d);
    const ACCENT = '#ff4a12', LOSS = '#b5462a', GAIN = '#2f7d4f', INK = '#0e1420', PAPER = '#f6f7f7';
    const FACTS = __FACTS__;
    const seg = (items, cur, key, set) => items.map(it => ({ label: it.label, bg: cur === it.k ? INK : PAPER, fg: cur === it.k ? '#e4e8ea' : INK, pick: () => set(it.k) }));

    // tabs
    const tabKeys = ['start', 'findings', 'play', 'scen', 'recs', 'how', 'variables', 'calcs', 'pipe'];
    const tb = {}, show = {}, go = {};
    tabKeys.forEach(k => {
      tb[k] = { bg: S.tab === k ? ACCENT : INK, fg: S.tab === k ? '#ffffff' : '#e4e8ea' };
      show[k] = S.tab === k;
      go[k] = () => { this.setState({ tab: k }); try { window.scrollTo(0, 0); } catch (e) {} };
    });

    // scenario 1
    const pstar = (S.h + S.m) === 0 ? 0 : Math.round((S.h / (S.m + S.h)) * 100);
    const verdict = pstar < 23 ? 'Even the low end of five items clears it: fixed price looks safe.' : (pstar > 88 ? 'Even the high end of five items falls short: auction wins.' : 'Five items cannot settle it: the range straddles the break-even.');

    // variables
    const KN = ['receipt', 'listing', 'during_listing', 'sale', 'post_sale'];
    const KNOTE = { receipt: 'Known when the pallet arrives. Safe for every model.', listing: 'Known when the item is listed. The default prediction moment.', during_listing: 'Accrues while listed (views, bids so far). Safe only for the daily timing model.', sale: 'Known when it sells. Outcome, not input.', post_sale: 'Known after the sale (refunds). Never an input.' };
    const KBG = { receipt: '#2e9e5b', listing: '#2e9e5b', during_listing: '#ffd400', sale: LOSS, post_sale: LOSS };
    const KFG = { receipt: '#fff', listing: '#fff', during_listing: INK, sale: '#fff', post_sale: '#fff' };
    const stagesKnown = KN.map(k => ({ name: k.replace('_', ' '), note: KNOTE[k], bg: KBG[k], fg: KFG[k] }));
    const roles = ['all'].concat(Array.from(new Set(V.map(v => v.role))));
    const roleBtns = seg(roles.map(r => ({ k: r, label: r })), S.role, 'role', (k) => this.setState({ role: k }));
    const q = S.vq.trim().toLowerCase();
    const vf = V.filter(v => (S.role === 'all' || v.role === S.role) && (!q || (v.name + ' ' + v.description + ' ' + (v.why || '')).toLowerCase().indexOf(q) >= 0));
    const vlist = vf.map(v => ({ name: v.name, dtype: v.dtype, role: v.role, why: v.why || '', description: v.description || '', klabel: 'known at: ' + String(v.known_at).replace('_', ' '), kbg: KBG[v.known_at] || '#52606c', kfg: KFG[v.known_at] || '#fff', used: Array.isArray(v.used_in) ? (v.used_in.length ? 'used in ' + v.used_in.join(', ') : 'not a model input') : (v.used_in ? 'used in ' + v.used_in : 'not a model input') }));

    // calcs
    const calcList = D.calcs.map(c => {
      const val = c.value;
      let s;
      if (val === null || val === undefined) s = '-';
      else if (/rate|sell_through|refund|recovery/.test(c.name) || (val > 0 && val < 1.5 && !/days|cost/.test(c.name))) s = Number(val).toFixed(3);
      else if (/cost|value|margin|per_item/.test(c.name) && !/count/.test(c.name)) s = usd(val, Math.abs(val) < 100 ? 2 : 0);
      else s = fmt(val, Math.abs(val) < 100 ? 2 : 0);
      return { name: c.name, levels: (c.levels || []).join(', '), desc: c.desc, sql: c.sql, where: c.where || 'all rows', value: s };
    });

    // scenario 2
    const premBtns = seg([0, 0.1, 0.2, 0.3].map(p => ({ k: p, label: 'premium +' + Math.round(p * 100) + '%' })), S.pm, 'pm', (k) => this.setState({ pm: k }));
    const impactRows = D.impact.filter(r => r.premium === S.pm).map(r => ({
      anchor: r.anchor.indexOf('oracle') === 0 ? 'oracle (upper bound)' : r.anchor,
      nv: usd(r.net_value_per_item, 2),
      gain: r.anchor === 'incumbent' ? 'baseline' : sgn(r.gain_vs_first_per_item, 2),
      range: r.anchor === 'incumbent' ? '-' : (sgn(r.lo95, 2) + ' to ' + sgn(r.hi95, 2)),
      month: r.anchor === 'incumbent' ? '-' : sgn(r.gain_per_month, 0)
    }));

    // scenario 3
    const bs = D.sweep.filter(r => String(r.risk_buffer_k) === String(Number(S.bk)) && String(r.target_margin) === String(Number(S.bm)))[0] || D.sweep[0];
    const base = D.bt[0];
    const bidStats = [
      { v: fmt(bs.lots_bought), l: 'lots bought of 800' },
      { v: usd(bs.total_profit / 1000, 0) + 'k', l: 'total profit (status quo ' + usd(base.total_profit / 1000, 0) + 'k)' },
      { v: bs.profit_per_spend.toFixed(2), l: 'profit per dollar spent (status quo ' + Number(base.profit_per_spend_dollar).toFixed(2) + ')' },
      { v: Math.round(bs.share_of_lots_over_ceiling * 100) + '%', l: 'lots over the ceiling' }
    ];

    // scenario 4
    const wr = D.wait.filter(r => r.category === S.wcat)[0] || D.wait[0];
    const wkeys = [['DP, full ladder', 'Learned schedule, full ladder'], ['DP, supported range', 'Learned schedule, tested range'], ['hold at +10%', 'Hold one price, +10%'], ['hold at +20%', 'Hold one price, +20%'], ['hold at +30%', 'Hold one price, +30%']];
    const wmax = Math.max.apply(null, wkeys.map(k => Math.max(0, wr[k[0]] || 0)).concat([0.01]));
    const waitBars = wkeys.map((k, i) => ({ label: k[1], v: Number(wr[k[0]]).toFixed(3), w: Math.max(0, (wr[k[0]] / wmax) * 100).toFixed(1) + '%', c: i < 2 ? ACCENT : '#8a7f70' }));
    const catOptions = D.cat.map(c => ({ v: c.category }));

    // scenario 5
    const POOL = 0.039, LAB = 1.06;
    const ben = POOL * S.ph, net = ben - LAB;
    const photoStats = [{ v: usd(ben, 2), l: 'expected benefit' }, { v: usd(LAB, 2), l: 'extra labor' }, { v: sgn(net, 2), l: 'net per item' }];
    const photoVerdict = net > 0 ? 'Yes: take the extra photos.' : 'No: the labor costs more than the lift.';
    const photoColor = net > 0 ? GAIN : LOSS;

    // scenario 6
    const mx = Math.max.apply(null, D.cat.map(c => Math.abs(c.cm)));
    const catRows = D.cat.slice().sort((a, b) => b.cm - a.cm).map(c => {
      const w = (Math.abs(c.cm) / mx) * 50;
      return { cat: c.category, cm: (c.cm < 0 ? '-$' : '$') + fmt(Math.abs(c.cm) / 1000, 0) + 'k', rate: (c.cm_per_retail >= 0 ? '+' : '') + Number(c.cm_per_retail).toFixed(2), left: (c.cm >= 0 ? 50 : 50 - w) + '%', w: w + '%', c: c.cm >= 0 ? GAIN : LOSS };
    });
    const totalCm = D.cat.reduce((a, c) => a + c.cm, 0);

    // scenario 7
    const sel = D.cat.filter(c => S.cc === 'ALL' || c.category === S.cc);
    let extra = 0;
    sel.forEach(c => {
      if (S.ck === 'per_item') extra += S.ca * c.n;
      else if (S.ck === 'pct_of_sale') extra += (S.ca / 100) * c.sale;
      else extra += S.ca * c.hdays;
    });
    const costStats = [
      { v: usd(extra, 0), l: 'added cost over 24 months' },
      { v: usd(totalCm - extra, 0), l: 'new total margin (was ' + usd(totalCm, 0) + ')' },
      { v: usd(extra / 24, 0), l: 'per month' },
      { v: (extra / D.cat.reduce((a, c) => a + c.n, 0)).toFixed(2), l: 'per closed item overall' }
    ];
    const costYaml = 'custom_costs:\n  - name: my_cost\n    kind: ' + S.ck + '\n    amount: ' + S.ca + (S.ck === 'pct_of_sale' ? '   # percent' : '') + '\n    applies_to: ' + (S.cc === 'ALL' ? 'all' : '[category = ' + S.cc + ']');

    // scenario 8
    const nm = S.vn.trim();
    const used = Object.keys(S.vm).filter(k => S.vm[k]);
    const errs = [];
    if (!/^[a-z][a-z0-9_]*$/.test(nm)) errs.push('Name must be lower_snake_case.');
    if (V.some(v => v.name === nm)) errs.push('That name already exists in the registry.');
    if (/;|--|\b(drop|delete|insert|update|alter|create|attach|copy)\b/i.test(S.vd)) errs.push('Expression contains a forbidden SQL token.');
    const modelKnown = { recovery: ['receipt', 'listing'], match: ['receipt', 'listing'], uplift: ['receipt', 'listing'], hazard: ['receipt', 'listing', 'during_listing'] };
    used.forEach(u => { if (modelKnown[u].indexOf(S.vk) < 0) errs.push('Leakage: ' + S.vk.replace('_', ' ') + ' values are not known when the ' + u + ' model predicts.'); });
    const vOk = errs.length === 0;
    const vStatus = vOk ? 'Valid: passes name, safety and leakage checks.' : errs.join(' ');
    const vColor = vOk ? GAIN : LOSS;
    const vYaml = 'custom_variables:\n  - name: ' + nm + '\n    dtype: ' + S.vt + '\n    role: feature\n    known_at: ' + S.vk + '\n    used_in: [' + used.join(', ') + ']\n' + (S.vd.trim() ? '    derive: "' + S.vd.replace(/"/g, "'") + '"\n' : '    source: user_csv   # data/user_inputs/extra_item_variables.csv\n');
    const modelBtns = ['recovery', 'hazard', 'match', 'uplift'].map(k => ({ label: k, bg: S.vm[k] ? INK : PAPER, fg: S.vm[k] ? '#e4e8ea' : INK, pick: () => { const vm = Object.assign({}, S.vm); vm[k] = !vm[k]; this.setState({ vm: vm }); } }));

    // scenario 9
    const srcRows = D.sc.slice().sort((a, b) => b.score - a.score).map(r => ({ id: r.source_id, type: r.source_type, lots: r.lots, score: Number(r.score).toFixed(1), tier: r.tier, profit: Number(r.profit_per_retail_dollar_shrunk).toFixed(3), pay: Number(r.avg_price_rate).toFixed(3), ceil: Number(r.ceiling_price_rate).toFixed(3), head: (r.headroom_price_rate >= 0 ? '+' : '') + Number(r.headroom_price_rate).toFixed(3), lever: r.negotiation_lever }));


    // playbook
    const PRE = [{ k: 'today', label: 'As recorded', dd: 0, cs: 0 }, { k: 'hol', label: 'Holiday rush: sales prices +10%', dd: 10, cs: 0 }, { k: 'slump', label: 'Slow season: sales prices -10%', dd: -10, cs: 0 }, { k: 'cost', label: 'Suppliers raise prices 10%', dd: 0, cs: 10 }, { k: 'both', label: 'Worst case: slow season and +10% pallets', dd: -10, cs: 10 }];
    const presetBtns = PRE.map(p => ({ label: p.label, bg: (S.dd === p.dd && S.cs === p.cs) ? INK : PAPER, fg: (S.dd === p.dd && S.cs === p.cs) ? '#e4e8ea' : INK, pick: () => this.setState({ dd: p.dd, cs: p.cs }) }));
    const useCustom = S.src === 'custom' && S.custom;
    const CATS = useCustom ? S.custom.cat : D.cat;
    const PBY = {}; (useCustom ? S.custom.pb : D.pb).forEach(p => { PBY[p.category] = p; });
    const baseTot = CATS.reduce((a, c) => a + c.cm, 0);
    const nowTot0 = CATS.reduce((a, c) => a + (c.netrev * (1 + S.dd / 100) - c.handling - c.holding - c.lotcost * (1 + S.cs / 100)), 0);
    const ddText = S.dd === 0 ? 'Now: no change.' : 'Now: sales prices ' + (S.dd > 0 ? 'up ' : 'down ') + Math.abs(S.dd) + '%.';
    const csText = S.cs === 0 ? 'Now: no change.' : 'Now: pallet prices ' + (S.cs > 0 ? 'up ' : 'down ') + Math.abs(S.cs) + '%.';
    let nBuy = 0, nCut = 0, nHold = 0;
    const ACT = { buy: ['Buy more', GAIN, '#fff'], hold: ['Buy selectively', '#ffd400', INK], cut: ['Buy less or control', LOSS, '#ffffff'] };
    const sg = (x, d) => (x >= 0 ? '+' : '-') + '$' + fmt(Math.abs(x), d || 0);
    const playRows = CATS.map(c => {
      const p = PBY[c.category] || {};
      const fixedCost = c.handling + c.holding;
      const cmNow = c.netrev * (1 + S.dd / 100) - fixedCost - c.lotcost * (1 + S.cs / 100);
      const rate = cmNow / c.retail, paid = c.lotcost * (1 + S.cs / 100) / c.retail;
      const be = (c.netrev * (1 + S.dd / 100) - fixedCost) / c.retail;
      const target = be / 1.12;
      const hasTrend = p.recent !== undefined && p.prev !== undefined && p.recent !== null && p.prev !== null;
      const trend = hasTrend ? p.recent - p.prev : 0;
      let a = rate >= 0.10 ? 'buy' : (rate >= 0 ? 'hold' : 'cut');
      if (a === 'buy' && trend < -0.02) a = 'hold';
      if (a === 'buy') nBuy++; else if (a === 'hold') nHold++; else nCut++;
      const demand = p.st != null && p.bid != null && p.st >= 0.92 && p.bid >= 3;
      let price;
      if (p.fxlo === undefined || p.fxlo === null) price = 'No channel test data was loaded for this category.';
      else if (p.fxlo > 0) price = 'List at a fixed price. In the randomized pilot, fixed price beat auction here by ' + p.fx.toFixed(3) + ' per retail dollar.';
      else if (p.fxhi < 0) price = 'Keep it at auction. In the pilot, fixed price did worse here (' + p.fx.toFixed(3) + ' per retail dollar).';
      else price = 'Auction and fixed price did about equally well in the pilot (difference ' + (p.fx >= 0 ? '+' : '') + p.fx.toFixed(3) + ', too small to tell apart from zero).';
      if (demand) price += ' Demand is strong (' + Math.round(p.st * 100) + '% sell, about ' + p.bid.toFixed(1) + ' bidders per auction), so test a higher opening bid or a higher fixed-price markup.';
      else if (p.st != null && p.st < 0.8) price += ' Only ' + Math.round(p.st * 100) + '% of items sell, so mark down earlier rather than holding.';
      let buy;
      if (a === 'buy') buy = 'Buy more. You can pay up to ' + (target * 100).toFixed(0) + ' cents per retail dollar and still keep a 12% margin. You currently pay ' + (paid * 100).toFixed(0) + '.';
      else if (a === 'hold') buy = 'Keep volume flat and buy only from sources with price headroom. Do not pay more than ' + (target * 100).toFixed(0) + ' cents per retail dollar (now ' + (paid * 100).toFixed(0) + ').';
      else buy = 'Buy less, or negotiate hard. The items bring in about ' + (be * 100).toFixed(0) + ' cents per retail dollar after handling, and you pay ' + (paid * 100).toFixed(0) + '. ' + (p.minband === 'none' ? 'No item size is profitable here: skip it, or buy it only inside a mixed pallet.' : (p.minband ? 'Stop listing items under the ' + p.minband + ' retail band and sell the rest quickly.' : 'Sell quickly and do not spend extra effort on it.'));
      const arrow = !hasTrend ? 'no history loaded' : (trend > 0.015 ? 'improving' : (trend < -0.015 ? 'getting worse' : 'steady')) + ' (' + (p.prev >= 0 ? '+' : '') + p.prev.toFixed(2) + ' then, ' + (p.recent >= 0 ? '+' : '') + p.recent.toFixed(2) + ' last 3 months)';
      return { cat: c.category, abg: ACT[a][1], afg: ACT[a][2], alabel: ACT[a][0], rate: (rate >= 0 ? '+' : '') + rate.toFixed(3), cm: sg(cmNow / 1000, 0) + 'k', delta: sg((cmNow - c.cm) / 1000, 0) + 'k', trend: arrow, price, buy, sort: rate };
    }).sort((x, y) => y.sort - x.sort);
    const playStats = [{ v: '' + nBuy, l: 'categories to buy more of' }, { v: '' + nHold, l: 'categories to buy selectively' }, { v: '' + nCut, l: 'categories to buy less of or control' }, { v: sg(nowTot0 / 1000, 0) + 'k', l: 'total profit in this situation (as recorded: ' + sg(baseTot / 1000, 0) + 'k)' }];
    const pbSource = useCustom ? 'your uploaded file (' + S.custom.name + ', ' + S.custom.cat.length + ' categories).' : 'the pipeline run of ' + FACTS.built_at + ' (simulated data).';
    const dlTemplate = () => {
      const rows = ['category,items,retail_value,net_revenue,handling_cost,holding_cost,lot_cost,recent_margin,prior_margin,sell_through,avg_bidders'].concat(D.cat.slice(0, 3).map(c => [c.category, c.n, Math.round(c.retail), Math.round(c.netrev), Math.round(c.handling), Math.round(c.holding), Math.round(c.lotcost), '', '', '', ''].join(',')));
      try { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([rows.join('\n') + '\n'], { type: 'text/csv' })); a.download = 'playbook_template.csv'; document.body.appendChild(a); a.click(); a.remove(); } catch (e) {}
    };
    const parseCsv = (text, name) => {
      const lines = text.replace(/\r/g, '').split('\n').filter(x => x.trim());
      if (lines.length < 2) throw new Error('The file needs a header row and at least one category row.');
      const head = lines[0].split(',').map(x => x.trim().toLowerCase());
      const need = ['category', 'items', 'retail_value', 'net_revenue', 'handling_cost', 'holding_cost', 'lot_cost'];
      const miss = need.filter(x => head.indexOf(x) < 0);
      if (miss.length) throw new Error('Missing column(s): ' + miss.join(', ') + '.');
      const ix = k => head.indexOf(k);
      const num = (v) => { const x = parseFloat(v); return isNaN(x) ? null : x; };
      const cat = [], pb = [];
      lines.slice(1).forEach((ln, li) => {
        const f = ln.split(',').map(x => x.trim());
        const v = need.slice(1).map(k => num(f[ix(k)]));
        if (!f[ix('category')] || v.some(x => x === null)) throw new Error('Row ' + (li + 2) + ' has a missing or non-numeric value.');
        const c = { category: f[ix('category')], n: v[0], retail: v[1], netrev: v[2], handling: v[3], holding: v[4], lotcost: v[5] };
        if (c.retail <= 0) throw new Error('Row ' + (li + 2) + ': retail_value must be above zero.');
        c.cm = c.netrev - c.handling - c.holding - c.lotcost; c.cm_per_retail = c.cm / c.retail; cat.push(c);
        const o = k => (ix(k) >= 0 ? num(f[ix(k)]) : null);
        pb.push({ category: c.category, recent: o('recent_margin'), prev: o('prior_margin'), st: o('sell_through'), bid: o('avg_bidders') });
      });
      return { cat: cat, pb: pb, name: name };
    };
    const onCsv = (e) => {
      const file = e.target.files && e.target.files[0]; if (!file) return;
      const rd = new FileReader();
      rd.onload = () => { try { this.setState({ custom: parseCsv(String(rd.result), file.name), src: 'custom', csvError: '' }); } catch (err) { this.setState({ csvError: err.message }); } };
      rd.readAsText(file);
    };
    const resetData = () => this.setState({ src: 'pipeline', custom: null, csvError: '' });
    return {
      ddText, csText, pbSource, csvError: S.csvError, dlTemplate, onCsv, resetData, presetBtns, dd: S.dd, cs: S.cs, onDd: (e) => this.setState({ dd: Number(e.target.value) }), onCs: (e) => this.setState({ cs: Number(e.target.value) }), playRows, playStats,
      tb, show, go, tabs: tabKeys,
      m: S.m, h: S.h, pstar, verdict,
      onM: (e) => this.setState({ m: Number(e.target.value) }),
      onH: (e) => this.setState({ h: Number(e.target.value) }),
      stagesKnown, roleBtns, vq: S.vq, onVq: (e) => this.setState({ vq: e.target.value }), vcount: vf.length + ' of ' + V.length + ' variables', vlist,
      calcList,
      premBtns, impactRows,
      bk: S.bk, bm: S.bm, onBk: (e) => this.setState({ bk: e.target.value }), onBm: (e) => this.setState({ bm: e.target.value }), bidStats, bidAccept: 'an assumed constant share',
      wcat: S.wcat, onW: (e) => this.setState({ wcat: e.target.value }), catOptions, waitBars,
      ph: S.ph, onPh: (e) => this.setState({ ph: Number(e.target.value) || 0 }), photoStats, photoVerdict, photoColor,
      catRows, catMonths: 24,
      ck: S.ck, ca: S.ca, cc: S.cc, onCk: (e) => this.setState({ ck: e.target.value }), onCa: (e) => this.setState({ ca: Number(e.target.value) || 0 }), onCc: (e) => this.setState({ cc: e.target.value }), costStats, costYaml,
      vn: S.vn, vt: S.vt, vk: S.vk, vd: S.vd, onVn: (e) => this.setState({ vn: e.target.value }), onVt: (e) => this.setState({ vt: e.target.value }), onVk: (e) => this.setState({ vk: e.target.value }), onVd: (e) => this.setState({ vd: e.target.value }), vStatus, vColor, vYaml, modelBtns,
      srcRows,
      counters: [{ v: '73,133', l: 'Items simulated' }, { v: '800', l: 'Lots from 34 sources' }, { v: '40', l: 'Registered variables' }, { v: '33', l: 'Tests passing' }, { v: '18', l: 'Charts' }],
      asked: [
        { n: '01', said: 'Predict recovery rate', built: 'Two-part model keeps zeros in: P(sells) times price given sold, with calibrated 80% intervals.', where: 'models/recovery.py' },
        { n: '02', said: 'A zero is a zero', built: 'Auction zeros are final. Fixed-price open items are tracked, censored, and measured as a whole strategy.', where: 'decisions/channel.py' },
        { n: '03', said: 'No countdown on fixed price', built: 'Discrete-time sale-timing model plus a hold-one-more-day rule and a markdown ladder.', where: 'models/hazard.py, decisions/waiting.py' },
        { n: '04', said: 'Three more photos for a $1000 item', built: 'Randomized photo experiment gives the value above which extra photos pay for the labor.', where: 'decisions/effort.py' },
        { n: '05', said: 'Truckloads with unknown contents', built: 'Source scorecard with shrinkage, tiers, and a bid ceiling per lot, backtested.', where: 'decisions/scorecard.py, bid_ceiling.py' },
        { n: '06', said: 'Match to Amazon or Walmart.com', built: 'Wrong-match classifier and a review queue ranked by dollars at risk.', where: 'models/match.py' },
        { n: '07', said: 'Answer report requests', built: 'Governed metric definitions, gross vs net, clarifying questions, assumptions stated with every number.', where: 'metrics/clarify.py' },
        { n: '08', said: 'Thousands of dollars per month', built: 'Shadow pricing test scores each estimate through the true sale mechanism, with a bootstrap interval.', where: 'decisions/impact.py' }
      ],
      tiles: [
        { tag: 'Recovery', lot: 'LOT 01', big: '0.169', unit: 'mean abs. error, holdout', text: 'Beats a category-and-condition lookup (0.187) and a category average (0.209). Total predicted dollars land within 3% of actual; a sold-only model is 13% high.' },
        { tag: 'Zero problem', lot: 'LOT 02', big: '-0.013', unit: 'net value per retail dollar, average', text: 'Fixed-price-first is worse than auction on average (95% interval -0.020 to -0.005) and takes 14 days instead of 4. But it clearly wins in one category (Large_appliances) and clearly loses in five.' },
        { tag: 'Waiting', lot: 'LOT 03', big: '0.322', unit: 'vs 0.295 best single price', text: 'A learned markdown schedule beats holding one price when scored against the true mechanism. Only 0.303 inside the tested range, so confirm with a markdown test.' },
        { tag: 'Effort', lot: 'LOT 04', big: '$100', unit: 'retail value, roughly', text: 'Extra photos pay for the labor from that band up. Below $50 they lose money. About 3.9% uplift in sale price against about $1.06 of labor.' },
        { tag: 'Sourcing', lot: 'LOT 05', big: '0.83', unit: 'score vs true profitability', text: 'The scorecard ranks sources well. Lot-value prediction correlates 0.979 with actual, and the bid-ceiling sweep shows what conservatism costs.' },
        { tag: 'Quality', lot: 'LOT 06', big: '75%', unit: 'of mismatch dollars', text: 'Reviewing only the top 5% of items by risk captures that share. Reviewing 20% captures nearly all of it.' }
      ],
      stages: [
        { n: '01', t: 'Simulate', d: 'Known truth, a randomized fixed-price pilot, a photo experiment, duplicates, late revisions and a mid-stream source change.', f: 'sim/generate.py' },
        { n: '02', t: 'Warehouse', d: 'DuckDB models with ref() resolution, 15 data-quality tests, lot cost allocated by retail share.', f: 'sql/ + data/warehouse.py' },
        { n: '03', t: 'Model', d: 'Recovery, sale timing, uplift, match, lot value, drift monitoring and model cards.', f: 'models/' },
        { n: '04', t: 'Decide', d: 'Channel, waiting, effort, scorecard, bid ceiling, shadow impact.', f: 'decisions/' },
        { n: '05', t: 'Answer', d: 'Metric layer for report requests; results, charts and tables written out.', f: 'metrics/ + report.py' }
      ],
      limits: [
        { n: '01', t: 'Everything is simulated. Parameters are placeholders and no number describes a real company.' },
        { n: '02', t: 'Policies are scored against the simulator’s own mechanism. That validates the method, not the real world.' },
        { n: '03', t: 'The markdown schedule extrapolates beyond the premium range the pilot tested. Confirm with a randomized markdown test.' },
        { n: '04', t: 'The bid sweep assumes sellers accept counters at the same rate at any price. Use your own acceptance history.' },
        { n: '05', t: 'After the June 2026 source expansion the sale-timing model over-predicts (' + FACTS.hz_pred.toFixed(3) + ' against ' + FACTS.hz_act.toFixed(3) + '). Monitoring flags it; a rolling recalibration only partly fixes it.' },
        { n: '06', t: 'The simulator was set so categories behave differently: some earn, some break even, some lose, and fixed price wins in one. Those differences are assumptions I chose to exercise every outcome, not findings about any real business.' },
        { n: '07', t: 'This page shows the pipeline’s saved outputs. The panels recompute from them in your browser; the models themselves run offline with make all.' }
      ],
      chartList: CH.map((c, i) => ({ ...c, nn: pad(c.n), bg: i === S.sel ? INK : PAPER, fg: i === S.sel ? '#e4e8ea' : INK, pick: () => this.setState({ sel: i }) })),
      cur: { ...CH[S.sel], nn: pad(CH[S.sel].n) }
    };
  }
}
