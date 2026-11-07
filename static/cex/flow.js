'use strict';

/* Модуль «Цех» · поток заказа: конструктор (производственная карта) → снабженец (сырьё) → технолог. */

const FL = { design: { очередь: [], история: {} }, supply: { очередь: [], спецификации: {}, размеры: {}, рулоны: [], статусы: [] },
  num: '', rows: [], bomModel: '', bomRows: [], bomSizes: [], supplyTab: 'orders' };

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

function flNoSpecHtml(model) {
  return `<div class="cx-notice warn">Для модели <b>${esc(model)}</b> нет спецификации — расход сырья не рассчитан. Её вносит снабженец (вкладка «Снабжение» → «Спецификации»).</div>`;
}

function flNoNormHtml(model, sizes) {
  return sizes && sizes.length
    ? `<div class="cx-notice warn">Для модели <b>${esc(model)}</b> нет нормы расхода на размер: <b>${sizes.map(esc).join(', ')}</b> — сырьё на эти штуки не посчитано. Норму вносит снабженец (вкладка «Спецификации»).</div>` : '';
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

function flRollsHint(m) {
  if (!m.рулоны) return '<span class="cx-hint">—</span>';
  const r = m.рулоны;
  return `${nf(r.рулонов)} рул. · ${nf(r.кг)} кг${r.под_заказ_кг ? `<div class="cx-hint">под этот заказ ${nf(r.под_заказ_кг)} кг</div>` : ''}`;
}

async function loadDesign() { FL.design = await api(`${API}/design`); }
async function loadSupply() { FL.supply = await api(`${API}/supply`); }

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

function designCardHtml(o) {
  const rows = FL.rows.map((r, i) => `<tr>
      <td><input class="input" data-fl-row="${i}|модель" value="${esc(r.модель)}" list="fl-models"></td>
      <td><input class="input" data-fl-row="${i}|цвет" value="${esc(r.цвет)}" list="fl-colors"></td>
      <td><input class="input cx-mini" data-fl-row="${i}|размер" value="${esc(r.размер)}"></td>
      <td class="num">${nf(r.заказано)}</td>
      <td><input class="input cx-mini" type="number" min="0" data-fl-row="${i}|итог" value="${esc(r.итог)}"></td>
      <td><input class="input" data-fl-row="${i}|характеристики" value="${esc(r.характеристики)}" placeholder="длина, ткань, фурнитура…"></td>
      <td><button class="btn ghost" data-act="fl-row-del" data-i="${i}" title="Убрать строку">✕</button></td>
    </tr>`).join('');
  const total = FL.rows.reduce((s, r) => s + num(r.итог), 0);
  return `<div class="cx-card" style="margin-top:14px">
    <div class="cx-card-h"><h3>Карта заказа №${esc(o.номер)}</h3>
      <span class="cx-hint">в заказе ${nf(o.заказано)} шт · в карте <b id="fl-total">${nf(total)}</b> шт</span></div>
    <div class="cx-card-b">
      ${o.комментарий ? `<div class="cx-notice">${esc(o.комментарий)}</div>` : ''}
      <datalist id="fl-models">${(ST.refs.модели || []).map((m) => `<option value="${esc(m.модель)}">${esc(m.название)}</option>`).join('')}</datalist>
      <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
      <div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Модель</th><th>Цвет</th><th>Размер</th><th class="num">Заказано</th><th>Итог, шт</th><th>Доп. характеристики</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="cx-btn-row" style="margin-top:10px"><button class="btn" data-act="fl-row-add">+ Строка</button></div>
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
  FL.rows = (o.карта || []).map((r) => ({ ...r }));
  render();
}

async function flSaveDesign(done) {
  const body = { номер: FL.num, готово: done, комментарий: ($('#fl-note') || {}).value || '', позиции: FL.rows };
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
  const sub = [['orders', `Заказы ${nf((FL.supply.очередь || []).length)}`], ['bom', 'Спецификации'], ['rolls', 'Рулоны']];
  return `<div class="cx-hero compact"><div><h1>Снабжение</h1>
      <div class="cx-sub">Сырьё по спецификациям артикулов, поступившие рулоны. Когда сырьё готово — заказ уходит технологу</div></div>
      <div class="cx-hero-actions"><button class="btn" data-act="refresh">Обновить</button></div></div>
    <div class="cx-tabs">${sub.map(([id, l]) => `<button class="cx-tab ${t === id ? 'on' : ''}" data-act="fl-sub" data-tab="${id}">${l}</button>`).join('')}</div>
    ${t === 'bom' ? bomHtml() : t === 'rolls' ? rollsHtml() : supplyOrdersHtml()}`;
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
      <td class="num">${flRollsHint(m)}</td>
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
      ${miss.length ? `<div class="cx-notice warn">Нет нормы расхода для: <b>${miss.map(esc).join('; ')}</b> — это сырьё в расчёт не вошло. Заполните во вкладке «Спецификации».</div>` : ''}
      ${mats ? `<div class="cx-scroll"><table class="cx-table">
        <thead><tr><th>Материал</th><th>Цвет</th><th class="num">Нужно</th><th class="num">Принято рулонов</th><th>Есть / заказано</th><th>Статус</th><th>Комментарий</th></tr></thead>
        <tbody>${mats}</tbody></table></div>
        <div class="cx-hint" style="margin-top:6px">«Принято рулонов» — приход по реестру (вкладка «Рулоны»), расход на крой из него не вычитается.</div>` : ''}
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

function bomHtml() {
  const all = FL.supply.спецификации || {};
  const models = (ST.refs.модели || []).map((m) => m.модель);
  Object.keys(all).forEach((m) => { if (!models.includes(m)) models.push(m); });
  const chips = models.map((m) => `<button class="rt-chip ${m === FL.bomModel ? 'on' : ''}" data-act="fl-bom-pick" data-model="${esc(m)}">${esc(m)}${all[m] ? ` · ${flBomToRows(all[m]).rows.length}` : ''}</button>`).join('');
  const sizeHead = FL.bomSizes.map((sz) => `<th class="num">${esc(sz)} <button class="btn ghost cx-xs" data-act="fl-bom-size-del" data-size="${esc(sz)}" title="Убрать размер ${esc(sz)}">✕</button></th>`).join('');
  const rows = FL.bomRows.map((r, i) => `<tr>
      <td><input class="input" data-fl-bom="${i}|материал" value="${esc(r.материал)}" placeholder="ткань, нитки, молния…"></td>
      <td><input class="input" data-fl-bom="${i}|цвет" value="${esc(r.цвет)}" placeholder="в цвет изделия" list="fl-colors"></td>
      <td><input class="input cx-mini" data-fl-bom="${i}|ед" value="${esc(r.ед || 'м')}" list="fl-units"></td>
      <td><input class="input cx-mini" type="number" min="0" max="100" step="any" data-fl-bom="${i}|запас" value="${esc(r.запас || '')}" placeholder="0"></td>
      <td><input class="input cx-mini" type="number" min="0" step="any" data-fl-bom="${i}|норма" value="${esc(r.норма)}" placeholder="—" title="Норма для всех размеров, у которых своя не указана"></td>
      ${FL.bomSizes.map((sz) => `<td><input class="input cx-mini" type="number" min="0" step="any" data-fl-bsz="${i}|${esc(sz)}" value="${esc(r.размеры[sz] ?? '')}" placeholder="${r.норма !== '' && r.норма != null ? esc(r.норма) : '—'}"></td>`).join('')}
      <td><input class="input" data-fl-bom="${i}|параметры" value="${esc(r.параметры)}" placeholder="ширина, состав…"></td>
      <td><button class="btn ghost" data-act="fl-bom-del" data-i="${i}">✕</button></td></tr>`).join('');
  const seen = (FL.supply.размеры || {})[FL.bomModel] || [];
  const missing = seen.filter((sz) => !FL.bomSizes.includes(sz));
  return `<div class="cx-card"><div class="cx-card-h"><h3>Спецификация материалов по артикулу и размерам</h3></div>
    <div class="cx-card-b">
      <div class="cc-wait">${chips || '<span class="cx-hint">Справочник моделей пуст</span>'}</div>
      ${FL.bomModel ? `
        <datalist id="fl-colors">${(ST.refs.цвета || []).map((c) => `<option value="${esc(c.цвет)}">`).join('')}</datalist>
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
    await api(`${API}${path}`, { method: 'POST', body: JSON.stringify(body) });
    await loadSupply();
    render();
    toast(okText, 'ok');
    return true;
  } catch (err) { toast(err.message, 'err'); return false; }
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act^="fl-"]');
  if (!el || !['design', 'supply'].includes(ST.view)) return;
  ev.stopPropagation();
  const act = el.dataset.act;
  if (act === 'fl-design-open') return flOpenDesign(el.dataset.num);
  if (act === 'fl-supply-open') return flOpenSupply(el.dataset.num);
  if (act === 'fl-row-add') {
    const last = FL.rows[FL.rows.length - 1] || {};
    FL.rows.push({ модель: last.модель || '', цвет: last.цвет || '', размер: '', заказано: 0, итог: 0, характеристики: '' });
    return render();
  }
  if (act === 'fl-row-del') { FL.rows.splice(Number(el.dataset.i), 1); return render(); }
  if (act === 'fl-design-save' || act === 'fl-design-done') {
    el.disabled = true; await flSaveDesign(act === 'fl-design-done'); el.disabled = false; return;
  }
  if (act === 'fl-supply-save' || act === 'fl-supply-done') {
    el.disabled = true; await flSaveSupply(act === 'fl-supply-done'); el.disabled = false; return;
  }
  if (act === 'fl-sub') { FL.supplyTab = el.dataset.tab; FL.num = ''; return render(); }
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
  if (act === 'fl-roll-add') {
    const body = {};
    FL_ROLL_FIELDS.forEach((f) => { body[f] = ($(`#fl-r-${f}`) || {}).value || ''; });
    if (await flPost('/supply/roll', body, `Рулон ${body.код} внесён`)) FL.supplyTab = 'rolls';
  }
}, true);

document.addEventListener('input', (ev) => {
  const t = ev.target;
  const pick = (attr, list) => {
    const [i, f] = t.dataset[attr].split('|');
    list[Number(i)][f] = t.value;
  };
  if (t.dataset.flRow) {
    pick('flRow', FL.rows);
    const total = document.getElementById('fl-total');
    if (total) total.textContent = nf(FL.rows.reduce((s, r) => s + num(r.итог), 0));
  }
  if (t.dataset.flMat) pick('flMat', FL.rows);
  if (t.dataset.flBom || t.dataset.flBsz) {
    if (t.dataset.flBom) pick('flBom', FL.bomRows);
    else {
      const raw = t.dataset.flBsz;
      const cut = raw.indexOf('|');
      FL.bomRows[Number(raw.slice(0, cut))].размеры[raw.slice(cut + 1)] = t.value;
    }
    const box = document.getElementById('fl-bom-preview');
    if (box) box.innerHTML = flBomPreviewHtml();
  }
});
