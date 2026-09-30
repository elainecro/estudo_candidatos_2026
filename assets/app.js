/* Guia eleitoral ES 2026. Sem dependências. Lê window.ESTUDO_2026 (data/bundle.js). */
(function () {
  'use strict';
  const D = window.ESTUDO_2026;
  if (!D) { document.body.insertAdjacentHTML('afterbegin', '<p class="aviso wrap">Não achei data/bundle.js. Rode <code>python3 scripts/build_bundle.py</code>.</p>'); return; }

  const CARGOS = D.cargos.cargos;
  const CARGO_POR_ID = Object.fromEntries(CARGOS.map(c => [c.id, c]));
  const PARTIDOS = D.partidos.partidos;
  const PARTIDO_POR_SIGLA = Object.fromEntries(PARTIDOS.map(p => [p.sigla, p]));
  const CANDS = D.candidatos.candidatos;
  const ESPECTROS = (D.espectros?.espectros || []).slice().sort((a, b) => a.posicao - b.posicao);
  const ESPECTRO_POR_ID = Object.fromEntries(ESPECTROS.map(e => [e.id, e]));
  const ORDEM_ESPECTROS = ESPECTROS.map(e => e.id);
  const espectroDe = sigla => PARTIDO_POR_SIGLA[sigla]?.espectro || '';
  const corEsp = id => `--esp: var(--esp-${ESPECTRO_POR_ID[id]?.posicao || 4})`;
  const ORDEM_CARGOS = ['presidente', 'governador', 'senador', 'deputado_federal', 'deputado_estadual'];
  const NOME_CURTO = { presidente: 'Presidente', governador: 'Governador', senador: 'Senador', deputado_federal: 'Dep. Federal', deputado_estadual: 'Dep. Estadual' };

  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const h = (tag, attrs = {}, html = '') => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined) e.setAttribute(k, v); } e.innerHTML = html; return e; };

  // ------------------------------------------------------------------ cargos
  function renderCargos() {
    const box = $('#lista-cargos');
    for (const c of CARGOS) {
      const card = h('button', { class: 'card cargo', type: 'button', onclick: () => abrirCargo(c) }, `
        <div class="vagas">${c.vagas}</div>
        <h3>${esc(c.nome)}</h3>
        <p class="sub">${c.vagas === 1 ? '1 vaga' : c.vagas + ' vagas'} · ${c.mandato_anos} anos · ${c.digitos} dígitos</p>
        <p class="sub">${esc(c.o_que_e)}</p>
        <div class="tags"><span class="tag">${esc(c.sistema.split(':')[0].split(',')[0])}</span></div>`);
      box.appendChild(card);
    }
    const gl = $('#glossario');
    for (const g of D.cargos.glossario) { gl.appendChild(h('dt', {}, esc(g.termo))); gl.appendChild(h('dd', {}, esc(g.def))); }
  }
  function abrirCargo(c) {
    const cands = CANDS.filter(x => x.cargo === c.id && x.situacao !== 'desistiu');
    abrirModal(`
      <p class="kicker">Cargo</p>
      <h2>${esc(c.nome)}</h2>
      <p class="sub">${c.vagas} ${c.vagas === 1 ? 'vaga' : 'vagas'} · mandato de ${c.mandato_anos} anos · voto com ${c.digitos} dígitos · ${esc(c.sistema)}</p>
      <p>${esc(c.o_que_e)}</p>
      <h3>Pelo que responde</h3>
      <ul>${c.responsabilidades.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
      <h3>O que não está na alçada</h3>
      <p>${esc(c.o_que_nao_faz)}</p>
      ${c.aviso_proporcional ? `<p class="aviso">${esc(c.aviso_proporcional)}</p>` : ''}
      <h3>Como avaliar um candidato</h3>
      <p>${esc(c.como_avaliar)}</p>
      <h3>Candidatos neste guia (${cands.length})</h3>
      <ul>${cands.map(x => `<li><a href="#" data-cand="${x.id}">${esc(x.nome_urna)}</a> (${esc(x.partido)}${x.numero ? ', ' + x.numero : ''})</li>`).join('')}</ul>
      <a class="pill-link" href="#candidatos" data-filtra-cargo="${c.id}">Ver todos com filtro →</a>`);
  }

  // --------------------------------------------------------------- espectros
  function renderEspectros() {
    if (!ESPECTROS.length) { $('#espectros').hidden = true; return; }
    const E = D.espectros;
    $('#espectro-origem').innerHTML = E.origem.map(t => `<p>${esc(t)}</p>`).join('') +
      `<div class="regua">${ESPECTROS.map(e => `<span style="${corEsp(e.id)}" title="${esc(e.nome)}"></span>`).join('')}</div>` +
      `<p class="regua-rotulos"><span>← esquerda</span><span>direita →</span></p>` +
      `<div class="eixos">${E.eixos.map(x => `<div class="eixo-caixa"><h4>${esc(x.nome)}</h4><p class="lado"><i>${esc(x.pergunta)}</i></p><p><b>Esquerda:</b> ${esc(x.esquerda)}</p><p><b>Direita:</b> ${esc(x.direita)}</p></div>`).join('')}</div>`;
    $('#espectro-limites').innerHTML = E.limites.map(t => `<li>${esc(t)}</li>`).join('');
    const box = $('#lista-espectros');
    for (const e of ESPECTROS) {
      const partidos = PARTIDOS.filter(p => p.espectro === e.id).sort((a, b) => a.sigla.localeCompare(b.sigla, 'pt-BR'));
      const n = CANDS.filter(c => espectroDe(c.partido) === e.id && c.situacao !== 'desistiu').length;
      box.appendChild(h('button', { class: 'card espectro', type: 'button', style: corEsp(e.id), onclick: () => abrirEspectro(e) }, `
        <h3>${esc(e.nome)}</h3>
        <p class="siglas">${partidos.map(p => esc(p.sigla)).join(' · ') || 'nenhum partido'}</p>
        <p class="resumo">${esc(e.resumo)}</p>
        <div class="tags"><span class="tag ${n ? 'ok' : ''}">${n} ${n === 1 ? 'candidato' : 'candidatos'} no ES</span></div>`));
    }
  }
  function abrirEspectro(e) {
    const partidos = PARTIDOS.filter(p => p.espectro === e.id).sort((a, b) => a.sigla.localeCompare(b.sigla, 'pt-BR'));
    const n = CANDS.filter(c => espectroDe(c.partido) === e.id && c.situacao !== 'desistiu').length;
    abrirModal(`
      <p class="kicker">Espectro</p>
      <h2><span class="esp-dot" style="${corEsp(e.id)}"></span>${esc(e.nome)}</h2>
      <p class="sub">${esc(e.resumo)}</p>
      <h3>O que prioriza</h3><ul>${e.prioriza.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
      <h3>Por que existe</h3><p>${esc(e.por_que_existe)}</p>
      <h3>Como reconhecer</h3><ul>${e.como_reconhecer.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
      ${e.no_brasil ? `<h3>Peso hoje</h3><p>${esc(e.no_brasil)}</p>` : ''}
      <h3>Partidos nesta faixa (${partidos.length})</h3>
      <ul>${partidos.map(p => `<li><a href="#" data-partido="${esc(p.sigla)}">${esc(p.sigla)}</a> · ${esc(p.nome)}${p.espectro_nota ? ` <span class="obs">(${esc(p.espectro_nota)})</span>` : ''}</li>`).join('') || '<li>nenhum</li>'}</ul>
      <a class="pill-link" href="#partidos" data-filtra-espectro-partidos="${esc(e.id)}">Ver esses partidos →</a>
      <a class="pill-link" href="#candidatos" data-filtra-espectro="${esc(e.id)}">Filtrar os ${n} candidatos →</a>
      <p class="nota">${esc(D.espectros.nota)}</p>`);
  }

  // ---------------------------------------------------------------- partidos
  function renderPartidos() {
    const sel = $('#f-espectro');
    const esps = [...new Set(PARTIDOS.map(p => p.espectro))].sort((a, b) => ORDEM_ESPECTROS.indexOf(a) - ORDEM_ESPECTROS.indexOf(b));
    for (const e of esps) sel.appendChild(h('option', { value: e }, esc(ESPECTRO_POR_ID[e]?.nome || e)));
    sel.addEventListener('change', desenharPartidos);
    $('#f-com-candidato').addEventListener('change', desenharPartidos);
    desenharPartidos();
  }
  function temCandidato(sigla) { return CANDS.some(c => c.partido === sigla && c.situacao !== 'desistiu'); }
  function desenharPartidos() {
    const box = $('#lista-partidos'); box.innerHTML = '';
    const esp = $('#f-espectro').value; const so = $('#f-com-candidato').checked;
    const lista = PARTIDOS.filter(p => (!esp || p.espectro === esp) && (!so || temCandidato(p.sigla)))
      .sort((a, b) => a.sigla.localeCompare(b.sigla, 'pt-BR'));
    for (const p of lista) {
      const n = CANDS.filter(c => c.partido === p.sigla && c.situacao !== 'desistiu').length;
      box.appendChild(h('button', { class: 'card partido', type: 'button', onclick: () => abrirPartido(p) }, `
        <h3><span class="num">${p.numero}</span> ${esc(p.sigla)}</h3>
        <p class="sub">${esc(p.nome)} · desde ${p.fundacao}</p>
        <p class="esp"><span class="esp-dot" style="${corEsp(p.espectro)}"></span>${esc(p.espectro)}${p.espectro_nota ? ' (' + esc(p.espectro_nota.split(':')[0].split(';')[0].toLowerCase()) + ')' : ''}${p.federacao ? ' · federação ' + esc(p.federacao) : ''}</p>
        <p class="sub">${esc(p.ideologia.split('. ')[0])}.</p>
        <div class="tags"><span class="tag ${n ? 'ok' : ''}">${n ? n + (n === 1 ? ' candidato neste guia' : ' candidatos neste guia') : 'sem candidato no guia'}</span></div>`));
    }
    if (!lista.length) box.innerHTML = '<p class="nota">Nenhum partido com esses filtros.</p>';
  }
  function abrirPartido(p) {
    const cands = CANDS.filter(c => c.partido === p.sigla && c.situacao !== 'desistiu').sort((a, b) => ORDEM_CARGOS.indexOf(a.cargo) - ORDEM_CARGOS.indexOf(b.cargo));
    abrirModal(`
      <p class="kicker">Partido · número ${p.numero}</p>
      <h2>${esc(p.sigla)} <small style="font-weight:400;color:var(--muted)">${esc(p.nome)}</small></h2>
      <p class="sub">Fundado em ${p.fundacao} · <span class="esp-dot" style="${corEsp(p.espectro)}"></span>${esc(p.espectro)}${p.espectro_nota ? '. ' + esc(p.espectro_nota) : ''}${p.federacao ? ' · Federação ' + esc(p.federacao) : ' · sem federação'}</p>
      <h3>O que defende</h3><p>${esc(p.ideologia)}</p>
      <h3>Marcos: o que fez ou sustentou quando teve poder</h3><ul class="marcos">${p.marcos.map(m => `<li>${esc(m)}</li>`).join('')}</ul>
      <h3>Críticas frequentes</h3><ul class="criticas">${p.criticas.map(m => `<li>${esc(m)}</li>`).join('')}</ul>
      <h3>No Espírito Santo em 2026</h3><p>${esc(p.no_es)}</p>
      ${cands.length ? `<h3>Candidatos neste guia (${cands.length})</h3><ul>${cands.map(x => `<li><a href="#" data-cand="${x.id}">${esc(x.nome_urna)}</a> · ${NOME_CURTO[x.cargo]}${x.numero ? ' · ' + x.numero : ''}</li>`).join('')}</ul>` : ''}
      <a class="pill-link" href="#candidatos" data-filtra-partido="${esc(p.sigla)}">Filtrar candidatos do ${esc(p.sigla)} →</a>
      <p class="nota">${esc(D.partidos.nota)}</p>`);
  }

  // -------------------------------------------------------------- candidatos
  const estado = { cargo: 'governador', partido: '', espectro: '', busca: '', reeleicao: false };
  function renderCandidatos() {
    const chips = $('#chips-cargo');
    for (const id of ORDEM_CARGOS) {
      const n = CANDS.filter(c => c.cargo === id && c.situacao !== 'desistiu').length;
      chips.appendChild(h('button', { type: 'button', role: 'tab', 'data-cargo': id, 'aria-selected': String(id === estado.cargo), onclick: () => { estado.cargo = id; desenharCandidatos(); } }, `${NOME_CURTO[id]} <small>(${n})</small>`));
    }
    const sel = $('#f-partido');
    for (const s of [...new Set(CANDS.map(c => c.partido))].sort((a, b) => a.localeCompare(b, 'pt-BR'))) sel.appendChild(h('option', { value: s }, `${esc(s)} · ${PARTIDO_POR_SIGLA[s]?.numero ?? ''}`));
    sel.addEventListener('change', e => { estado.partido = e.target.value; desenharCandidatos(); });
    const selE = $('#f-espectro-cand');
    for (const e of ESPECTROS) selE.appendChild(h('option', { value: e.id }, esc(e.nome)));
    selE.addEventListener('change', e => { estado.espectro = e.target.value; if (estado.partido && espectroDe(estado.partido) !== estado.espectro) estado.partido = ''; desenharCandidatos(); });
    $('#f-busca').addEventListener('input', e => { estado.busca = e.target.value.trim().toLowerCase(); desenharCandidatos(); });
    $('#f-reeleicao').addEventListener('change', e => { estado.reeleicao = e.target.checked; desenharCandidatos(); });
    desenharCandidatos();
  }
  function normal(s) { return String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function desenharCandidatos() {
    document.querySelectorAll('#chips-cargo button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.cargo === estado.cargo)));
    $('#f-partido').value = estado.partido;
    $('#f-espectro-cand').value = estado.espectro;
    for (const o of $('#f-partido').options) o.hidden = !!(estado.espectro && o.value && espectroDe(o.value) !== estado.espectro);
    const cob = D.candidatos.meta.cobertura[estado.cargo];
    $('#cobertura').innerHTML = `<b>${esc(CARGO_POR_ID[estado.cargo].nome)}</b>: ${esc(cob)}`;
    const busca = normal(estado.busca);
    const lista = CANDS.filter(c => c.cargo === estado.cargo)
      .filter(c => !estado.partido || c.partido === estado.partido)
      .filter(c => !estado.espectro || espectroDe(c.partido) === estado.espectro)
      .filter(c => !estado.reeleicao || (c.mandatos && c.mandatos.length))
      .filter(c => !busca || normal(c.nome_urna).includes(busca) || normal(c.nome_completo).includes(busca) || (c.numero || '').startsWith(busca) || normal(c.partido).includes(busca))
      .sort((a, b) => (a.situacao === 'desistiu') - (b.situacao === 'desistiu') || (a.numero || '99999').localeCompare(b.numero || '99999') || a.nome_urna.localeCompare(b.nome_urna, 'pt-BR'));
    const box = $('#lista-candidatos'); box.innerHTML = '';
    $('#contagem').textContent = `${lista.length} ${lista.length === 1 ? 'candidato' : 'candidatos'}${estado.partido ? ' do ' + estado.partido : (estado.espectro ? ' de partidos de ' + (ESPECTRO_POR_ID[estado.espectro]?.nome || estado.espectro).toLowerCase() : '')}${busca ? ' para "' + estado.busca + '"' : ''}`;
    for (const c of lista) box.appendChild(cardCandidato(c));
    if (!lista.length) box.innerHTML = '<p class="nota">Ninguém com esses filtros. Se o nome que você procura não está aqui, ele pode estar entre os candidatos ainda não importados do TSE (veja o aviso de cobertura acima).</p>';
  }
  function anosPolitica(c) { return c.inicio_politica ? new Date().getFullYear() - c.inicio_politica : null; }
  function tagSituacao(c) {
    if (c.situacao === 'deferido') return '<span class="tag ok">registro deferido</span>';
    if (c.situacao === 'indeferido') return '<span class="tag bad">registro indeferido</span>';
    if (c.situacao === 'desistiu') return '<span class="tag bad">desistiu</span>';
    return '<span class="tag warn">registro em análise</span>';
  }
  function resumoProjetos(c) {
    if (!c.projetos && c.camara_municipal) return `${c.camara_municipal.projetos?.length || 0} projetos na Câmara de ${esc((c.camara_municipal.casa || '').replace('Câmara Municipal de ', ''))}`;
    if (!c.projetos) return c.tipo_historico === 'sem_mandato' ? 'nunca teve mandato' : 'sem dados de projetos';
    const a = c.projetos.aprovados?.length || 0, t = c.projetos.em_tramitacao?.length || 0;
    if (!a && !t) return 'projetos: sem consolidação';
    return `<b>${a}</b> lei${a === 1 ? '' : 's'} · <b>${t}</b> em tramitação`;
  }
  function resumoHistorico(c) {
    if (c.gestao?.length && (!c.projetos || (!c.projetos.aprovados?.length && !c.projetos.em_tramitacao?.length))) return `gestão: <b>${c.gestao.length}</b> ${c.gestao.length === 1 ? 'cargo' : 'cargos'}`;
    const partes = [resumoProjetos(c)];
    if (c.relatorias?.length) partes.push(`<b>${c.relatorias.length}</b> relatoria${c.relatorias.length === 1 ? '' : 's'}`);
    return partes.join(' · ');
  }
  function temSancao(c) { const s = c.sancoes; return !!(s && ['tcu', 'ceis', 'cnep', 'ceaf'].some(k => s[k]?.length)); }
  function cardCandidato(c) {
    const anos = anosPolitica(c);
    const p = PARTIDO_POR_SIGLA[c.partido];
    return h('button', { class: 'card candidato', type: 'button', onclick: () => abrirCandidato(c) }, `
      <div class="cabeca">
        ${c.foto ? `<img class="foto" src="${esc(c.foto)}" alt="" loading="lazy" onerror="this.remove()">` : ''}
        <div><h3>${esc(c.nome_urna)}</h3><p class="sub">${esc(c.partido)}${p?.federacao ? ' · ' + esc(p.federacao) : ''}${c.ocupacao ? ' · ' + esc(c.ocupacao) : ''}</p></div>
        <div class="numero ${c.numero ? '' : 'pendente'}">${c.numero || 'nº a confirmar'}</div>
      </div>
      <p class="resumo">${esc(c.resumo)}</p>
      <div class="tags">${tagSituacao(c)}${c.reeleicao ? '<span class="tag">tenta reeleição</span>' : ''}${c.tipo_historico === 'sem_mandato' ? '<span class="tag">estreante</span>' : ''}${c.processos?.length ? `<span class="tag warn">${c.processos.length} ${c.processos.length === 1 ? 'processo/denúncia' : 'processos/denúncias'}</span>` : ''}${temSancao(c) ? '<span class="tag bad">em lista de sanção</span>' : ''}${c.certidoes_flag === 'com apontamentos' ? '<span class="tag warn">certidão com processo</span>' : ''}</div>
      <div class="rodape-card"><span>${anos !== null && c.tipo_historico !== 'sem_mandato' ? `<b>${anos}</b> anos de vida pública` : 'sem mandato anterior'}</span><span>${resumoHistorico(c)}</span></div>`);
  }
  function abrirCandidato(c) {
    const cargo = CARGO_POR_ID[c.cargo]; const p = PARTIDO_POR_SIGLA[c.partido]; const anos = anosPolitica(c);
    const chapa = c.chapa ? `<div class="chapa"><b>Chapa:</b> vice ${esc(c.chapa.vice || 'não informado')}${c.chapa.partido_vice ? ' (' + esc(c.chapa.partido_vice) + ')' : ''}${c.chapa.coligacao ? '<br><b>Coligação:</b> ' + esc(c.chapa.coligacao) : ''}</div>` : '';
    const supl = c.suplentes ? `<div class="chapa"><b>Suplentes:</b> ${c.suplentes.map(esc).join(', ')}</div>` : '';
    const mandatos = c.mandatos?.length ? c.mandatos.map(m => `<div class="linha"><div class="per">${esc(m.periodo)}</div><div><b>${esc(m.cargo)}</b>${m.partido ? ' · ' + esc(m.partido) : ''}${m.obs ? `<div class="obs">${esc(m.obs)}</div>` : ''}</div></div>`).join('') : '<p class="nota">Nenhum mandato eletivo anterior.</p>';
    let camaraMunicipal = '';
    if (c.camara_municipal) {
      const cm = c.camara_municipal;
      const tipos = Object.entries(cm.por_tipo || {}).slice(0, 6).map(([k, v]) => `<li>${esc(k)}: <b>${v}</b></li>`).join('');
      const sits = Object.entries(cm.por_situacao || {}).slice(0, 5).map(([k, v]) => `${esc(k)} ${v}`).join(' · ');
      const li = pr => `<li>${pr.url ? `<a href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(pr.tipo || '')} ${esc(pr.numero || '')}</a>` : `<b>${esc(pr.tipo || '')} ${esc(pr.numero || '')}</b>`}${pr.situacao ? ` <span class="tag ${/aprovad|sancion|promulg/i.test(pr.situacao) ? 'ok' : /arquiv|rejeit|retirad/i.test(pr.situacao) ? 'bad' : ''}">${esc(pr.situacao)}</span>` : ''}${pr.data ? ` <i class="obs">${esc(pr.data)}</i>` : ''}${pr.ementa ? `<div class="obs">${esc(pr.ementa.length > 220 ? pr.ementa.slice(0, 220) + '…' : pr.ementa)}</div>` : ''}</li>`;
      camaraMunicipal = `<h4 class="eixo">Na ${esc(cm.casa || 'Câmara Municipal')}</h4>
        <p><b>${Number(cm.total_declarado || cm.total_lido || 0).toLocaleString('pt-BR')}</b> proposições de autoria registradas no portal da Câmara${cm.total_lido && cm.total_declarado && cm.total_lido < cm.total_declarado ? ` (${cm.total_lido} lidas)` : ''}. ${sits ? 'Situação: ' + sits + '.' : ''}</p>
        ${tipos ? `<ul>${tipos}</ul>` : ''}
        ${cm.temas?.length ? `<p class="obs"><b>Palavras mais frequentes nas ementas:</b> ${cm.temas.map(esc).join(', ')}.</p>` : ''}
        ${cm.projetos?.length ? `<h4 class="eixo">Projetos (lei, resolução, emenda)</h4><ul>${cm.projetos.slice(0, 15).map(li).join('')}</ul>${cm.projetos.length > 15 ? `<details><summary class="nota">Ver os outros ${cm.projetos.length - 15} projetos</summary><ul>${cm.projetos.slice(15).map(li).join('')}</ul></details>` : ''}` : '<p class="nota">Nenhum projeto de lei, resolução ou emenda localizado; a produção é de indicações e requerimentos.</p>'}
        ${cm.recentes?.length ? `<details><summary class="nota">Indicações e requerimentos mais recentes (${cm.recentes.length})</summary><ul>${cm.recentes.map(li).join('')}</ul></details>` : ''}
        <p class="nota">Fonte: <a href="${esc(cm.url)}" target="_blank" rel="noopener">${esc(cm.fonte || cm.casa)}</a>, consultado em ${esc(cm.consultado_em || '')}. Indicação é pedido à prefeitura, sem força de lei; o que vira lei é o projeto aprovado e sancionado.</p>`;
    }
    let projetos;
    if (!c.projetos && camaraMunicipal) {
      projetos = camaraMunicipal;
    } else if (!c.projetos) {
      projetos = c.tipo_historico === 'sem_mandato'
        ? '<p class="nota">Não há histórico legislativo porque a pessoa nunca teve mandato. Resta avaliar propostas e trajetória profissional.</p>'
        : '<p class="nota">Ainda não consolidamos os projetos desta pessoa. Para quem foi deputado federal ou senador, rode <code>scripts/fetch_dados.py --camara</code> ou <code>--senado</code>.</p>';
    } else {
      const pj = c.projetos; const lista = (arr, vazio) => arr?.length ? `<ul>${arr.map(i => `<li>${i.id ? `<b>${esc(i.id)}</b> ` : ''}${esc(i.titulo)}${i.norma && i.norma !== i.titulo ? ` <i>(${esc(i.norma)}${i.ano ? ', ' + i.ano : ''})</i>` : ''}${i.status ? ` · ${esc(i.status)}` : ''}${i.papel ? ` · ${esc(i.papel)}` : ''}${i.obs ? `<div class="obs">${esc(i.obs)}</div>` : ''}</li>`).join('')}</ul>` : `<p class="vazio">${vazio}</p>`;
      projetos = `
        <div class="colunas">
          <div class="col"><h4>Apresentados <span>${pj.apresentados?.total ?? '?'}</span></h4><p class="vazio">${esc(pj.apresentados?.obs || '')}</p></div>
          <div class="col"><h4>Em tramitação <span>${pj.em_tramitacao?.length ?? 0}</span></h4>${lista(pj.em_tramitacao, 'Nenhum registrado aqui.')}</div>
          <div class="col"><h4>Aprovados e em vigor <span>${pj.aprovados?.length ?? 0}</span></h4>${lista(pj.aprovados, 'Nenhum registrado aqui.')}</div>
          ${pj.pecs_assinadas?.length ? `<div class="col"><h4>PECs assinadas com outros <span>${pj.pecs_assinadas.length}</span></h4><p class="vazio">${esc(pj.pecs_obs || '')} Não conta como projeto próprio.</p><details><summary class="nota">Ver as PECs</summary>${lista(pj.pecs_assinadas, '')}</details></div>` : ''}
        </div>
        <p class="nota">Fonte: ${esc(pj.fonte)} · atualizado em ${esc(pj.atualizado_em)}.</p>`;
    }
    const gestao = c.gestao?.length ? `<h3>Gestão: o que fez quando teve a caneta</h3>` + c.gestao.map(g => `
        <div class="gestao">
          <div class="linha"><div class="per">${esc(g.periodo)}</div><div><b>${esc(g.cargo)}</b>${g.fonte ? `<div class="obs">Fonte: ${esc(g.fonte)}</div>` : ''}</div></div>
          <div class="colunas">
            <div class="col"><h4>Realizações <span>${g.realizacoes?.length ?? 0}</span></h4>${g.realizacoes?.length ? `<ul>${g.realizacoes.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : '<p class="vazio">Sem balanço consolidado.</p>'}</div>
            <div class="col"><h4>Críticas e problemas <span>${g.criticas?.length ?? 0}</span></h4>${g.criticas?.length ? `<ul>${g.criticas.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : '<p class="vazio">Nenhuma registrada aqui.</p>'}</div>
          </div>
        </div>`).join('') : (c.tipo_historico === 'executivo' || c.tipo_historico === 'misto' ? '<h3>Gestão</h3><p class="nota">Teve cargo executivo, mas ainda não consolidamos o balanço.</p>' : '');
    const LIM_REL = 15;
    const liRel = r => `<li><b>${esc(r.titulo)}</b>${r.ano ? ` (${r.ano})` : ''}${r.resultado ? `<div class="obs">${esc(r.resultado)}</div>` : ''}</li>`;
    const relatorias = c.relatorias?.length
      ? `<ul>${c.relatorias.slice(0, LIM_REL).map(liRel).join('')}</ul>${c.relatorias.length > LIM_REL ? `<details><summary class="nota">Ver as outras ${c.relatorias.length - LIM_REL} relatorias</summary><ul>${c.relatorias.slice(LIM_REL).map(liRel).join('')}</ul></details>` : ''}`
      : '<p class="nota">Nenhuma relatoria ou presidência de comissão registrada aqui.</p>';
    const fiscalizacao = c.fiscalizacao?.length ? `<ul>${c.fiscalizacao.map(f => `<li><span class="tag">${esc(f.tipo)}</span> ${esc(f.descricao)}${f.ano ? ` <i>(${f.ano})</i>` : ''}</li>`).join('')}</ul>` : '<p class="nota">Nenhuma CPI, denúncia ou ação de fiscalização registrada aqui.</p>';
    const cert = c.certidoes_resumo?.length ? (() => {
      const grupos = {};
      for (const x of c.certidoes_resumo) { const k = x.orgao + (x.grau ? ' · ' + x.grau : '') + (x.tipo === 'quitação eleitoral' ? ' · quitação' : ''); (grupos[k] = grupos[k] || []).push(x); }
      const chip = st => st === 'nada consta' ? 'ok' : st === 'com apontamentos' ? 'bad' : st === 'só eleitoral' ? '' : 'warn';
      const linhas = Object.entries(grupos).map(([k, xs]) => `<li><b>${esc(k)}</b>: ${xs.map(x => `<span class="tag ${chip(x.status)}">${esc(x.status)}</span>`).join(' ')}${xs.flatMap(x => x.processos || []).length ? `<div class="obs">Processos: ${xs.flatMap(x => x.processos).map(esc).join(', ')}</div>` : ''}${xs.filter(x => x.trecho).map(x => `<div class="obs">“${esc(x.trecho)}”</div>`).join('')}</li>`).join('');
      const it = c.certidoes_interpretacao;
      const interp = it ? (() => {
        const procs = [];
        const vistos = new Set();
        for (const d of it.certidoes || []) for (const pr of d.processos || []) { const k = pr.numero || JSON.stringify(pr); if (vistos.has(k)) continue; vistos.add(k); procs.push(pr); }
        const chipPolo = polo => /r[ée]u|paciente|apelante/.test(polo || '') ? 'bad' : /não diz|só mencionado/.test(polo || '') ? 'warn' : 'ok';
        const tabela = procs.length ? `<table class="tabela-proc"><thead><tr><th>Processo</th><th>Classe</th><th>Polo</th><th>Situação</th></tr></thead><tbody>${procs.map(pr => `<tr><td><code>${esc(pr.numero || '?')}</code>${pr.orgao ? `<div class="obs">${esc(pr.orgao)}</div>` : ''}</td><td>${esc(pr.classe || '')}${pr.assunto ? `<div class="obs">${esc(pr.assunto)}</div>` : ''}${pr.criminal === false ? '<div class="obs">não criminal</div>' : ''}</td><td><span class="tag ${chipPolo(pr.polo_candidato)}">${esc(pr.polo_candidato || 'não diz')}</span></td><td>${esc(pr.situacao || 'não diz')}${pr.data ? `<div class="obs">${esc(pr.data)}</div>` : ''}</td></tr>`).join('')}</tbody></table>` : '';
        const conf = it.confianca === 'alta' ? 'ok' : it.confianca === 'baixa' ? 'bad' : 'warn';
        return `<h4 class="eixo">Interpretação automática das certidões</h4>
          <p>${esc(it.resumo || '')}</p>
          <p class="obs"><span class="tag ${it.processos_como_reu ? 'bad' : 'ok'}">réu em ${it.processos_como_reu ?? '?'}</span> <span class="tag ${it.processos_ativos_como_reu ? 'bad' : 'ok'}">${it.processos_ativos_como_reu ?? '?'} em andamento</span> <span class="tag ${it.condenacao === true ? 'bad' : it.condenacao === false ? 'ok' : 'warn'}">condenação: ${it.condenacao === true ? 'sim' : it.condenacao === false ? 'não consta' : 'não dá para saber'}</span> <span class="tag ${conf}">confiança ${esc(it.confianca || '?')}</span></p>
          ${tabela}
          ${it.atencao?.length ? `<p class="obs"><b>Confira no tribunal:</b></p><ul class="obs">${it.atencao.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}
          <p class="nota">Interpretação feita por modelo de linguagem (${esc(it.modelo || '')}, ${esc(it.data || '')}) a partir do texto OCR das certidões. Pode errar. Processo em andamento não é condenação. Confira pelo número no site do tribunal.</p>`;
      })() : '';
      return `<p><span class="tag ${chip(c.certidoes_flag)}">certidões do registro: ${esc(c.certidoes_flag || '')}</span> ${c.certidoes_resumo.length} certidões anexadas ao TSE, lidas automaticamente.</p>${interp}<ul>${linhas}</ul><p class="nota">Leitura automática do texto das certidões. "Com apontamentos" quer dizer que a certidão lista processo; pode ser arquivado ou a pessoa pode não ser ré. Os PDFs originais estão na página do candidato no DivulgaCand.</p>`;
    })() : '';
    const processos = (c.processos?.length ? `<ul class="processos">${c.processos.map(pr => `<li>${esc(pr.descricao)}<div class="obs"><b>Status:</b> ${esc(pr.status)}${pr.ano ? ` · ${pr.ano}` : ''}${pr.fonte ? ` · <a href="${esc(pr.fonte)}" target="_blank" rel="noopener">fonte</a>` : ''}</div></li>`).join('')}</ul><p class="nota">${esc(D.candidatos.meta.aviso_processos || '')}</p>` : '<p class="nota">Nenhum processo, investigação ou denúncia localizado na imprensa. Isso não é atestado: veja as certidões abaixo e procure o nome no MPES, TSE e Jusbrasil.</p>') + cert;
    const brl = v => (v === null || v === undefined) ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
    let plano = '';
    if (c.proposta_resumo || c.proposta_governo) {
      const r = c.proposta_resumo;
      const pg = c.proposta_governo || {};
      const resumo = r ? `${r.sintese ? `<p>${esc(r.sintese)}</p>` : ''}${r.eixos?.length ? r.eixos.map(e => `<h4 class="eixo">${esc(e.tema)}</h4><ul>${(e.propostas || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`).join('') : ''}${r.mensuraveis?.length ? `<h4 class="eixo">Promessas com número ou prazo</h4><ul>${r.mensuraveis.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}${r.lacunas?.length ? `<h4 class="eixo">O que o plano não diz</h4><ul>${r.lacunas.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}${r.fonte ? `<p class="nota">${esc(r.fonte)}</p>` : ''}` : '<p class="nota">Resumo ainda não escrito. O texto integral está abaixo.</p>';
      const texto = pg.texto ? `<details><summary class="nota">Texto integral extraído do PDF (${pg.paginas || '?'} páginas, ${Number(pg.caracteres || 0).toLocaleString('pt-BR')} caracteres)</summary><pre class="plano">${esc(pg.texto)}</pre></details>` : (pg.arquivo ? `<p class="nota">Texto extraído em <code>${esc(pg.arquivo)}</code>.</p>` : '');
      plano = `<h3>Plano de governo registrado no TSE</h3>${pg.legivel === false ? '<p class="aviso">O PDF entregue ao TSE não tem texto legível (imagem). Abra o original no DivulgaCand.</p>' : ''}${resumo}${texto}`;
    } else if (c.cargo === 'presidente' || c.cargo === 'governador') {
      plano = '<h3>Plano de governo registrado no TSE</h3><p class="nota">Ainda não extraído. Rode <code>scripts/ler_pdfs.py --propostas</code> com o zip de propostas em data/cache/.</p>';
    }
    const blocos = [];
    if (c.bens) blocos.push(`<h3>Patrimônio declarado ao TSE</h3><p><b>${brl(c.bens.total)}</b> em ${c.bens.itens?.length ?? 0} bens.</p>${c.bens.itens?.length ? `<ul>${c.bens.itens.slice(0, 8).map(b => `<li>${esc(b.tipo || '')}: ${esc(b.descricao || '')} · ${brl(b.valor)}</li>`).join('')}</ul>` : ''}`);
    if (c.campanha) {
      const k = c.campanha;
      const gastou = k.despesas === null || k.despesas === undefined
        ? 'gastos ainda não consolidados (o TSE publica despesas em arquivo separado)'
        : `contratou <b>${brl(k.despesas)}</b> em despesas${k.despesas_pagas !== null && k.despesas_pagas !== undefined ? ` (${brl(k.despesas_pagas)} já pagos)` : ''}${k.despesas > k.receitas * 1.05 ? ' <span class="tag warn">contratou mais do que recebeu</span>' : ''}`;
      const doadores = k.maiores_doadores?.length ? `<h4 class="eixo">Maiores doadores</h4><ul>${k.maiores_doadores.map(d => `<li>${esc(d.nome)} · ${brl(d.valor)}</li>`).join('')}</ul>` : '';
      const forn = k.maiores_fornecedores?.length ? `<h4 class="eixo">Maiores fornecedores</h4><ul>${k.maiores_fornecedores.slice(0, 6).map(d => `<li>${esc(d.nome)} · ${brl(d.valor)}</li>`).join('')}</ul>` : '';
      const tipos = k.despesas_por_tipo?.length ? `<h4 class="eixo">Em que gastou</h4><ul>${k.despesas_por_tipo.map(d => `<li>${esc(d.tipo)} · ${brl(d.valor)}</li>`).join('')}</ul>` : '';
      blocos.push(`<h3>Financiamento da campanha 2026</h3><p>Recebeu <b>${brl(k.receitas)}</b>, ${gastou}. De fundo público e partido: ${brl(k.fundo_publico_e_partido)}.</p>${doadores}${tipos}${forn}<p class="nota">Prestação de contas parcial, informada pelo candidato ao TSE. "Contratou" é o valor dos contratos declarados, pagos ou não; por isso pode passar do que foi recebido até aqui. Tudo muda até a prestação final, depois da eleição.</p>`);
    }
    if (c.eleicoes_anteriores?.length || c.filiacoes?.length) {
      const el = (c.eleicoes_anteriores || []).map(e => `<div class="linha"><div class="per">${esc(e.ano)}</div><div>${esc(e.cargo || '')}${e.partido ? ' · ' + esc(e.partido) : ''}${e.uf ? ' · ' + esc(e.uf) : ''}${e.resultado ? `<div class="obs">${esc(e.resultado)}${e.votos ? ' · ' + Number(e.votos).toLocaleString('pt-BR') + ' votos' : ''}</div>` : ''}</div></div>`).join('');
      const fl = (c.filiacoes || []).map(f => `<li>${esc(f.partido)} · ${esc(f.inicio || '?')} a ${esc(f.fim || 'atual')}</li>`).join('');
      blocos.push(`<h3>Histórico eleitoral e partidos</h3>${c.trocas_de_partido !== undefined && c.trocas_de_partido !== null ? `<p><b>${c.eleicoes_anteriores?.length ?? 0}</b> ${(c.eleicoes_anteriores?.length ?? 0) === 1 ? 'eleição anterior' : 'eleições anteriores'}${c.vezes_eleito !== undefined ? `, eleito <b>${c.vezes_eleito}</b> ${c.vezes_eleito === 1 ? 'vez' : 'vezes'}` : ''}. <b>${c.trocas_de_partido}</b> ${c.trocas_de_partido === 1 ? 'troca' : 'trocas'} de partido entre elas.</p>` : ''}${el}${fl ? `<p class="nota" style="margin-top:8px">Filiações (Senado):</p><ul>${fl}</ul>` : ''}`);
    }
    if (c.votacoes_chave?.length) {
      const principal = v => /^(aprovad|rejeitad|mantid)/i.test(v.descricao || '') && /(projeto|proposta|substitutivo|texto|parecer|redação final|emenda aglutinativa global|em 1º turno|em 2º turno|em primeiro turno|em segundo turno)/i.test(v.descricao || '') && !/destaque|requerimento|emenda n[ºo°]|dvs/i.test(v.descricao || '');
      const linha = v => `<tr><td>${esc(v.tema)}<div class="obs">${esc(v.descricao || '')}</div></td><td>${esc((v.data || v.quando || '').slice(0, 10))}</td><td><b>${esc(v.voto || 'sem registro')}</b></td></tr>`;
      const tabela = rows => `<div class="tabela-wrap"><table class="tabela"><thead><tr><th>Tema</th><th>Quando</th><th>Voto</th></tr></thead><tbody>${rows.map(linha).join('')}</tbody></table></div>`;
      const vp = c.votacoes_chave.filter(principal), vo = c.votacoes_chave.filter(v => !principal(v));
      blocos.push(`<h3>Como votou em temas-chave</h3>${vp.length ? tabela(vp) : '<p class="nota">Nenhuma votação principal identificada; veja todas abaixo.</p>'}${vo.length ? `<details><summary class="nota">Ver as outras ${vo.length} votações (destaques, emendas, requerimentos)</summary>${tabela(vo)}</details>` : ''}<p class="nota">Votações escolhidas em data/votacoes_chave.json. "Principal" é a votação do texto; o resto são destaques e emendas.</p>`);
    }
    if (c.gastos?.cota_parlamentar_por_ano) blocos.push(`<h3>Cota parlamentar (gastos reembolsados)</h3><ul>${Object.entries(c.gastos.cota_parlamentar_por_ano).map(([a, v]) => `<li>${a}: ${brl(v)}</li>`).join('')}</ul>`);
    if (c.emendas) blocos.push(`<h3>Emendas parlamentares</h3><p><b>${brl(c.emendas.total_empenhado)}</b> empenhados.</p>${c.emendas.maiores_destinos?.length ? `<ul>${c.emendas.maiores_destinos.map(d => `<li>${esc(d.destino)} · ${brl(d.valor)}</li>`).join('')}</ul>` : ''}`);
    if (c.comissoes?.length) blocos.push(`<h3>Comissões na Câmara</h3><ul>${c.comissoes.slice(0, 12).map(o => `<li>${esc(o.sigla || '')} ${esc(o.nome || '')}${o.papel ? ' · ' + esc(o.papel) : ''}</li>`).join('')}</ul>`);
    if (c.certidoes?.length) blocos.push(`<h3>Certidões anexadas ao registro</h3><ul class="fontes">${c.certidoes.map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.nome)}</a></li>`).join('')}</ul>`);
    const redes = c.redes?.length ? `<h3>Redes sociais declaradas ao TSE</h3><ul class="fontes">${c.redes.map(u => `<li><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\/(www\.)?/, ''))}</a></li>`).join('')}</ul>` : '';
    const comp = c.tse_complementar ? `<p class="nota">${[c.tse_complementar.nascimento ? 'Nascimento: ' + esc(c.tse_complementar.nascimento) : '', c.tse_complementar.limite_gastos ? 'Limite de gastos da campanha: ' + brl(c.tse_complementar.limite_gastos) : '', c.tse_complementar.declarou_bens === false ? 'Não declarou bens' : '', c.tse_complementar.substituido ? 'Foi substituído na chapa' : ''].filter(Boolean).join(' · ')}</p>` : '';
    const links = (c.links?.length ? `<h3>Onde conferir</h3><ul>${c.links.map(l => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.nome)}</a></li>`).join('')}</ul>` : '') + redes + comp;
    const t = c.trajetoria;
    const trajetoria = t ? `<h3>Trajetória</h3>${(t.texto || '').split(/\n\s*\n/).map(x => `<p>${esc(x)}</p>`).join('')}${t.marcos?.length ? `<ul>${t.marcos.map(m => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}${t.controversias?.length ? `<p><b>Controvérsias noticiadas</b></p><ul>${t.controversias.map(m => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}<p class="nota">Pesquisa feita com ajuda de IA em ${esc(t.escrito_em || '')} a partir de fontes públicas (confiança ${esc(t.confianca || '?')}). ${t.fontes?.length ? 'Fontes: ' + t.fontes.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.titulo || f.url)}</a>`).join(' · ') : ''}</p>` : '';
    const sc = c.sancoes;
    const listas = [['tcu', 'TCU: contas julgadas irregulares'], ['ceis', 'CEIS: empresas e pessoas inidôneas'], ['cnep', 'CNEP: punidas pela Lei Anticorrupção'], ['ceaf', 'CEAF: servidores expulsos']];
    const sancoes = sc ? `<h4 class="eixo">Listas de sanção (por CPF)</h4><ul>${listas.map(([k, nome]) => `<li><span class="tag ${sc[k]?.length ? 'bad' : 'ok'}">${sc[k]?.length ? sc[k].length + ' ocorrência' + (sc[k].length > 1 ? 's' : '') : 'nada'}</span> ${esc(nome)}${sc[k]?.length ? `<div class="obs">${sc[k].map(x => esc(Object.entries(x).filter(([, v]) => v).map(([kk, v]) => `${kk}: ${v}`).join(' · '))).join('<br>')}</div>` : ''}</li>`).join('')}</ul><p class="nota">Cruzamento exato por CPF em ${esc(sc.verificado_em || '')}: ${esc((sc.fontes_consultadas || []).join(', ') || 'nenhuma lista consultada ainda')}.</p>${c.servidor_federal?.vinculos?.length ? `<p class="obs"><b>Servidor federal:</b> ${c.servidor_federal.vinculos.map(v => esc([v.cargo, v.orgao, v.situacao].filter(Boolean).join(' · '))).join('; ')} <i>(${esc(c.servidor_federal.fonte)})</i></p>` : ''}` : '';
    const nt = c.noticias;
    const noticias = nt?.itens?.length ? `<h3>Na imprensa</h3><ul class="noticias">${nt.itens.map(n => `<li><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.titulo)}</a><div class="obs">${[n.fonte, n.data ? fmtData(n.data) : ''].filter(Boolean).map(esc).join(' · ')}</div></li>`).join('')}</ul><p class="nota">Manchetes do Google Notícias para a busca <code>${esc(nt.busca || '')}</code> em ${esc(nt.consultado_em || '')}. Pode incluir homônimos. Não é avaliação, é o que foi publicado.</p>` : (nt ? '<h3>Na imprensa</h3><p class="nota">Nenhuma manchete encontrada no Google Notícias para este nome.</p>' : '');
    const cruzamentos = blocos.join('') + links + (blocos.length ? '' : '<p class="nota">Patrimônio, doadores, votações-chave, cota e emendas ainda não foram coletados para esta pessoa. Rode <code>scripts/fetch_dados.py --tudo</code>.</p>');
    abrirModal(`
      <p class="kicker">${esc(cargo.nome)} · ${esc(c.partido)}${p?.federacao ? ' · Federação ' + esc(p.federacao) : ''}</p>
      <div class="modal-cabeca">${c.foto ? `<img class="foto grande" src="${esc(c.foto)}" alt="Foto de urna de ${esc(c.nome_urna)}" onerror="this.remove()">` : ''}<h2>${esc(c.nome_urna)} <span class="numero">${c.numero || ''}</span></h2></div>
      <p class="sub">${esc(c.nome_completo || '')}${c.idade ? ' · ' + c.idade + ' anos' : ''}${c.ocupacao ? ' · ' + esc(c.ocupacao) : ''}${c.escolaridade ? ' · ' + esc(c.escolaridade.toLowerCase()) : ''}</p>
      <div class="tags">${tagSituacao(c)}${!c.numero ? '<span class="tag warn">número não confirmado</span>' : ''}${c.reeleicao ? '<span class="tag">tenta reeleição</span>' : ''}</div>
      ${c.situacao_obs ? `<p class="aviso">${esc(c.situacao_obs)}</p>` : ''}
      <p>${esc(c.resumo)}</p>
      ${trajetoria}
      ${chapa}${supl}
      <h3>Tempo de política</h3>
      <p>${c.tipo_historico === 'sem_mandato' ? 'Primeira candidatura registrada. ' : ''}${anos !== null && c.inicio_politica ? `Na vida pública desde <b>${c.inicio_politica}</b> (${anos} anos).` : 'Sem data de início registrada.'}</p>
      <h3>Mandatos e cargos</h3>
      ${mandatos}
      ${gestao}
      <h3>Projetos de lei</h3>
      ${projetos}${c.projetos && camaraMunicipal ? camaraMunicipal : ''}
      <h3>Relatorias e cargos de direção</h3>
      ${relatorias}
      <h3>Fiscalização e denúncias que fez</h3>
      ${fiscalizacao}
      <h3>Processos e denúncias contra</h3>
      ${processos}
      ${sancoes}
      ${plano}
      ${noticias}
      ${cruzamentos}
      <h3>Sobre o partido</h3>
      <p>${esc(p?.ideologia || '')} <a href="#" data-partido="${esc(c.partido)}">Ver ficha do ${esc(c.partido)}</a></p>
      <h3>Fontes</h3>
      <ul class="fontes">${(c.fontes || []).map(f => `<li><a href="${esc(f)}" target="_blank" rel="noopener">${esc(f)}</a></li>`).join('')}</ul>`);
  }

  // -------------------------------------------------------------------- urna
  function renderUrna() {
    const ol = $('#ordem-urna');
    for (const v of D.cargos.eleicao.ordem_na_urna) ol.appendChild(h('li', {}, `<span>${esc(CARGO_POR_ID[v.cargo].nome)}${v.obs ? ` <small>(${esc(v.obs)})</small>` : ''}</span><span class="dig">${'#'.repeat(v.digitos)}</span>`));
    const e = D.cargos.eleicao;
    $('#atualizado').textContent = `Dados atualizados em ${fmtData(D.candidatos.meta.atualizado_em)}. 1º turno: ${fmtData(e.primeiro_turno)}. 2º turno (presidente e governador, se houver): ${fmtData(e.segundo_turno)}. Eleitores no ES: ${e.eleitores_es}.`;
  }
  function fmtData(iso) { const [a, m, d] = iso.split('-'); return `${d}/${m}/${a}`; }

  // ------------------------------------------------------------------- modal
  const modal = $('#modal'), conteudo = $('#modal-conteudo'); let ultimoFoco = null;
  function abrirModal(html) {
    ultimoFoco = document.activeElement;
    conteudo.innerHTML = html; modal.hidden = false; document.body.style.overflow = 'hidden';
    $('.modal-caixa').scrollTop = 0; $('.fechar').focus();
  }
  function fecharModal() { modal.hidden = true; document.body.style.overflow = ''; ultimoFoco?.focus?.(); }
  modal.addEventListener('click', e => {
    if (e.target.closest('[data-fechar]')) return fecharModal();
    const a = e.target.closest('a[data-cand],a[data-partido],a[data-filtra-cargo],a[data-filtra-partido],a[data-filtra-espectro],a[data-filtra-espectro-partidos]');
    if (!a) return;
    e.preventDefault();
    if (a.dataset.cand) { const c = CANDS.find(x => x.id === a.dataset.cand); if (c) abrirCandidato(c); }
    else if (a.dataset.partido) { const p = PARTIDO_POR_SIGLA[a.dataset.partido]; if (p) abrirPartido(p); }
    else if (a.dataset.filtraEspectroPartidos) { $('#f-espectro').value = a.dataset.filtraEspectroPartidos; $('#f-com-candidato').checked = false; desenharPartidos(); fecharModal(); location.hash = 'partidos'; }
    else if (a.dataset.filtraEspectro) { estado.espectro = a.dataset.filtraEspectro; estado.partido = ''; if (!CANDS.some(x => x.cargo === estado.cargo && espectroDe(x.partido) === estado.espectro && x.situacao !== 'desistiu')) { const c = CANDS.find(x => espectroDe(x.partido) === estado.espectro && x.situacao !== 'desistiu'); if (c) estado.cargo = c.cargo; } desenharCandidatos(); fecharModal(); location.hash = 'candidatos'; }
    else if (a.dataset.filtraCargo) { estado.cargo = a.dataset.filtraCargo; estado.partido = ''; estado.espectro = ''; desenharCandidatos(); fecharModal(); location.hash = 'candidatos'; }
    else if (a.dataset.filtraPartido) { estado.partido = a.dataset.filtraPartido; estado.espectro = ''; const c = CANDS.find(x => x.partido === estado.partido && x.situacao !== 'desistiu'); if (c && !CANDS.some(x => x.partido === estado.partido && x.cargo === estado.cargo)) estado.cargo = c.cargo; desenharCandidatos(); fecharModal(); location.hash = 'candidatos'; }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) fecharModal(); });

  renderCargos(); renderEspectros(); renderPartidos(); renderCandidatos(); renderUrna();
})();
