(function () {
  "use strict";
  const MAX_PONTOS = 60;              // 60 amostras x 5 s = últimos 5 minutos
  const LIMITE_DESATUALIZADO = 3;     // 3 intervalos sem coleta = desatualizado
  let ultimaColetaOk = null;
  let emAndamento = false;
  let semComunicacao = false;
  let horaServidor = "";

  const $ = (id) => document.getElementById(id);
  const esc = (t) => { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; };

  const BADGE = {
    ativo: ["success", "● Ativo"],
    inativo: ["secondary", "○ Inativo"],
    falha: ["danger", "✖ Falha"],
    desconhecido: ["warning", "? Desconhecido"],
  };

  function fmtUptime(s) {
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + " d " : "") + h + " h " + m + " min";
  }

  function notificar(tipo, texto) {
    const cores = { sucesso: "text-bg-success", erro: "text-bg-danger", aviso: "text-bg-warning" };
    const icones = { sucesso: "✔ ", erro: "✖ ", aviso: "⚠ " };
    const el = document.createElement("div");
    el.className = "toast align-items-center border-0 " + cores[tipo];
    el.setAttribute("role", "alert");
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + icones[tipo] + esc(texto) +
      '</div><button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Fechar"></button></div>';
    $("toasts").appendChild(el);
    new bootstrap.Toast(el, { delay: 6000 }).show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
  }

  const base = { animation: false, responsive: true, maintainAspectRatio: false,
                 interaction: { mode: "index", intersect: false } };
  const gRec = new Chart($("g-recursos"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "CPU %", data: [], borderColor: "#2563eb", backgroundColor: "#2563eb", tension: .3, pointRadius: 0 },
      { label: "Memória %", data: [], borderColor: "#16a34a", backgroundColor: "#16a34a", tension: .3, pointRadius: 0, borderDash: [6, 3] },
    ] },
    options: { ...base, scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } } },
  });
  const gHttp = new Chart($("g-http"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "HTTP (ms)", data: [], borderColor: "#9333ea", backgroundColor: "#9333ea", tension: .3, pointRadius: 0, spanGaps: false },
    ] },
    options: { ...base, plugins: { legend: { display: false } },
               scales: { y: { beginAtZero: true, ticks: { callback: (v) => v + " ms" } } } },
  });

  function empurrar(grafico, rotulo, valores) {
    grafico.data.labels.push(rotulo);
    valores.forEach((v, i) => grafico.data.datasets[i].data.push(v));
    if (grafico.data.labels.length > MAX_PONTOS) {
      grafico.data.labels.shift();
      grafico.data.datasets.forEach((ds) => ds.data.shift());
    }
    grafico.update();
  }

  function render(d) {
    const s = d.sistema;
    $("v-cpu").textContent = s.cpu_percentual.toFixed(1) + " %";
    $("b-cpu").style.width = s.cpu_percentual + "%";

    $("v-mem").textContent = (s.memoria.usada_mb / 1024).toFixed(2) + " / " + (s.memoria.total_mb / 1024).toFixed(2) + " GB";
    $("b-mem").style.width = s.memoria.percentual + "%";
    $("d-mem").textContent = "Disponível: " + s.memoria.disponivel_mb + " MB · " + s.memoria.percentual + " % em uso";

    const principal = s.discos[0];
    if (principal && !principal.erro) {
      $("v-disco").textContent = principal.usado_gb + " / " + principal.total_gb + " GB";
      $("b-disco").style.width = principal.percentual + "%";
    }
    $("d-disco").textContent = s.discos.map((x) => x.erro ? x.ponto + ": " + x.erro : x.ponto + " (" + x.percentual + " %)").join(" · ");

    $("v-up").textContent = fmtUptime(s.uptime_s);
    $("d-up").textContent = "Host: " + d.servidor.hostname + " (" + d.servidor.ip + ")";

    const h = d.http;
    $("v-http").textContent = h.ok ? h.duracao_ms + " ms" : "✖ Falha";
    $("d-http").textContent = (h.codigo ? "HTTP " + h.codigo : (h.erro || "sem resposta")) +
      " · " + h.instante + " · medido no " + h.ponto_medicao;

    renderOperacoes(d.operacoes || []);
    const rotulo = d.coletado_em.slice(11);
    empurrar(gRec, rotulo, [s.cpu_percentual, s.memoria.percentual]);
    empurrar(gHttp, rotulo, [h.ok ? h.duracao_ms : null]);

    $("t-servicos").innerHTML = d.servicos.map((sv) => {
      const [cor, txt] = BADGE[sv.estado] || BADGE.desconhecido;
      const tp = sv.teste_porta;
      return "<tr><td>" + esc(sv.nome) + '<div class="small text-muted">' + esc(sv.unidade) + "</div></td>" +
        '<td><span class="badge text-bg-' + cor + '">' + txt + '</span> <span class="small text-muted">' + esc(sv.detalhe) + "</span></td>" +
        "<td>" + sv.porta + "</td>" +
        "<td>" + (tp.aberta ? "✔ aberta" : "✖ fechada") + ' <span class="small text-muted">(' + tp.duracao_ms + " ms · " + esc(tp.instante.slice(11)) + ")</span></td></tr>";
    }).join("");
  }

  const SITUACAO = {
    "concluída": ["success", "✔ concluída"],
    "concluída com alerta": ["warning", "⚠ com alerta"],
    "falha": ["danger", "✖ falha"],
    "em andamento": ["info", "⏳ em andamento"],
  };

  function renderOperacoes(ops) {
    const alvo = $("t-operacoes");
    if (!alvo) return;
    if (!ops.length) {
      alvo.innerHTML = '<tr><td colspan="4" class="text-muted">Nenhuma operação nesta sessão ainda.</td></tr>';
      return;
    }
    alvo.innerHTML = ops.map((o) => {
      const [cor, txt] = SITUACAO[o.situacao] || ["secondary", esc(o.situacao)];
      return '<tr><td class="small text-nowrap">' + esc(o.instante) + "</td>" +
        '<td><span class="badge text-bg-light border">' + esc(o.modulo) + "</span></td>" +
        '<td class="small">' + esc(o.descricao) + (o.detalhe ? '<div class="text-muted text-break">' + esc(o.detalhe) + "</div>" : "") + "</td>" +
        '<td><span class="badge text-bg-' + cor + '">' + txt + "</span></td></tr>";
    }).join("");
  }

  function marcarDesconhecido() {
    document.querySelectorAll("#t-servicos tr").forEach((tr) => {
      tr.style.opacity = ".5";
      tr.title = "Última leitura antes da perda de comunicação";
    });
    document.querySelectorAll("#t-servicos .badge").forEach((b) => {
      b.className = "badge text-bg-warning";
      b.textContent = "? Desconhecido";
    });
  }

  function atualizarIdade() {
    if (!ultimaColetaOk) return;
    const seg = Math.round((Date.now() - ultimaColetaOk) / 1000);
    $("status-coleta").textContent = (semComunicacao ? "⚠ Sem comunicação" : "● Conectado") +
      " · última coleta às " + horaServidor + " (há " + seg + " s) · atualização a cada " + CONFIG.intervalo + " s";
    const desatualizado = seg > CONFIG.intervalo * LIMITE_DESATUALIZADO;
    $("aviso-desatualizado").classList.toggle("d-none", !desatualizado);
    if (desatualizado) {
      $("aviso-desatualizado").textContent = "⚠ Dados desatualizados: a última coleta bem-sucedida foi às " +
        horaServidor + " (há " + seg + " s). Os valores podem não refletir o estado atual.";
    }
  }

  async function coletar(manual) {
    if (emAndamento) return;
    emAndamento = true;
    $("btn-atualizar").disabled = true;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      const r = await fetch(CONFIG.url, { signal: ctrl.signal, cache: "no-store", headers: { Accept: "application/json" } });
      if (r.redirected || r.url.includes(CONFIG.loginUrl)) {
        window.location = CONFIG.loginUrl + "?next=" + encodeURIComponent(location.pathname);
        return;
      }
      if (r.status === 403) throw new Error("sem permissão");
      const d = await r.json();
      if (!d.ok) throw new Error(d.erro || "falha na coleta");
      render(d);
      ultimaColetaOk = new Date();
      horaServidor = d.coletado_em.slice(11);
      if (semComunicacao) notificar("sucesso", "Comunicação com o servidor restabelecida.");
      else if (manual) notificar("sucesso", "Dados atualizados.");
      semComunicacao = false;
    } catch (e) {
      if (!semComunicacao) {
        notificar("erro", "Perda de comunicação com o servidor: " + (e.name === "AbortError" ? "tempo esgotado" : e.message));
      }
      semComunicacao = true;
      marcarDesconhecido();
      if (!ultimaColetaOk) $("status-coleta").textContent = "⚠ Não foi possível obter dados do servidor.";
    } finally {
      clearTimeout(timer);
      emAndamento = false;
      $("btn-atualizar").disabled = false;
      atualizarIdade();
    }
  }

  $("btn-atualizar").addEventListener("click", () => coletar(true));
  coletar(false);
  setInterval(() => coletar(false), CONFIG.intervalo * 1000);
  setInterval(atualizarIdade, 1000);
})();
