'use strict';

/* Модуль «Цех» · поток заказа: конструктор (производственная карта) → снабженец (сырьё) → технолог. */

const FL = { design: { очередь: [], история: {} }, supply: { очередь: [], спецификации: {}, размеры: {}, рулоны: [], статусы: [] },
  num: '', rows: [], grid: { sizes: [], groups: [] }, bomModel: '', bomRows: [], bomSizes: [], supplyTab: 'orders',
  stock: { позиции: [], движения: [], единицы: ['кг', 'г', 'м', 'шт', 'бобина'] },
  stockForm: { материал: '', цвет: '', количество: '', ед: 'кг', комментарий: '' }, stockBulk: '' };

/* ---- расход сырья: общие функции для снабжения, технолога и закройщика ----
   Нормы задаются по размерам: у каждого размера свой расход на 1 шт. Пустая ячейка размера
   в спецификации = действует общая норма строки («все размеры»). */
const FL_G = { 'г': 1, 'гр': 1, 'грамм': 1, 'кг': 1000 };
const FL_NEW_ROW = () => ({ материал: '', цвет: '', норма: '', ед: 'м', параметры: '', запас: '', размеры: {} });

function flGrams(v, unit) {
  const k = FL_G[String(unit || '').toLowerCase().replace(/\.$/, '')];
  return k ? Math.round(Number(v || 0) * k * 10) / 10 : null;
}

// «336 г», «33,6 кг = 33 600 г», «0,4 м» — вес показываем и в граммах, и в килограммах
function flQty(v, unit) {
  const g = flGrams(v, unit);
  const main = `${nf(v)} ${esc(unit)}`;
  if (g === null) return main;
  const isKg = String(unit).toLowerCase().startsWith('кг');
  const other = isKg ? `${nf(g)} г` : (g >= 1000 ? `${nf(g / 1000)} кг` : '');
  return other ? `${main} <span class="cx-hint">= ${other}</span>` : main;
}

// склад: большие остатки — просто в кг, граммы подсказываем только для малых количеств
function flStockQty(v, unit) {
  const isKg = String(unit).toLowerCase().startsWith('кг');
  return isKg && Math.abs(v) >= 10 ? `${nf(v)} ${esc(unit)}` : flQty(v, unit);
}

function flNoSpecHtml(model) {
  return `<div class="cx-notice warn">Для модели <b>${esc(model)}</b> нет спецификации — расход сырья не рассчитан. Её вносит снабженец (вкладка «Справочник товара»).</div>`;
}

function flNoNormHtml(model, sizes) {
  return sizes && sizes.length
    ? `<div class="cx-notice warn">Для модели <b>${esc(model)}</b> нет нормы расхода на размер: <b>${sizes.map(esc).join(', ')}</b> — сырьё на эти штуки не посчитано. Норму вносит снабженец (вкладка «Справочник товара»).</div>` : '';
}

