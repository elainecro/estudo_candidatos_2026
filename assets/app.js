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

  // ---------------------------------------------------------------- partidos
  function renderPartidos() {
    const sel = $('#f-espectro');
    for (const e of [...new Set(PARTIDOS.map(p => p.espectro))].sort()) sel.appendChild(h('option', { value: e }, esc(e)));
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
        <p class="esp">${esc(p.espectro)}${p.federacao ? ' · federação ' + esc(p.federacao) : ''}</p>
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
      <p class="sub">Fundado em ${p.fundacao} · ${esc(p.espectro)}${p.federacao ? ' · Federação ' + esc(p.federacao) : ' · sem federação'}</p>
      <h3>O que defende</h3><p>${esc(p.ideologia)}</p>
      <h3>Marcos: o que fez ou sustentou quando teve poder</h3><ul class="marcos">${p.marcos.map(m => `<li>${esc(m)}</li>`).join('')}</ul>
      <h3>Críticas frequentes</h3><ul class="criticas">${p.criticas.map(m => `<li>${esc(m)}</li>`).join('')}</ul>
      <h3>No Espírito Santo em 2026</h3><p>${esc(p.no_es)}</p>
      ${cands.length ? `<h3>Candidatos neste guia (${cands.length})</h3><ul>${cands.map(x => `<li><a href="#" data-cand="${x.id}">${esc(x.nome_urna)}</a> · ${NOME_CURTO[x.cargo]}${x.numero ? ' · ' + x.numero : ''}</li>`).join('')}</ul>` : ''}
      <a class="pill-link" href="#candidatos" data-filtra-partido="${esc(p.sigla)}">Filtrar candidatos do ${esc(p.sigla)} →</a>
      <p class="nota">${esc(D.partidos.nota)}</p>`);
  }

  // -------------------------------------------------------------- candidatos
  const estado = { cargo: 'governador', partido: '', busca: '', reeleicao: false };
  function renderCandidatos() {
    const chips = $('#chips-cargo');
    for (const id of ORDEM_CARGOS) {
      const n = CANDS.filter(c => c.cargo === id && c.situacao !== 'desistiu').length;
      chips.appendChild(h('button', { type: 'button', role: 'tab', 'data-cargo': id, 'aria-selected': String(id === estado.cargo), onclick: () => { estado.cargo = id; desenharCandidatos(); } }, `${NOME_CURTO[id]} <small>(${n})</small>`));
    }
    const sel = $('#f-partido');
    for (const s of [...new Set(CANDS.map(c => c.partido))].sort((a, b) => a.localeCompare(b, 'pt-BR'))) sel.appendChild(h('option', { value: s }, `${esc(s)} · ${PARTIDO_POR_SIGLA[s]?.numero ?? ''}`));
    sel.addEventListener('change', e => { estado.partido = e.target.value; desenharCandidatos(); });
    $('#f-busca').addEventListener('input', e => { estado.busca = e.target.value.trim().toLowerCase(); desenharCandidatos(); });
    $('#f-reeleicao').addEventListener('change', e => { estado.reeleicao = e.target.checked; desenharCandidatos(); });
    desenharCandidatos();
  }
  function normal(s) { return String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function desenharCandidatos() {
    document.querySelectorAll('#chips-cargo button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.cargo === estado.cargo)));
    $('#f-partido').value = estado.partido;
    const cob = D.candidatos.meta.cobertura[estado.cargo];
    $('#cobertura').innerHTML = `<b>${esc(CARGO_POR_ID[estado.cargo].nome)}</b>: ${esc(cob)}`;
    const busca = normal(estado.busca);
    const lista = CANDS.filter(c => c.cargo === estado.cargo)
      .filter(c => !estado.partido || c.partido === estado.partido)
      .filter(c => !estado.reeleicao || (c.mandatos && c.mandatos.length))
      .filter(c => !busca || normal(c.nome_urna).includes(busca) || normal(c.nome_completo).includes(busca) || (c.numero || '').startsWith(busca) || normal(c.partido).includes(busca))
      .sort((a, b) => (a.situacao === 'desistiu') - (b.situacao === 'desistiu') || (a.numero || '99999').localeCompare(b.numero || '99999') || a.nome_urna.localeCompare(b.nome_urna, 'pt-BR'));
    const box = $('#lista-candidatos'); box.innerHTML = '';
    $('#contagem').textContent = `${lista.length} ${lista.length === 1 ? 'candidato' : 'candidatos'}${estado.partido ? ' do ' + estado.partido : ''}${busca ? ' para "' + estado.busca + '"' : ''}`;
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
    if (!c.projetos) return c.tipo_historico === 'sem_mandato' ? 'nunca teve mandato' : 'sem dados de projetos';
    const a = c.projetos.aprovados?.length || 0, t = c.projetos.em_tramitacao?.length || 0;
    if (!a && !t) return 'projetos: sem consolidação';
    return `<b>${a}</b> lei${a === 1 ? '' : 's'} · <b>${t}</b> em tramitação`;
  }
  function cardCandidato(c) {
    const anos = anosPolitica(c);
    const p = PARTIDO_POR_SIGLA[c.partido];
    return h('button', { class: 'card candidato', type: 'button', onclick: () => abrirCandidato(c) }, `
      <div class="cabeca">
        <div><h3>${esc(c.nome_urna)}</h3><p class="sub">${esc(c.partido)}${p?.federacao ? ' · ' + esc(p.federacao) : ''}${c.ocupacao ? ' · ' + esc(c.ocupacao) : ''}</p></div>
        <div class="numero ${c.numero ? '' : 'pendente'}">${c.numero || 'nº a confirmar'}</div>
      </div>
      <p class="resumo">${esc(c.resumo)}</p>
      <div class="tags">${tagSituacao(c)}${c.reeleicao ? '<span class="tag">tenta reeleição</span>' : ''}${c.tipo_historico === 'sem_mandato' ? '<span class="tag">estreante</span>' : ''}</div>
      <div class="rodape-card"><span>${anos !== null && c.tipo_historico !== 'sem_mandato' ? `<b>${anos}</b> anos de vida pública` : 'sem mandato anterior'}</span><span>${resumoProjetos(c)}</span></div>`);
  }
  function abrirCandidato(c) {
    const cargo = CARGO_POR_ID[c.cargo]; const p = PARTIDO_POR_SIGLA[c.partido]; const anos = anosPolitica(c);
    const chapa = c.chapa ? `<div class="chapa"><b>Chapa:</b> vice ${esc(c.chapa.vice || 'não informado')}${c.chapa.partido_vice ? ' (' + esc(c.chapa.partido_vice) + ')' : ''}${c.chapa.coligacao ? '<br><b>Coligação:</b> ' + esc(c.chapa.coligacao) : ''}</div>` : '';
    const supl = c.suplentes ? `<div class="chapa"><b>Suplentes:</b> ${c.suplentes.map(esc).join(', ')}</div>` : '';
    const mandatos = c.mandatos?.length ? c.mandatos.map(m => `<div class="linha"><div class="per">${esc(m.periodo)}</div><div><b>${esc(m.cargo)}</b>${m.partido ? ' · ' + esc(m.partido) : ''}${m.obs ? `<div class="obs">${esc(m.obs)}</div>` : ''}</div></div>`).join('') : '<p class="nota">Nenhum mandato eletivo anterior.</p>';
    let projetos;
    if (!c.projetos) {
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
        </div>
        <p class="nota">Fonte: ${esc(pj.fonte)} · atualizado em ${esc(pj.atualizado_em)}.</p>`;
    }
    abrirModal(`
      <p class="kicker">${esc(cargo.nome)} · ${esc(c.partido)}${p?.federacao ? ' · Federação ' + esc(p.federacao) : ''}</p>
      <h2>${esc(c.nome_urna)} <span class="numero">${c.numero || ''}</span></h2>
      <p class="sub">${esc(c.nome_completo || '')}${c.idade ? ' · ' + c.idade + ' anos' : ''}${c.ocupacao ? ' · ' + esc(c.ocupacao) : ''}</p>
      <div class="tags">${tagSituacao(c)}${!c.numero ? '<span class="tag warn">número não confirmado</span>' : ''}${c.reeleicao ? '<span class="tag">tenta reeleição</span>' : ''}</div>
      ${c.situacao_obs ? `<p class="aviso">${esc(c.situacao_obs)}</p>` : ''}
      <p>${esc(c.resumo)}</p>
      ${chapa}${supl}
      <h3>Tempo de política</h3>
      <p>${c.tipo_historico === 'sem_mandato' ? 'Primeira candidatura registrada. ' : ''}${anos !== null && c.inicio_politica ? `Na vida pública desde <b>${c.inicio_politica}</b> (${anos} anos).` : 'Sem data de início registrada.'}</p>
      <h3>Mandatos e cargos</h3>
      ${mandatos}
      <h3>Projetos</h3>
      ${projetos}
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
    const a = e.target.closest('a[data-cand],a[data-partido],a[data-filtra-cargo],a[data-filtra-partido]');
    if (!a) return;
    e.preventDefault();
    if (a.dataset.cand) { const c = CANDS.find(x => x.id === a.dataset.cand); if (c) abrirCandidato(c); }
    else if (a.dataset.partido) { const p = PARTIDO_POR_SIGLA[a.dataset.partido]; if (p) abrirPartido(p); }
    else if (a.dataset.filtraCargo) { estado.cargo = a.dataset.filtraCargo; estado.partido = ''; desenharCandidatos(); fecharModal(); location.hash = 'candidatos'; }
    else if (a.dataset.filtraPartido) { estado.partido = a.dataset.filtraPartido; const c = CANDS.find(x => x.partido === estado.partido && x.situacao !== 'desistiu'); if (c && !CANDS.some(x => x.partido === estado.partido && x.cargo === estado.cargo)) estado.cargo = c.cargo; desenharCandidatos(); fecharModal(); location.hash = 'candidatos'; }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) fecharModal(); });

  renderCargos(); renderPartidos(); renderCandidatos(); renderUrna();
})();
