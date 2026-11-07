(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (t) => { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; };
  const EXT = JSON.parse($("extensoes").textContent);
  const NOME_OK = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

  function notificar(ok, texto) {
    const el = document.createElement("div");
    el.className = "toast align-items-center border-0 " + (ok ? "text-bg-success" : "text-bg-danger");
    el.setAttribute("role", "alert");
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + (ok ? "✔ " : "✖ ") + esc(texto) +
      '</div><button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Fechar"></button></div>';
    $("toasts").appendChild(el);
    new bootstrap.Toast(el, { delay: 6000 }).show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
  }

  function tabelaHashes(v) {
    const linha = (rotulo, h) => "<tr><th class='fw-normal small'>" + rotulo + "</th><td><code class='small text-break'>" + (h ? esc(h) : "—") + "</code></td></tr>";
    const http = v.http_codigo ? "HTTP " + v.http_codigo : esc(v.erro_http || "sem resposta");
    return '<div class="alert ' + (v.integro ? "alert-success" : "alert-warning") + ' mb-0" role="status"><strong>' +
      (v.integro ? "✔ Integridade confirmada: os hashes coincidem." : "⚠ Integridade não confirmada.") + "</strong>" +
      '<div class="small mt-1">Publicação HTTP: ' + http + ' · <a href="' + esc(v.url_http) + '" target="_blank" rel="noopener">' + esc(v.url_http) + "</a></div>" +
      '<table class="table table-sm mb-0 mt-2"><tbody>' +
      (v.sha256_local ? linha("SHA-256 do arquivo enviado", v.sha256_local) : "") +
      linha("SHA-256 recuperado por FTP", v.sha256_ftp) +
      linha("SHA-256 publicado por HTTP", v.sha256_http) +
      "</tbody></table></div>";
  }

  // ---------- Envio ----------
  const form = $("form-envio");
  if (form) {
    const input = $("arquivo");

    function validar() {
      const f = input.files[0];
      let msg = "";
      if (!f) msg = "Selecione um arquivo.";
      else {
        const ext = f.name.includes(".") ? "." + f.name.split(".").pop().toLowerCase() : "";
        if (!NOME_OK.test(f.name) || f.name.includes("..")) msg = "Nome inválido: use apenas letras, números, ponto, hífen ou sublinhado.";
        else if (!EXT.includes(ext)) msg = "Tipo não permitido. Permitidos: " + EXT.join(", ");
        else if (f.size === 0) msg = "O arquivo está vazio.";
        else if (f.size > ARQ.maxMb * 1024 * 1024) msg = "Arquivo maior que " + ARQ.maxMb + " MB.";
      }
      input.classList.toggle("is-invalid", !!msg);
      $("erro-arquivo").textContent = msg;
      return !msg;
    }

    input.addEventListener("change", validar);

    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      if (!validar()) return;
      const f = input.files[0];
      const barra = $("progresso-barra"), texto = $("progresso-texto");
      $("progresso").classList.remove("d-none");
      $("resultado").innerHTML = "";
      $("btn-enviar").disabled = true;
      barra.className = "progress-bar progress-bar-striped";
      barra.style.width = "0%";
      texto.textContent = "⏳ Enviando " + f.name + " ao console…";

      const xhr = new XMLHttpRequest();
      xhr.timeout = 60000;
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const p = Math.round((e.loaded / e.total) * 100);
        barra.style.width = p + "%";
        texto.textContent = "⏳ Enviando " + f.name + " ao console: " + p + " %";
        if (p === 100) {
          texto.textContent = "⏳ Transferindo ao vsftpd por FTP e verificando integridade…";
          barra.classList.add("progress-bar-animated");
        }
      };
      xhr.onload = () => {
        $("btn-enviar").disabled = false;
        barra.classList.remove("progress-bar-animated");
        let d;
        try { d = JSON.parse(xhr.responseText); }
        catch (e) { d = { ok: false, erro: xhr.status === 403 ? "Sem permissão para enviar arquivos." : "Resposta inesperada do servidor (HTTP " + xhr.status + ")." }; }
        if (d.ok) {
          barra.classList.add("bg-success");
          texto.textContent = "✔ Transferência concluída: " + d.nome;
          $("resultado").innerHTML =
            '<div class="mb-2"><strong>' + esc(d.nome) + "</strong> · " + d.tamanho + " bytes enviados · " +
            d.tamanho_remoto + " bytes no servidor · resposta do FTP: <code>" + esc(d.resposta_ftp) + "</code></div>" +
            tabelaHashes(d.verificacao) +
            '<a class="btn btn-sm btn-outline-secondary mt-2" href="">⟳ Atualizar lista</a>';
          notificar(true, "Arquivo " + d.nome + " enviado via FTP.");
          form.reset();
        } else {
          barra.classList.add("bg-danger");
          barra.style.width = "100%";
          texto.textContent = "✖ Falha no envio";
          $("resultado").innerHTML = '<div class="alert alert-danger mb-0" role="alert">✖ ' + esc(d.erro) + "</div>";
          notificar(false, d.erro);
        }
      };
      xhr.onerror = xhr.ontimeout = () => {
        $("btn-enviar").disabled = false;
        barra.classList.add("bg-danger");
        texto.textContent = "✖ Sem comunicação com o console.";
        notificar(false, "Perda de comunicação durante o envio.");
      };
      xhr.open("POST", form.action);
      xhr.send(new FormData(form));
    });
  }

  // ---------- Verificação de integridade ----------
  document.querySelectorAll(".btn-verificar").forEach((btn) => btn.addEventListener("click", async () => {
    const alvo = $("resultado-verificacao");
    btn.disabled = true;
    alvo.innerHTML = '<div class="text-muted" role="status">⏳ Baixando ' + esc(btn.dataset.nome) + " por FTP e por HTTP para comparar…</div>";
    try {
      const r = await fetch(ARQ.verificar + "?nome=" + encodeURIComponent(btn.dataset.nome), { cache: "no-store" });
      const d = await r.json();
      alvo.innerHTML = d.ok
        ? '<div class="mb-1"><strong>' + esc(d.nome) + "</strong></div>" + tabelaHashes(d)
        : '<div class="alert alert-danger" role="alert">✖ ' + esc(d.erro) + "</div>";
    } catch (e) {
      alvo.innerHTML = '<div class="alert alert-danger" role="alert">✖ Sem comunicação com o console.</div>';
    } finally {
      btn.disabled = false;
    }
  }));
})();