// Матрица «материал × размер»: сколько сырья уходит на 1 шт (с запасом на отходы) именно в этом размере.
// rows — piece_table; sizes — [{размер, штук}]; total — подпись колонки «всего» (или '' без неё)
function flSizeTableHtml(rows, sizes, total) {
  const head = sizes.map((s) => `<th class="num">${s.размер ? esc(s.размер) : 'Все размеры'}${s.штук ? `<div class="cx-hint">${nf(s.штук)} шт</div>` : ''}</th>`).join('');
  const body = rows.map((r) => {
    const vals = sizes.map((s) => (r.по_размерам[s.размер] || {}).на_1_шт);
    const known = vals.filter((v) => v !== undefined);
    const varies = known.length > 1 && Math.max(...known) !== Math.min(...known);
    const cells = sizes.map((s, i) => {
      const c = r.по_размерам[s.размер];
      return `<td class="num">${c ? (varies ? `<b>${flQty(c.на_1_шт, r.ед)}</b>` : flQty(c.на_1_шт, r.ед))
        : '<span class="cx-hint" title="Для этого размера нормы нет">нет нормы</span>'}</td>`;
    }).join('');
    return `<tr><td>${esc(r.материал)}${r.параметры ? `<div class="cx-hint">${esc(r.параметры)}</div>` : ''}</td>
      <td>${r.цвет ? esc(r.цвет) : '<span class="cx-hint">в цвет изделия</span>'}</td>${cells}
      ${total ? `<td class="num"><b>${flQty(r.всего, r.ед)}</b></td>` : ''}</tr>`;
  }).join('');
  return `<div class="cx-scroll"><table class="cx-table cx-sizetable">
    <thead><tr><th>Материал</th><th>Цвет</th>${head}${total ? `<th class="num">${total}</th>` : ''}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
}

// по модели заказа: расход на 1 шт по размерам и на всё количество (m — элемент «расход» заказа)
function flSpecTableHtml(m) {
  if (m.нет_спецификации) return flNoSpecHtml(m.модель);
  return `<div class="cx-hint" style="margin:10px 0 4px"><b>Модель ${esc(m.модель)}</b> · на 1 шт в каждом размере, с запасом на отходы</div>
    ${flNoNormHtml(m.модель, m.без_нормы)}
    ${flSizeTableHtml(m.строки, m.размеры, `Всего на ${nf(m.штук)} шт`)}`;
}

// для закройщика: расход на 1 шт по размерам партии, на партию по плану и на то, что ещё не раскроено (p — партия из cut_state)
function flCutSpecHtml(p) {
  const r = p.расход;
  if (!r) return '';
  if (r.нет_спецификации) return flNoSpecHtml(p.модель);
  const qty = {};
  (p.строки || []).forEach((x) => { qty[x.размер] = (qty[x.размер] || 0) + (x.план || 0); });
  const key = (x) => `${x.материал}|${x.цвет}|${x.ед}`;
  const rest = Object.fromEntries((r.остаток || []).map((x) => [key(x), x]));
  return `<div class="cx-hint" style="margin:6px 0 4px"><b>Расход на 1 шт</b> в каждом размере партии, с запасом на отходы</div>
    ${flNoNormHtml(p.модель, r.без_нормы)}
    ${flSizeTableHtml(r.на_1_шт, r.размеры.map((sz) => ({ размер: sz, штук: qty[sz] || 0 })), '')}
    <div class="cx-hint" style="margin:12px 0 4px"><b>Сколько сырья на партию</b> — по цветам</div>
    <div class="cx-scroll"><table class="cx-table">
      <thead><tr><th>Материал</th><th>Цвет</th><th class="num">На партию (${nf(p.план)} шт)</th><th class="num">Ещё не раскроено (${nf(p.остаток)} шт)</th></tr></thead>
      <tbody>${(r.план || []).map((x) => `<tr><td>${esc(x.материал)}</td><td>${esc(x.цвет)}</td>
        <td class="num">${flQty(x.нужно, x.ед)}</td><td class="num">${rest[key(x)] ? flQty(rest[key(x)].нужно, x.ед) : '—'}</td></tr>`).join('')}</tbody>
    </table></div>`;
}

// что со складом по строке потребности: остаток, свободно (за вычетом партий в крое), нехватка
function flStockCell(m) {
  const w = m.склад;
  if (!w || !w.позиция) return '<span class="cx-hint">нет на складе</span>';
  if (w.единицы_не_сходятся) return `<span class="cx-neg">единицы не сходятся — на складе в «${esc(w.ед)}»</span>`;
  return `${flStockQty(w.остаток, w.ед)}${w.резерв ? `<div class="cx-hint">свободно ${flStockQty(w.свободно, w.ед)}</div>` : ''}
    ${w.не_хватает > 0 ? `<div class="cx-neg">не хватает ${flStockQty(w.не_хватает, w.ед)}</div>` : '<div class="cx-pos">хватает</div>'}`;
}

async function loadDesign() { FL.design = await api(`${API}/design`); }
async function loadSupply() { FL.supply = await api(`${API}/supply`); }
async function loadStock() { FL.stock = await api(`${API}/stock`); }

// после кроя: что склад списал сам и о чём стоит знать
function flStockToast(text, st) {
  const used = ((st || {}).списано || []).map((x) => `${x.материал}${x.цвет ? ' ' + x.цвет : ''} ${nf(x.количество)} ${x.ед}`);
  const warn = (st || {}).предупреждения || [];
  const msg = text + (used.length ? ` · Со склада списано: ${used.join('; ')}` : '') + (warn.length ? ` · ⚠ ${warn.join('; ')}` : '');
  toast(msg, warn.length ? 'err' : 'ok', used.length || warn.length ? 9000 : 3200);
}

function flHistoryHtml(list) {
  if (!list || !list.length) return '<div class="cx-hint">Изменений пока нет</div>';
  return `<div class="cx-scroll"><table class="cx-table">
    <thead><tr><th>Когда</th><th>Кто</th><th>Позиция</th><th class="num">Было</th><th class="num">Стало</th><th>Комментарий</th></tr></thead>
    <tbody>${list.slice().reverse().map((h) => `<tr><td>${esc(h.дата)}</td><td>${esc(h.кто)}</td>
      <td>${h.модель ? `${esc(h.модель)} · ${esc(h.цвет)} · ${esc(h.размер)}` : '<b>Вся карта</b>'}</td>
      <td class="num">${esc(h.было)}</td><td class="num">${esc(h.стало)}</td><td>${esc(h.комментарий)}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

function flQueue(list, act, empty) {
  if (!list.length) return `<div class="cx-card"><div class="cx-empty"><b>Очередь пуста</b>${empty}</div></div>`;
  return `<div class="cx-queue">${list.map((o) => `
    <div class="cx-qitem ${FL.num === o.номер ? 'on' : ''}" data-act="${act}" data-num="${esc(o.номер)}">
      <div class="cx-qmain">
        <div class="cx-qtitle">Заказ №${esc(o.номер)} ${statusPill(o.статус)}</div>
        <div class="cx-hint">${esc(o.клиент)} · ${nf(o.позиций)} поз. · заказано ${nf(o.заказано)} шт · срок ${esc(o.срок || '—')}</div>
      </div>
      <div class="cx-qright"><button class="btn primary" data-act="${act}" data-num="${esc(o.номер)}">Открыть</button></div>
    </div>`).join('')}</div>`;
}

// ------------------------------------------------------------ конструктор
function designHtml() {
  const q = FL.design.очередь || [];
  const o = q.find((x) => x.номер === FL.num);
  return `<div class="cx-hero compact"><div><h1>Конструктор</h1>
      <div class="cx-sub">Производственная карта: модель, цвет, размеры, итоговое количество и характеристики. Готовая карта уходит снабженцу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    ${flQueue(q, 'fl-design-open', 'Новые заказы на пошив появятся здесь')}
    ${o ? designCardHtml(o) : ''}`;
}

/* ---- карта конструктора сеткой: строка = модель + цвет, колонки = размеры ----
   На сервер уходит прежний плоский список «модель · цвет · размер · итог». Клетка, которая была в карте
   и стала пустой, — это 0 шт (строка остаётся в истории); новая пустая клетка в карту не попадает. */
function flGridFromCard(card) {
  const sizes = [];
  const groups = [];
  const idx = {};
  (card || []).forEach((r) => {
    const k = `${r.модель}|${r.цвет}`;
    let g = idx[k];
    if (!g) { g = idx[k] = { модель: r.модель, цвет: r.цвет, хар: r.характеристики || '', хар_разные: false, хар_тронуты: false, cells: {} }; groups.push(g); }
    if ((r.характеристики || '') !== g.хар) g.хар_разные = true;
    g.cells[r.размер] = { итог: String(r.итог ?? ''), заказано: num(r.заказано), был: true, хар: r.характеристики || '' };
    if (!sizes.includes(r.размер)) sizes.push(r.размер);
  });
  groups.forEach((g) => { if (g.хар_разные) g.хар = ''; });
  return { sizes: flSizeSort(sizes), groups };
}

function flGridToRows() {
  const out = [];
  FL.grid.groups.forEach((g) => {
    FL.grid.sizes.forEach((sz) => {
      const c = g.cells[sz];
      if (!c) return;
      const empty = String(c.итог).trim() === '';
      if (empty && !c.был) return;
      const хар = g.хар_тронуты || !g.хар_разные ? g.хар : c.хар;
      out.push({ модель: g.модель, цвет: g.цвет, размер: sz, итог: empty ? 0 : c.итог, характеристики: хар });
    });
  });
  return out;
}

const flCellQty = (c) => (c ? Math.max(0, Math.round(num(c.итог))) : 0);
const flSizeLabel = (sz) => (sz === '' ? 'без размера' : esc(sz));

function flGridTotals() {
  const rows = FL.grid.groups.map((g) => FL.grid.sizes.reduce((s, sz) => s + flCellQty(g.cells[sz]), 0));
  const cols = FL.grid.sizes.map((sz) => FL.grid.groups.reduce((s, g) => s + flCellQty(g.cells[sz]), 0));
  return { rows, cols, total: rows.reduce((a, b) => a + b, 0) };
}

// обновить суммы, не перерисовывая таблицу (иначе курсор уходит из клетки)
function flGridRefresh() {
  const t = flGridTotals();
  t.rows.forEach((v, i) => { const el = document.getElementById(`fl-gsum-${i}`); if (el) el.textContent = v ? nf(v) : ''; });
  t.cols.forEach((v, i) => { const el = document.getElementById(`fl-gcol-${i}`); if (el) el.textContent = v ? nf(v) : ''; });
  const tot = document.getElementById('fl-total');
  if (tot) tot.textContent = nf(t.total);
  const all = document.getElementById('fl-gall');
  if (all) all.textContent = nf(t.total);
}

function designGridHtml() {
  const { sizes, groups } = FL.grid;
  const t = flGridTotals();
  const body = groups.map((g, gi) => `<tr>
      <th class="cx-gcolor fl-gmeta">
        <input class="input" data-fl-g="${gi}|модель" value="${esc(g.модель)}" list="fl-models" placeholder="модель" aria-label="Модель">
        <input class="input" data-fl-g="${gi}|цвет" value="${esc(g.цвет)}" list="fl-colors" placeholder="цвет" aria-label="Цвет">
      </th>
      ${sizes.map((sz) => {
        const c = g.cells[sz];
        const v = c ? c.итог : '';
        const ord = c ? c.заказано : 0;
        const diff = c && c.был && String(v).trim() !== '' && Math.round(num(v)) !== ord;
        return `<td><input class="cx-gin ${diff ? 'diff' : ''}" type="number" min="0" step="1" inputmode="numeric"
            data-fl-gc="${gi}|${esc(sz)}" value="${esc(v)}" placeholder="·"
            aria-label="${esc(g.модель)} ${esc(g.цвет)}, размер ${flSizeLabel(sz)}">
          ${ord ? `<div class="fl-gord" title="Заказано клиентом">зак. ${nf(ord)}</div>` : ''}</td>`;
      }).join('')}
      <td class="cx-gsum" id="fl-gsum-${gi}">${t.rows[gi] ? nf(t.rows[gi]) : ''}</td>
      <td class="fl-gchar"><input class="input" data-fl-g="${gi}|хар" value="${esc(g.хар)}"
          placeholder="${g.хар_разные && !g.хар_тронуты ? 'по размерам разные — впишите, чтобы задать всем' : 'длина, ткань, фурнитура…'}"></td>
      <td><button class="btn ghost" data-act="fl-g-del" data-i="${gi}" title="Убрать модель и цвет">✕</button></td>
    </tr>`).join('');
  const head = sizes.map((sz, si) => `<th>${flSizeLabel(sz)}
      <button class="fl-gx" data-act="fl-g-size-del" data-i="${si}" title="Убрать размер ${flSizeLabel(sz)}">✕</button></th>`).join('');
  const foot = sizes.map((sz, si) => `<td class="cx-gsum" id="fl-gcol-${si}">${t.cols[si] ? nf(t.cols[si]) : ''}</td>`).join('');
  const suggest = flSizeSort(flAllSizes().filter((s) => !sizes.includes(s)));
  return `<div class="cx-gwrap"><table class="cx-gtable fl-gtable">
      <thead><tr><th class="cx-gcolor">Модель · цвет / размер</th>${head}<th>Σ</th><th>Доп. характеристики</th><th></th></tr></thead>
      <tbody>${body}</tbody>
      <tfoot><tr><th class="cx-gcolor">Итого по размерам</th>${foot}<td class="cx-gsum"><b id="fl-gall">${nf(t.total)}</b></td><td></td><td></td></tr></tfoot>
    </table></div>
    <div class="cx-btn-row" style="margin-top:10px;align-items:center;flex-wrap:wrap">
      <button class="btn" data-act="fl-g-add">+ Модель / цвет</button>
      <input class="input cx-mini" id="fl-g-size" list="fl-g-sizes" placeholder="размер" style="width:140px;max-width:140px">
      <datalist id="fl-g-sizes">${suggest.map((s) => `<option value="${esc(s)}">`).join('')}</datalist>
      <button class="btn" data-act="fl-g-size-add">+ Размер</button>
    </div>`;
}

function designCardHtml(o) {
  const total = flGridTotals().total;
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Карта заказа №${esc(o.номер)}</h3>
      <span class="cx-hint">в заказе ${nf(o.заказано)} шт · в карте <b id="fl-total">${nf(total)}</b> шт</span></div>
    <div class="cx-card-b">
      ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
      <datalist id="fl-models">${(ST.refs.модели || []).map((m) => `<option value="${esc(m.модель)}">${esc(m.название)}</option>`).join('')}</datalist>
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      <div class="cx-hint" style="margin-bottom:8px">Впишите итог в клетку «модель · цвет × размер». Под клеткой — сколько заказал клиент; оранжевая рамка — итог отличается от заказа.</div>
      ${designGridHtml()}
      <div class="cx-field" style="margin-top:12px"><label>Комментарий к изменению</label>
        <input class="input" id="fl-note" placeholder="Например: по 46 размеру не хватает ткани"></div>
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-design-save">Сохранить черновик</button>
        <button class="btn primary" data-act="fl-design-done">Утвердить и передать снабженцу</button>
      </div>
      <div class="cx-hint" style="margin-top:8px">Итог может быть больше или меньше заказа. Каждое изменение записывается в историю.</div>
      <h4 style="margin:18px 0 8px">История изменений</h4>
      ${flHistoryHtml((FL.design.история || {})[o.номер])}
    </div></div>`;
}

function flOpenDesign(numStr) {
  const o = (FL.design.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  FL.grid = flGridFromCard(o.карта);
  render();
}

async function flSaveDesign(done) {
  const rows = flGridToRows();
  const bad = rows.find((r) => !String(r.модель).trim() || !String(r.цвет).trim());
  if (bad) return toast('У строки сетки не заполнена модель или цвет', 'err');
  const body = { номер: FL.num, готово: done, комментарий: ($('#fl-note') || {}).value || '', позиции: rows };
  if (done && !confirm('Утвердить карту и передать заказ снабженцу? После этого карту не поменять.')) return;
  try {
    const res = await api(`${API}/design`, { method: 'POST', body: JSON.stringify(body) });
    await loadDesign();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenDesign(FL.num);
    render();
    toast(done ? `Заказ №${res.номер} передан снабженцу · ${nf(res.штук)} шт` : 'Черновик карты сохранён', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// ------------------------------------------------------------- снабжение
function supplyHtml() {
  const t = FL.supplyTab;
  const buyN = (FL.supply.докупить || []).length;
  const sub = [['orders', `Заказы ${nf((FL.supply.очередь || []).length)}`],
    ['buy', `Что докупить${buyN ? ' ' + nf(buyN) : ''}`], ['rolls', 'Рулоны']];
  return `<div class="cx-hero compact"><div><h1>Снабжение</h1>
      <div class="cx-sub">Сколько сырья нужно на заказ по справочнику товара и сколько его на складе. Когда сырьё готово — заказ уходит технологу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'rolls' ? rollsHtml() : (t === 'buy' ? buyHtml() : supplyOrdersHtml())}`;
}

// ------------------------------------------------- что докупить (все заказы снабжения разом)
function flBuyOrders(r) {
  return r.заказы.map((z) => `№${esc(z.номер)}: ${flStockQty(z.нужно, r.ед)}`).join('<br>');
}

function buyHtml() {
  const list = FL.supply.докупить || [];
  if (!list.length) {
    return `<div class="cx-card"><div class="cx-empty"><b>Докупать ничего не нужно</b>Сырья на складе хватает на все заказы у снабженца, и ни одна позиция не ниже минимального остатка</div></div>`;
  }
  const rows = list.map((r) => `<tr>
      <td><b>${esc(r.материал)}</b>${r.на_складе ? '' : '<div class="cx-hint">нет на складе сырья</div>'}</td>
      <td>${r.цвет ? esc(r.цвет) : '<span class="cx-hint">любой</span>'}</td>
      <td class="num"><b class="${r.не_хватает > 0 ? 'cx-neg' : ''}">${flQty(r.докупить, r.ед)}</b>
        ${!r.не_хватает && r.мин ? '<div class="cx-hint">до мин. остатка</div>' : ''}</td>
      <td class="num">${r.нужно ? flStockQty(r.нужно, r.ед) : '—'}${r.заказы.length ? `<div class="cx-hint">${flBuyOrders(r)}</div>` : ''}
        ${r.единицы_не_сходятся.length ? `<div class="cx-neg">не сложено — другие единицы: ${r.единицы_не_сходятся.map(esc).join('; ')}</div>` : ''}</td>
      <td class="num">${r.на_складе ? (r.свободно < 0 ? `<span class="cx-neg">${flStockQty(r.свободно, r.ед)}</span><div class="cx-hint">партиям в крое не хватает</div>` : flStockQty(r.свободно, r.ед)) : '—'}</td>
      <td class="num">${r.мин ? flStockQty(r.мин, r.ед) : '—'}</td>
      <td class="num">${r.заказано ? flStockQty(r.заказано, r.ед) : '—'}</td>
    </tr>`).join('');
  const short = list.filter((r) => r.не_хватает > 0).length;
  return `<div class="cx-card"><div class="cx-card-h"><h3>Что докупить</h3>
      <span class="cx-hint">${short ? `не хватает заказам: <b>${nf(short)}</b> поз.` : 'заказам хватает'} · всего в списке ${nf(list.length)}</span></div>
    <div class="cx-card-b">
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Докупить</th><th class="num">Нужно заказам</th>
          <th class="num">Свободно на складе</th><th class="num">Мин. остаток</th><th class="num">Уже заказано</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn primary" data-act="fl-buy-print">Печать</button>
        <button class="btn" data-act="fl-buy-csv">Скачать для Excel</button>
      </div>
      <div class="cx-hint" style="margin-top:10px">Считается по всем заказам во вкладке «Заказы» сразу: докупить = нужно заказам + мин. остаток − свободно на складе − уже заказано.
        «Свободно» — остаток минус то, что ещё нужно партиям в крое. «Уже заказано» — строки заказа со статусом «заказано» и количеством в колонке «Есть / заказано».</div>
    </div></div>`;
}

// одна строка для печати и Excel: число в единицах склада (граммы — подсказкой не нужны)
function flBuyPlain(r) {
  return {
    материал: r.материал, цвет: r.цвет || 'любой', ед: r.ед,
    нужно: r.нужно, заказы: r.заказы.map((z) => `№${z.номер}: ${String(z.нужно).replace('.', ',')} ${r.ед}`).join('; '),
    свободно: r.на_складе ? r.свободно : '', мин: r.мин || '', заказано: r.заказано || '', докупить: r.докупить,
  };
}

function flBuyPrint() {
  const list = (FL.supply.докупить || []).map(flBuyPlain);
  const today = new Date().toLocaleDateString('ru-RU');
  const frame = document.createElement('iframe');
  frame.style.cssText = 'position:fixed;width:0;height:0;border:0;right:0;bottom:0';
  document.body.appendChild(frame);
  const doc = frame.contentDocument;
  doc.open();
  doc.write(`<!doctype html><html><head><meta charset="utf-8"><title>Что докупить · ${today}</title><style>
    body { font: 12px/1.4 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; margin: 14mm; color: #000; }
    h1 { font-size: 18px; margin: 0 0 4px; } .sub { color: #555; margin-bottom: 12px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #999; padding: 5px 7px; vertical-align: top; text-align: left; }
    th { background: #eee; font-size: 11px; } .num { text-align: right; white-space: nowrap; }
    td.buy { font-weight: 700; font-size: 14px; } .z { color: #555; font-size: 10px; }
  </style></head><body>
    <h1>Что докупить</h1><div class="sub">${today} · заказы у снабженца · позиций ${list.length}</div>
    <table><thead><tr><th>Материал</th><th>Цвет</th><th class="num">Докупить</th><th class="num">Нужно заказам</th>
      <th class="num">Свободно</th><th class="num">Уже заказано</th><th>Отметка</th></tr></thead>
    <tbody>${list.map((r) => `<tr><td>${esc(r.материал)}</td><td>${esc(r.цвет)}</td>
      <td class="num buy">${nf(r.докупить)} ${esc(r.ед)}</td>
      <td class="num">${r.нужно ? nf(r.нужно) + ' ' + esc(r.ед) : '—'}${r.заказы ? `<div class="z">${esc(r.заказы)}</div>` : ''}</td>
      <td class="num">${r.свободно === '' ? '—' : nf(r.свободно) + ' ' + esc(r.ед)}</td>
      <td class="num">${r.заказано ? nf(r.заказано) + ' ' + esc(r.ед) : '—'}</td><td style="width:22mm"></td></tr>`).join('')}</tbody></table>
  </body></html>`);
  doc.close();
  setTimeout(() => {
    frame.contentWindow.focus();
    frame.contentWindow.print();
    setTimeout(() => frame.parentNode && frame.parentNode.removeChild(frame), 60000);
  }, 200);
}

// CSV для Excel: разделитель «;», десятичная запятая и BOM — русский Excel открывает без вопросов
function flBuyCsv() {
  const list = (FL.supply.докупить || []).map(flBuyPlain);
  const cell = (v) => {
    const s = typeof v === 'number' ? String(v).replace('.', ',') : String(v == null ? '' : v);
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = ['Материал', 'Цвет', 'Ед.', 'Докупить', 'Нужно заказам', 'По заказам', 'Свободно на складе', 'Мин. остаток', 'Уже заказано'];
  const lines = [head, ...list.map((r) => [r.материал, r.цвет, r.ед, r.докупить, r.нужно, r.заказы, r.свободно, r.мин, r.заказано])];
  const text = '﻿' + lines.map((l) => l.map(cell).join(';')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = `dokupit_${new Date().toISOString().slice(0, 10)}.csv`;  // латиница: кириллицу браузер может заменить на «download»
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); document.body.removeChild(a); }, 1000);
}

function supplyOrdersHtml() {
  const q = FL.supply.очередь || [];
  const o = q.find((x) => x.номер === FL.num);
  return flQueue(q, 'fl-supply-open', 'Сюда попадают заказы с утверждённой картой конструктора') + (o ? supplyCardHtml(o) : '');
}

function supplyCardHtml(o) {
  const card = (o.карта || []).map((c) => `<tr><td>${esc(c.модель)}</td><td>${esc(c.цвет)}</td><td>${esc(c.размер)}</td>
    <td class="num">${nf(c.заказано)}</td><td class="num"><b>${nf(c.итог)}</b></td><td>${esc(c.характеристики)}</td></tr>`).join('');
  const sts = FL.supply.статусы || [];
  const mats = (o.сырьё || []).map((m, i) => `<tr>
      <td>${esc(m.материал)}</td><td>${esc(m.цвет)}</td><td class="num"><b>${flQty(m.нужно, m.ед)}</b></td>
      <td class="num">${flStockCell(m)}</td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-mat="${i}|есть" value="${esc(m.есть || '')}"></td>
      <td><select class="input" data-fl-mat="${i}|статус"><option value="">—</option>${sts.map((s) => `<option ${m.статус === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></td>
      <td><input class="input" data-fl-mat="${i}|комментарий" value="${esc(m.комментарий)}"></td>
    </tr>`).join('');
  const miss = o.без_спецификации || [];
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Заказ №${esc(o.номер)} · карта конструктора</h3><span class="cx-hint">${nf(o.штук)} шт по карте</span></div>
    <div class="cx-card-b">
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Модель</th><th>Цвет</th><th>Размер</th><th class="num">Заказано</th><th class="num">Итог</th><th>Характеристики</th></tr></thead>
        <tbody>${card}</tbody></table></div>
      <h4 style="margin:18px 0 8px">Расход сырья: на 1 шт и на весь заказ</h4>
      <div class="cx-hint" style="margin-bottom:8px">Считается по спецификации модели: у каждого размера своя норма × (1 + запас на отходы) × количество. Эти же цифры видят технолог и закройщик.</div>
      ${(o.расход || []).map(flSpecTableHtml).join('')}
      <h4 style="margin:18px 0 8px">Сырьё на заказ — по цветам</h4>
      ${miss.length ? `<div class="cx-notice warn">Нет нормы расхода для: <b>${miss.map(esc).join('; ')}</b> — это сырьё в расчёт не вошло. Заполните во вкладке «Справочник товара».</div>` : ''}
      ${mats ? `<div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Нужно</th><th class="num">На складе</th><th>Есть / заказано</th><th>Статус</th><th>Комментарий</th></tr></thead>
        <tbody>${mats}</tbody></table></div>
        <div class="cx-hint" style="margin-top:6px">«На складе» — остаток из вкладки «Склад сырья»; «свободно» — за вычетом того, что нужно заказам в крое. Склад спишет сырьё сам, когда закройщик сохранит крой.</div>` : ''}
      <div class="cx-btn-row" style="margin-top:14px">
        <button class="btn" data-act="fl-supply-save">Сохранить</button>
        <button class="btn primary" data-act="fl-supply-done">Сырьё готово — передать технологу</button>
      </div>
    </div></div>`;
}

function flOpenSupply(numStr) {
  const o = (FL.supply.очередь || []).find((x) => x.номер === numStr);
  if (!o) return;
  FL.num = numStr;
  FL.rows = (o.сырьё || []).map((m) => ({ ...m }));
  render();
}

async function flSaveSupply(done) {
  if (done && !confirm('Передать заказ технологу?')) return;
  try {
    await api(`${API}/supply`, { method: 'POST', body: JSON.stringify({ номер: FL.num, готово: done, строки: FL.rows }) });
    await loadSupply();
    await refreshOrders();
    if (done) FL.num = '';
    else flOpenSupply(FL.num);
    render();
    toast(done ? 'Заказ передан технологу' : 'Сохранено', 'ok');
  } catch (err) { toast(err.message, 'err'); }
}

// названия материалов для подсказки: склад + то, что уже есть в справочнике товара
function flMaterialNames() {
  const out = new Map();
  (FL.supply.материалы || []).forEach((m) => out.set(m.toLowerCase(), m));
  Object.values(FL.supply.спецификации || {}).forEach((lines) => lines.forEach((l) => { if (!out.has(l.материал.toLowerCase())) out.set(l.материал.toLowerCase(), l.материал); }));
  return [...out.values()].sort((a, b) => a.localeCompare(b, 'ru'));
}

// материалы из строк, которых ещё нет на складе: появятся после первого прихода или рулона
function flBomUnknownHtml() {
  const known = new Set((FL.supply.материалы || []).map((m) => m.toLowerCase()));
  const names = [...new Set(FL.bomRows.map((r) => String(r.материал || '').trim()).filter((m) => m && !known.has(m.toLowerCase())))];
  return names.length ? `<div class="cx-notice" style="margin-top:12px">Этих материалов ещё нет на складе: <b>${names.map(esc).join(', ')}</b>. Они появятся там после первого прихода (вкладка «Склад сырья») или рулона — тогда расход начнёт списываться.</div>` : '';
}

// размеры, которые можно предложить: сетки из справочника + уже встречавшиеся у модели
function flAllSizes() {
  const out = [];
  (ST.refs.размеры || []).forEach((g) => (g.размеры || []).forEach((v) => { if (!out.includes(String(v))) out.push(String(v)); }));
  return out;
}

function flSizeSort(list) {
  return list.slice().sort((x, y) => {
    const a = parseFloat(String(x).replace(',', '.')), b = parseFloat(String(y).replace(',', '.'));
    if (!isNaN(a) && !isNaN(b) && a !== b) return a - b;
    return String(x).localeCompare(String(y), 'ru');
  });
}

// строки спецификации из таблицы (плоский список с колонкой «размер») → строки редактора «материал × размер»
function flBomToRows(lines) {
  const rows = [];
  const idx = {};
  const sizes = [];
  (lines || []).forEach((l) => {
    const k = `${l.материал}|${l.цвет}`;
    let r = idx[k];
    if (!r) { r = idx[k] = { ...FL_NEW_ROW(), материал: l.материал, цвет: l.цвет, ед: l.ед || 'м', параметры: l.параметры || '', запас: l.запас || '' }; rows.push(r); }
    if (l.размер) { r.размеры[l.размер] = l.норма; if (!sizes.includes(l.размер)) sizes.push(l.размер); }
    else { r.норма = l.норма; r.ед = l.ед || r.ед; r.параметры = l.параметры || r.параметры; r.запас = l.запас || r.запас; }
  });
  return { rows, sizes };
}

function refHtml() {
  return `<div class="cx-hero compact"><div><h1>Справочник товара</h1>
      <div class="cx-sub">Сколько сырья уходит на одну штуку артикула в каждом размере. По нему снабжение считает заказ, а склад списывает сырьё при крое</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    ${bomHtml()}`;
}

function bomHtml() {
  const all = FL.supply.спецификации || {};
  const models = (ST.refs.модели || []).map((m) => m.модель);
  Object.keys(all).forEach((m) => { if (!models.includes(m)) models.push(m); });
  const chips = models.map((m) => `<button class="rt-chip ${m === FL.bomModel ? 'on' : ''}" data-act="fl-bom-pick" data-model="${esc(m)}">${esc(m)}${all[m] ? ` · ${flBomToRows(all[m]).rows.length}` : ''}</button>`).join('');
  const sizeHead = FL.bomSizes.map((sz) => `<th class="num">${esc(sz)} <button class="btn ghost cx-xs" data-act="fl-bom-size-del" data-size="${esc(sz)}" title="Убрать размер ${esc(sz)}">✕</button></th>`).join('');
  const rows = FL.bomRows.map((r, i) => `<tr>
      <td><input class="input" data-fl-bom="${i}|материал" value="${esc(r.материал)}" placeholder="ткань, нитки, молния…" list="fl-mats"></td>
      <td><input class="input" data-fl-bom="${i}|цвет" value="${esc(r.цвет)}" placeholder="в цвет изделия" list="fl-colors"></td>
      <td><input class="input cx-mini" data-fl-bom="${i}|ед" value="${esc(r.ед || 'м')}" list="fl-units"></td>
      <td><input class="input cx-mini" type="number" min="0" max="100" step="any" data-fl-bom="${i}|запас" value="${esc(r.запас || '')}" placeholder="0"></td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-bom="${i}|норма" value="${esc(r.норма)}" placeholder="—" title="Норма для всех размеров, у которых своя не указана"></td>
      ${FL.bomSizes.map((sz) => `<td><input class="input cx-mini" type="number" min="0" step="any" data-fl-bsz="${i}|${esc(sz)}" value="${esc(r.размеры[sz] ?? '')}" placeholder="${r.норма !== '' && r.норма != null ? esc(r.норма) : '—'}"></td>`).join('')}
      <td><input class="input" data-fl-bom="${i}|параметры" value="${esc(r.параметры)}" placeholder="ширина, состав…"></td>
      <td><button class="btn ghost" data-act="fl-bom-del" data-i="${i}">✕</button></td></tr>`).join('');
  const seen = (FL.supply.размеры || {})[FL.bomModel] || [];
  const missing = seen.filter((sz) => !FL.bomSizes.includes(sz));
  return `<div class="cx-card"><div class="cx-card-h"><h3>Расход сырья на 1 шт по артикулу и размерам</h3></div>
    <div class="cx-card-b">
      <div class="cc-wait">${chips || '<span class="cx-hint">Справочник моделей пуст</span>'}</div>
      ${FL.bomModel ? `
        <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
        <datalist id="fl-mats">${flMaterialNames().map((m) => `<option value="${esc(m)}">`).join('')}</datalist>
        <datalist id="fl-sizes">${flAllSizes().map((v) => `<option value="${esc(v)}">`).join('')}</datalist>
        <div class="cx-hint" style="margin-top:12px">У каждого размера свой расход: впишите норму на 1 шт в колонку нужного размера. Пустая ячейка размера — действует «Общая норма» из строки.</div>
        <div class="cx-scroll" style="margin-top:8px"><table class="cx-table cx-sizetable">
          <thead><tr><th>Сырьё / материал</th><th>Цвет</th><th>Ед.</th><th title="Запас на отходы и подрезку, %">Запас, %</th><th class="num" title="Для размеров, где своя норма не указана">Общая норма</th>${sizeHead}<th>Доп. параметры</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <datalist id="fl-units"><option value="г"><option value="кг"><option value="м"><option value="шт"><option value="бобина"></datalist>
        <div class="cx-btn-row" style="margin-top:10px;align-items:center">
          <input class="input cx-mini" id="fl-new-size" list="fl-sizes" placeholder="размер" style="max-width:110px">
          <button class="btn" data-act="fl-bom-size-add">+ Размер</button>
          ${missing.length ? `<button class="btn" data-act="fl-bom-size-all" title="Размеры, которые есть в заказах этой модели">+ Размеры из заказов (${missing.map(esc).join(', ')})</button>` : ''}
        </div>
        <div class="cx-hint" style="margin-top:8px">Норму можно вносить в граммах («г») или килограммах («кг») — закройщик и технолог увидят вес. Запас — на отходы, его добавляют к норме.</div>
        <div id="fl-bom-unknown">${flBomUnknownHtml()}</div>
        <div id="fl-bom-preview" style="margin-top:12px">${flBomPreviewHtml()}</div>
        <div class="cx-btn-row" style="margin-top:10px">
          <button class="btn" data-act="fl-bom-add">+ Материал</button>
          <button class="btn primary" data-act="fl-bom-save">Сохранить спецификацию ${esc(FL.bomModel)}</button>
        </div>` : '<div class="cx-hint" style="margin-top:10px">Выберите артикул</div>'}
    </div></div>`;
}

// «Расход на 1 шт» прямо при вводе спецификации — как его увидят технолог и закройщик
function flBomPreviewHtml() {
  const sizes = FL.bomSizes.length ? FL.bomSizes : [''];
  const rows = FL.bomRows.filter((r) => String(r.материал || '').trim()).map((r) => {
    const by = {};
    sizes.forEach((sz) => {
      const own = sz ? r.размеры[sz] : '';
      const norm = (own !== '' && own != null) ? num(own) : num(r.норма);
      if (norm > 0) by[sz] = { на_1_шт: Math.round(norm * (1 + num(r.запас) / 100) * 10000) / 10000 };
    });
    return { материал: r.материал, цвет: r.цвет, ед: r.ед || 'м', параметры: '', по_размерам: by };
  }).filter((r) => Object.keys(r.по_размерам).length);
  if (!rows.length) return '';
  return `<div class="cx-hint" style="margin-bottom:4px"><b>Так увидят технолог и закройщик</b> — на 1 шт, с запасом на отходы</div>
    ${flSizeTableHtml(rows, sizes.map((sz) => ({ размер: sz, штук: 0 })), '')}`;
}

function flMoveQty(m) {
  const sign = m.изменение > 0 ? '+' : m.изменение < 0 ? '−' : '';
  return `<span class="${m.изменение < 0 ? 'cx-neg' : m.изменение > 0 ? 'cx-pos' : ''}">${sign}${flStockQty(Math.abs(m.изменение), m.ед)}</span>`;
}

function stockHtml() {
  const S = FL.stock, f = FL.stockForm;
  const pos = (S.позиции || []).map((x) => `<tr class="fl-pick" data-act="fl-stock-pick" data-mat="${esc(x.материал)}" data-color="${esc(x.цвет)}" data-unit="${esc(x.ед)}" title="Нажмите, чтобы внести приход или остаток по этой позиции">
      <td><b>${esc(x.материал)}</b></td>
      <td>${x.цвет ? esc(x.цвет) : '<span class="cx-hint">без цвета</span>'}</td>
      <td class="num ${x.минус ? 'cx-neg' : ''}"><b>${flStockQty(x.остаток, x.ед)}</b></td>
      <td class="num">${x.резерв ? flStockQty(x.резерв, x.ед) : '<span class="cx-hint">—</span>'}</td>
      <td class="num ${x.свободно < 0 ? 'cx-neg' : ''}">${flStockQty(x.свободно, x.ед)}</td>
      <td>${x.минус ? '<span class="cx-neg">в минусе</span>' : x.не_хватает ? '<span class="cx-neg">не хватает под партии</span>' : x.мало ? '<span class="cx-low">ниже минимума</span>' : '<span class="cx-hint">норма</span>'}</td></tr>`).join('');
  const names = [...new Set([...(S.позиции || []).map((x) => x.материал), ...flMaterialNames()])];
  const jr = (S.движения || []).slice(0, 80).map((m) => `<tr>
      <td>${esc(m.дата)}</td><td>${esc(m.тип)}</td><td>${esc(m.материал)}${m.цвет ? ` · ${esc(m.цвет)}` : ''}</td>
      <td class="num">${flMoveQty(m)}</td><td>${m.партия ? `партия ${esc(m.партия)}${m.настил ? ` / настил ${esc(m.настил)}` : ''}` : (m.заказ ? `заказ ${esc(m.заказ)}` : '')}</td>
      <td>${esc(m.кто)}</td><td class="cx-hint">${esc(m.комментарий)}</td></tr>`).join('');
  return `<div class="cx-hero compact"><div><h1>Склад сырья</h1>
      <div class="cx-sub">Остатки сырья по материалу и цвету. Склад сам списывает сырьё, когда закройщик сохраняет крой: норма размера × раскроено</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-card"><div class="cx-card-h"><h3>Что на складе</h3><span class="cx-hint">«резерв» — сколько ещё понадобится партиям в крое</span></div>
      <div class="cx-card-b"><div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Остаток</th><th class="num">Резерв</th><th class="num">Свободно</th><th>Состояние</th></tr></thead>
        <tbody>${pos || '<tr><td colspan="6" class="cx-empty">Склад пуст. Внесите остатки ниже: «Остаток по факту» для того, что уже лежит, и «Принять» для новых поступлений.</td></tr>'}</tbody></table></div></div></div>
    <div class="cx-card" style="margin-top:14px"><div class="cx-card-h"><h3>Принять сырьё или сверить остаток</h3></div>
      <div class="cx-card-b">
        <datalist id="fl-s-mats">${names.map((m) => `<option value="${esc(m)}">`).join('')}</datalist>
        <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
        <div class="cx-formgrid">
          <div class="cx-field"><label>Материал</label><input class="input" data-fl-sf="материал" value="${esc(f.материал)}" list="fl-s-mats" placeholder="Футер двунитка"></div>
          <div class="cx-field"><label>Цвет</label><input class="input" data-fl-sf="цвет" value="${esc(f.цвет)}" list="fl-colors" placeholder="пусто — не делится по цветам"></div>
          <div class="cx-field"><label>Количество</label><input class="input" data-fl-sf="количество" value="${esc(f.количество)}" inputmode="decimal"></div>
          <div class="cx-field"><label>Ед.</label><select class="input" data-fl-sf="ед">${(S.единицы || []).map((u) => `<option ${u === f.ед ? 'selected' : ''}>${esc(u)}</option>`).join('')}</select></div>
          <div class="cx-field"><label>Комментарий</label><input class="input" data-fl-sf="комментарий" value="${esc(f.комментарий)}" placeholder="накладная, поставщик…"></div>
        </div>
        <div class="cx-btn-row" style="margin-top:12px">
          <button class="btn primary" data-act="fl-stock-receive">Принять на склад (+)</button>
          <button class="btn" data-act="fl-stock-adjust">Остаток по факту = это количество</button>
        </div>
        <div class="cx-hint" style="margin-top:8px">Вес можно вносить в граммах или килограммах — склад ведёт килограммы. Рулон, внесённый во вкладке «Снабжение → Рулоны», приходует вес сам. Цвет не указывайте у материала, который не делят по цветам (молния, нитки): тогда он подойдёт ко всем цветам. Нажмите строку таблицы, чтобы подставить позицию.</div>
      </div></div>
    <div class="cx-card" style="margin-top:14px"><div class="cx-card-h"><h3>Загрузить остатки списком</h3><span class="cx-hint">для первого запуска: вставьте таблицу из Excel</span></div>
      <div class="cx-card-b">
        <textarea class="input" data-fl-bulk rows="6" style="width:100%;font-family:monospace" placeholder="материал; цвет; количество; ед.; мин. остаток&#10;Футер двунитка; бежевый; 120; кг; 20&#10;Резинка; чёрный; 300; м&#10;Нитки; ; 4000; г; 1">${esc(FL.stockBulk)}</textarea>
        <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-stock-import">Загрузить остатки</button></div>
        <div class="cx-hint" style="margin-top:8px">Каждая строка: материал, цвет, количество, ед., мин. остаток (последние два можно не писать). Разделитель — табуляция (копирование из Excel) или «;». Это остаток по факту: повторная загрузка того же списка ничего не меняет. Если в списке есть ошибка, склад не меняется совсем, и вы увидите, в какой строке.</div>
      </div></div>
    <div class="cx-card" style="margin-top:14px"><div class="cx-card-h"><h3>Журнал движений</h3><span class="cx-hint">последние ${nf((S.движения || []).slice(0, 80).length)}</span></div>
      <div class="cx-card-b"><div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Когда</th><th>Тип</th><th>Материал</th><th class="num">Изменение</th><th>Откуда</th><th>Кто</th><th>Комментарий</th></tr></thead>
        <tbody>${jr || '<tr><td colspan="7" class="cx-empty">Движений пока нет</td></tr>'}</tbody></table></div></div></div>`;
}

function rollsHtml() {
  const list = FL.supply.рулоны || [];
  return `<div class="cx-card"><div class="cx-card-h"><h3>Поступили рулоны</h3><span class="cx-hint">закройщик выбирает рулон из этого списка</span></div>
    <div class="cx-card-b">
      <div class="cx-formgrid">
        <div class="cx-field"><label>Код рулона</label><input class="input" id="fl-r-код"></div>
        <div class="cx-field"><label>Материал</label><input class="input" id="fl-r-материал"></div>
        <div class="cx-field"><label>Цвет</label><input class="input" id="fl-r-цвет" list="fl-colors"></div>
        <div class="cx-field"><label>Граммаж, г/м²</label><input class="input" id="fl-r-граммы" inputmode="decimal"></div>
        <div class="cx-field"><label>Вес, кг</label><input class="input" id="fl-r-вес" inputmode="decimal"></div>
        <div class="cx-field"><label>Под заказ №</label><input class="input" id="fl-r-заказ" inputmode="numeric"></div>
        <div class="cx-field"><label>Поставщик</label><input class="input" id="fl-r-поставщик"></div>
      </div>
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      <div class="cx-btn-row" style="margin-top:12px"><button class="btn primary" data-act="fl-roll-add">Внести рулон</button></div>
      <div class="cx-scroll" style="margin-top:14px"><table class="cx-table">
        <thead><tr><th>Код</th><th>Дата</th><th>Материал</th><th>Цвет</th><th class="num">г/м²</th><th class="num">кг</th><th>Заказ</th><th>Поставщик</th><th>Внёс</th></tr></thead>
        <tbody>${list.map((r) => `<tr><td><b>${esc(r.код)}</b></td><td>${esc(r.дата)}</td><td>${esc(r.материал)}</td><td>${esc(r.цвет)}</td>
          <td class="num">${esc(r.граммы)}</td><td class="num">${esc(r.вес)}</td><td>${esc(r.заказ)}</td><td>${esc(r.поставщик)}</td><td>${esc(r.внёс)}</td></tr>`).join('')
          || '<tr><td colspan="9" class="cx-empty">Рулонов пока нет</td></tr>'}</tbody></table></div>
    </div></div>`;
}

const FL_ROLL_FIELDS = ['код', 'материал', 'цвет', 'граммы', 'вес', 'заказ', 'поставщик'];

async function flPost(path, body, okText) {
  try {
    const res = await api(`${API}${path}`, { method: 'POST', body: JSON.stringify(body) });
    await loadSupply();
    render();
    toast(typeof okText === 'function' ? okText(res) : okText, 'ok', 5000);
    return res || true;
  } catch (err) { toast(err.message, 'err'); return false; }
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="fl-"]');
  if (!el || !['design', 'supply', 'ref', 'stock'].includes(ST.view)) return;
  ev.stopPropagation();
  const act = el.dataset.act;
  if (act === 'fl-design-open') return flOpenDesign(el.dataset.num);
  if (act === 'fl-supply-open') return flOpenSupply(el.dataset.num);
  if (act === 'fl-g-add') {
    const last = FL.grid.groups[FL.grid.groups.length - 1] || {};
    FL.grid.groups.push({ модель: last.модель || '', цвет: '', хар: '', хар_разные: false, хар_тронуты: false, cells: {} });
    render();
    const inp = document.querySelector(`[data-fl-g="${FL.grid.groups.length - 1}|цвет"]`);
    if (inp) inp.focus();
    return;
  }
  if (act === 'fl-g-del') {
    const g = FL.grid.groups[Number(el.dataset.i)];
    const n = FL.grid.sizes.reduce((s, sz) => s + flCellQty(g.cells[sz]), 0);
    if (n && !confirm(`Убрать ${g.модель} · ${g.цвет} (${nf(n)} шт) из карты?`)) return;
    FL.grid.groups.splice(Number(el.dataset.i), 1);
    return render();
  }
  if (act === 'fl-g-size-add') {
    const v = String(($('#fl-g-size') || {}).value || '').trim();
    if (!v) return toast('Впишите размер, например 50', 'err');
    if (FL.grid.sizes.includes(v)) return toast(`Размер ${v} уже есть`, 'err');
    FL.grid.sizes = flSizeSort([...FL.grid.sizes, v]);
    return render();
  }
  if (act === 'fl-g-size-del') {
    const sz = FL.grid.sizes[Number(el.dataset.i)];
    const n = FL.grid.groups.reduce((s, g) => s + flCellQty(g.cells[sz]), 0);
    if (n && !confirm(`Убрать размер ${sz || 'без размера'} (${nf(n)} шт) из карты?`)) return;
    FL.grid.sizes = FL.grid.sizes.filter((x) => x !== sz);
    FL.grid.groups.forEach((g) => { delete g.cells[sz]; });
    return render();
  }
  if (act === 'fl-design-save' || act === 'fl-design-done') {
    el.disabled = true; await flSaveDesign(act === 'fl-design-done'); el.disabled = false; return;
  }
  if (act === 'fl-supply-save' || act === 'fl-supply-done') {
    el.disabled = true; await flSaveSupply(act === 'fl-supply-done'); el.disabled = false; return;
  }
  if (act === 'fl-sub') { FL.supplyTab = el.dataset.tab; FL.num = ''; return render(); }
  if (act === 'fl-buy-print') return flBuyPrint();
  if (act === 'fl-buy-csv') return flBuyCsv();
  if (act === 'fl-bom-pick') {
    FL.bomModel = el.dataset.model;
    const got = flBomToRows((FL.supply.спецификации || {})[FL.bomModel] || []);
    FL.bomRows = got.rows;
    // колонки размеров: из спецификации и из заказов этой модели
    FL.bomSizes = flSizeSort([...new Set([...got.sizes, ...(((FL.supply.размеры || {})[FL.bomModel]) || [])])]);
    if (!FL.bomRows.length) FL.bomRows.push(FL_NEW_ROW());
    return render();
  }
  if (act === 'fl-bom-add') { FL.bomRows.push(FL_NEW_ROW()); return render(); }
  if (act === 'fl-bom-del') { FL.bomRows.splice(Number(el.dataset.i), 1); return render(); }
  if (act === 'fl-bom-size-add') {
    const v = String(($('#fl-new-size') || {}).value || '').trim();
    if (!v) return toast('Впишите размер, например 44', 'err');
    if (!FL.bomSizes.includes(v)) FL.bomSizes = flSizeSort([...FL.bomSizes, v]);
    return render();
  }
  if (act === 'fl-bom-size-all') {
    FL.bomSizes = flSizeSort([...new Set([...FL.bomSizes, ...(((FL.supply.размеры || {})[FL.bomModel]) || [])])]);
    return render();
  }
  if (act === 'fl-bom-size-del') {
    const sz = el.dataset.size;
    const filled = FL.bomRows.some((r) => r.размеры[sz] !== '' && r.размеры[sz] != null);
    if (filled && !confirm(`Убрать размер ${sz}? Введённые для него нормы пропадут.`)) return;
    FL.bomSizes = FL.bomSizes.filter((x) => x !== sz);
    FL.bomRows.forEach((r) => { delete r.размеры[sz]; });
    return render();
  }
  if (act === 'fl-bom-save') {
    const rows = FL.bomRows.map((r) => {
      const by = {};
      FL.bomSizes.forEach((sz) => { if (r.размеры[sz] !== '' && r.размеры[sz] != null) by[sz] = r.размеры[sz]; });
      return { материал: r.материал, цвет: r.цвет, ед: r.ед, запас: r.запас, параметры: r.параметры, норма: r.норма, по_размерам: by };
    });
    await flPost('/supply/bom', { модель: FL.bomModel, строки: rows }, `Спецификация ${FL.bomModel} сохранена`);
    return;
  }
  if (act === 'fl-stock-pick') {
    FL.stockForm = { ...FL.stockForm, материал: el.dataset.mat, цвет: el.dataset.color, ед: el.dataset.unit };
    return render();
  }
  if (act === 'fl-stock-receive' || act === 'fl-stock-adjust') {
    const f = FL.stockForm;
    const receive = act === 'fl-stock-receive';
    const body = { материал: f.материал, цвет: f.цвет, ед: f.ед, комментарий: f.комментарий };
    body[receive ? 'количество' : 'остаток'] = f.количество;
    el.disabled = true;
    try {
      const res = await api(`${API}/stock/${receive ? 'receive' : 'adjust'}`, { method: 'POST', body: JSON.stringify(body) });
      await loadStock();
      FL.stockForm = { ...FL.stockForm, количество: '', комментарий: '' };
      render();
      toast(receive ? `Принято: ${res.материал}${res.цвет ? ' ' + res.цвет : ''} +${nf(res.приход)} ${res.ед} · на складе ${nf(res.остаток)} ${res.ед}`
        : `${res.материал}${res.цвет ? ' ' + res.цвет : ''}: остаток теперь ${nf(res.остаток)} ${res.ед}`, 'ok', 5000);
    } catch (err) { toast(err.message, 'err'); }
    el.disabled = false;
    return;
  }
  if (act === 'fl-stock-import') {
    el.disabled = true;
    try {
      const r = await api(`${API}/stock/import`, { method: 'POST', body: JSON.stringify({ текст: FL.stockBulk }) });
      await loadStock();
      FL.stockBulk = '';
      render();
      toast(`Загружено строк: ${r.строк}. Новых позиций ${r.новых}, изменено ${r.изменено}, без изменений ${r.без_изменений}`, 'ok', 6000);
    } catch (err) { toast(err.message, 'err', 12000); }
    el.disabled = false;
    return;
  }
  if (act === 'fl-roll-add') {
    const body = {};
    FL_ROLL_FIELDS.forEach((f) => { body[f] = ($(`#fl-r-${f}`) || {}).value || ''; });
    if (await flPost('/supply/roll', body, (r) => `Рулон ${body.код} внесён${r && r.склад ? ' · ' + r.склад.сообщение : ''}`)) FL.supplyTab = 'rolls';
  }
}, true);

document.addEventListener('input', (ev) => {
  const t = ev.target;
  const pick = (attr, list) => {
    const [i, f] = t.dataset[attr].split('|');
    list[Number(i)][f] = t.value;
  };
  if (t.dataset.flG) {
    const [i, f] = t.dataset.flG.split('|');
    const g = FL.grid.groups[Number(i)];
    if (f === 'хар') { g.хар = t.value; g.хар_тронуты = true; } else g[f] = t.value;
  }
  if (t.dataset.flGc) {
    const raw = t.dataset.flGc;
    const cut = raw.indexOf('|');
    const g = FL.grid.groups[Number(raw.slice(0, cut))];
    const sz = raw.slice(cut + 1);
    const c = g.cells[sz] || (g.cells[sz] = { итог: '', заказано: 0, был: false, хар: '' });
    c.итог = t.value;
    t.classList.toggle('diff', c.был && t.value.trim() !== '' && Math.round(num(t.value)) !== c.заказано);
    flGridRefresh();
  }
  if (t.dataset.flMat) pick('flMat', FL.rows);
  if (t.dataset.flSf) FL.stockForm[t.dataset.flSf] = t.value;
  if (t.dataset.flBulk !== undefined) FL.stockBulk = t.value;
  if (t.dataset.flBom || t.dataset.flBsz) {
    if (t.dataset.flBom) pick('flBom', FL.bomRows);
    else {
      const raw = t.dataset.flBsz;
      const cut = raw.indexOf('|');
      FL.bomRows[Number(raw.slice(0, cut))].размеры[raw.slice(cut + 1)] = t.value;
    }
    const box = document.getElementById('fl-bom-preview');
    if (box) box.innerHTML = flBomPreviewHtml();
    const unk = document.getElementById('fl-bom-unknown');
    if (unk) unk.innerHTML = flBomUnknownHtml();
  }
});

document.addEventListener('change', (ev) => {  // выбор из списка (ед.) тоже сохраняем
  const t = ev.target;
  if (t.dataset && t.dataset.flSf) FL.stockForm[t.dataset.flSf] = t.value;
});
