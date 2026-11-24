"use strict";

// PetCare · frontend separado. Consume la API REST con JSON y autenticación JWT (Bearer).
// El access token vive solo en memoria; el refresh token en sessionStorage, que se borra al
// cerrar la pestaña. Al cerrar sesión el refresh se invalida en el servidor (lista negra).

const API = (window.PETCARE_CONFIG && window.PETCARE_CONFIG.apiBase || "").replace(/\/$/, "");
const REFRESH_KEY = "petcare.refresh";
const state = { access: null, user: null, cache: {} };

const ESTADOS_CITA = [["agendada", "Agendada"], ["atendida", "Atendida"], ["cancelada", "Cancelada"], ["no_asistio", "No asistió"]];

// Recursos que el frontend gestiona (CRUD completo). Los campos coinciden con los serializers.
const RESOURCES = {
    tutores: {
        title: "Tutores", singular: "tutor", nuevo: "Nuevo tutor", label: (r) => r.nombre,
        columns: [["nombre", "Nombre"], ["email", "Correo"], ["telefono", "Teléfono"]],
        fields: [
            { name: "nombre", label: "Nombre", required: true },
            { name: "email", label: "Correo electrónico", type: "email", required: true },
            { name: "telefono", label: "Teléfono", required: true },
            { name: "direccion", label: "Dirección" },
        ],
    },
    mascotas: {
        title: "Mascotas", singular: "mascota", nuevo: "Nueva mascota", label: (r) => r.nombre,
        columns: [["nombre", "Nombre"], ["especie", "Especie"], ["raza", "Raza"], ["tutor", "Tutor", "tutores"]],
        fields: [
            { name: "tutor", label: "Tutor", type: "fk", ref: "tutores", required: true },
            { name: "nombre", label: "Nombre", required: true },
            { name: "especie", label: "Especie", required: true },
            { name: "raza", label: "Raza" },
            { name: "nacimiento", label: "Fecha de nacimiento", type: "date" },
        ],
    },
    citas: {
        title: "Citas", singular: "cita", nuevo: "Nueva cita", label: (r) => `${fmtDateTime(r.inicio)}`,
        columns: [["inicio", "Inicio", "datetime"], ["mascota", "Mascota", "mascotas"],
                  ["profesional", "Profesional", "profesionales"], ["motivo", "Motivo"], ["estado", "Estado", "estado"]],
        fields: [
            { name: "mascota", label: "Mascota", type: "fk", ref: "mascotas", required: true },
            { name: "profesional", label: "Profesional", type: "fk", ref: "profesionales", required: true, onlyActive: true },
            { name: "inicio", label: "Inicio", type: "datetime", required: true },
            { name: "fin", label: "Fin", type: "datetime", required: true },
            { name: "motivo", label: "Motivo", required: true },
            { name: "estado", label: "Estado", type: "select", options: ESTADOS_CITA },
        ],
        help: "La cita debe quedar dentro de un bloque de disponibilidad del profesional y no cruzarse con otra.",
    },
    atenciones: {
        title: "Atenciones clínicas", singular: "atención", nuevo: "Nueva atención", label: (r) => r.fecha,
        columns: [["fecha", "Fecha", "date"], ["mascota", "Mascota", "mascotas"],
                  ["profesional", "Profesional", "profesionales"], ["diagnostico", "Diagnóstico"]],
        fields: [
            { name: "mascota", label: "Mascota", type: "fk", ref: "mascotas", required: true },
            { name: "profesional", label: "Profesional", type: "fk", ref: "profesionales", required: true, onlyActive: true },
            { name: "fecha", label: "Fecha", type: "date", omitEmpty: true },
            { name: "servicio", label: "Servicio", type: "fk", ref: "servicios" },
            { name: "monto", label: "Monto cobrado (CLP)", type: "number" },
            { name: "peso_kg", label: "Peso (kg)", type: "number", step: "0.01" },
            { name: "diagnostico", label: "Diagnóstico", type: "textarea", required: true },
            { name: "tratamiento", label: "Tratamiento", type: "textarea" },
            { name: "receta", label: "Receta médica", type: "textarea" },
            { name: "examenes", label: "Exámenes", type: "textarea" },
        ],
    },
};
const LABELS = { profesionales: (r) => r.activo === false ? `${r.nombre} (inactivo)` : r.nombre, servicios: (r) => r.nombre };

// ---------- Utilidades ----------
const $ = (sel) => document.querySelector(sel);
function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" });
}
function fmtDate(iso) {
    if (!iso) return "—";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
}
function toLocalInput(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function flash(message, kind = "success") {
    const box = $("#flash");
    box.textContent = message;
    box.className = `alert ${kind}`;
    box.hidden = false;
    clearTimeout(flash.timer);
    flash.timer = setTimeout(() => { box.hidden = true; }, kind === "error" ? 9000 : 4000);
}
function logRequest(method, path, status, ms) {
    const list = $("#api-log");
    if (!list) return;
    const item = document.createElement("li");
    item.className = status >= 400 ? "bad" : "ok";
    item.textContent = `${new Date().toLocaleTimeString("es-CL")} · ${method} ${path} → ${status || "sin respuesta"} (${ms} ms)`;
    list.prepend(item);
    while (list.children.length > 12) list.lastChild.remove();
}

// ---------- Cliente HTTP con JWT ----------
class ApiError extends Error {
    constructor(status, data) {
        super(describeError(status, data));
        this.status = status;
        this.data = data;
    }
}
function describeError(status, data) {
    if (status === 429) return "API Gateway limitó las solicitudes (429 Too Many Requests). Espera un momento y vuelve a intentar.";
    if (status === 401) return "Tu sesión expiró. Vuelve a ingresar.";
    if (status === 403) return (data && data.detail) || "Tu rol no permite esta acción (403).";
    if (status === 409) return (data && data.detail) || "Hay registros relacionados que impiden la operación (409).";
    if (status === 0) return "No se pudo conectar con la API. Revisa la conexión o la URL de API Gateway.";
    if (data && data.detail) return data.detail;
    if (data && data.non_field_errors) return data.non_field_errors.join(" ");
    if (Array.isArray(data)) return data.join(" ");
    return `La API respondió ${status}.`;
}

async function request(method, path, body, { retry = true, auth = true } = {}) {
    const headers = { "Accept": "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && state.access) headers["Authorization"] = `Bearer ${state.access}`;
    const started = performance.now();
    let response;
    try {
        response = await fetch(API + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (err) {
        logRequest(method, path, 0, Math.round(performance.now() - started));
        throw new ApiError(0, null);
    }
    logRequest(method, path, response.status, Math.round(performance.now() - started));
    if (response.status === 401 && auth && retry && sessionStorage.getItem(REFRESH_KEY)) {
        if (await refreshTokens()) return request(method, path, body, { retry: false, auth });
    }
    const text = await response.text();
    let data = null;
    if (text) {
        try { data = JSON.parse(text); } catch { data = { detail: text.slice(0, 200) }; }
    }
    if (!response.ok) {
        if (response.status === 401 && auth) logout(false);
        throw new ApiError(response.status, data);
    }
    return data;
}
const api = {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    put: (p, b) => request("PUT", p, b),
    patch: (p, b) => request("PATCH", p, b),
    del: (p) => request("DELETE", p),
};

async function login(username, password) {
    const data = await request("POST", "/api/token/", { username, password }, { auth: false, retry: false });
    state.access = data.access;
    sessionStorage.setItem(REFRESH_KEY, data.refresh);
}
async function refreshTokens() {
    const refresh = sessionStorage.getItem(REFRESH_KEY);
    if (!refresh) return false;
    try {
        const data = await request("POST", "/api/token/refresh/", { refresh }, { auth: false, retry: false });
        state.access = data.access;
        if (data.refresh) sessionStorage.setItem(REFRESH_KEY, data.refresh);
        return true;
    } catch {
        sessionStorage.removeItem(REFRESH_KEY);
        return false;
    }
}
async function logout(callServer = true) {
    const refresh = sessionStorage.getItem(REFRESH_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
    if (callServer && refresh) {
        try { await request("POST", "/api/token/logout/", { refresh }, { auth: false, retry: false }); } catch { /* ya expiró */ }
    }
    state.access = null;
    state.user = null;
    state.cache = {};
    showLogin();
}

// ---------- Datos relacionados (listas desplegables y nombres) ----------
async function related(name) {
    if (!state.cache[name]) {
        const data = await api.get(`/api/${name}/?page_size=200`);
        state.cache[name] = data.results || data;
    }
    return state.cache[name];
}
function labelFor(ref, id) {
    const row = (state.cache[ref] || []).find((r) => r.id === id);
    if (!row) return id == null ? "—" : `#${id}`;
    const fn = (RESOURCES[ref] && RESOURCES[ref].label) || LABELS[ref] || ((r) => r.nombre || `#${r.id}`);
    return fn(row);
}

// ---------- Vistas ----------
function showLogin() {
    $("#app-view").hidden = true;
    $("#login-view").hidden = false;
    $("#username").focus();
}
function renderNav() {
    const current = location.hash.replace(/^#\/?/, "").split("/")[0] || "inicio";
    const items = [["inicio", "Inicio"], ...Object.entries(RESOURCES).map(([k, r]) => [k, r.title])];
    $("#nav").innerHTML = items.map(([key, title]) =>
        `<a href="#/${key}"${key === current ? ' aria-current="page"' : ""}>${esc(title)}</a>`).join("");
}

async function showApp() {
    $("#login-view").hidden = true;
    $("#app-view").hidden = false;
    if (!state.user) state.user = await api.get("/api/yo/");
    $("#who").textContent = state.user.nombre;
    $("#role").textContent = state.user.rol;
    route();
}

async function route() {
    if (!state.access) return showLogin();
    renderNav();
    const [section, id] = location.hash.replace(/^#\/?/, "").split("/");
    const view = $("#view");
    view.innerHTML = '<p class="muted">Cargando…</p>';
    try {
        if (!section || section === "inicio") await renderHome(view);
        else if (RESOURCES[section] && id === "nuevo") await renderForm(view, section, null);
        else if (RESOURCES[section] && id) await renderForm(view, section, Number(id));
        else if (RESOURCES[section]) await renderList(view, section);
        else location.hash = "#/inicio";
    } catch (err) {
        view.innerHTML = `<p class="alert error">${esc(err.message)}</p>`;
    }
    $("#main").focus();
}

async function renderHome(view) {
    const [health, ...counts] = await Promise.all([
        request("GET", "/api/salud/", undefined, { auth: false }),
        ...Object.keys(RESOURCES).map((k) => api.get(`/api/${k}/?page_size=1`).then((d) => d.count)),
    ]);
    view.innerHTML = `
        <h1>Hola, ${esc(state.user.nombre)}</h1>
        <p class="muted">Conectado a <code>${esc(API)}</code> · API ${esc(health.status)} · base de datos ${esc(health.database)}</p>
        <div class="stats">
            ${Object.entries(RESOURCES).map(([k, r], i) =>
                `<a class="stat" href="#/${k}"><strong>${counts[i]}</strong> ${esc(r.title.toLowerCase())}</a>`).join("")}
        </div>
        <section class="card">
            <h2>Cómo funciona</h2>
            <ol class="steps">
                <li>Ingresas con usuario y contraseña: la API entrega un <strong>access token</strong> (15 min) y un <strong>refresh token</strong>.</li>
                <li>Cada solicitud viaja como JSON a <strong>API Gateway</strong>, que aplica el límite de solicitudes y la reenvía a Django.</li>
                <li>Django valida el token, los permisos del rol y las reglas de negocio, y guarda los datos en <strong>RDS PostgreSQL</strong>.</li>
            </ol>
        </section>`;
}

async function renderList(view, name, page = 1, query = "") {
    const res = RESOURCES[name];
    const refs = [...new Set(res.columns.map((c) => c[2]).filter((t) => t && !["datetime", "date", "estado"].includes(t)))];
    await Promise.all(refs.map(related));
    const data = await api.get(`/api/${name}/?page=${page}&search=${encodeURIComponent(query)}`);
    const cell = (row, [key, , type]) => {
        const value = row[key];
        if (type === "datetime") return esc(fmtDateTime(value));
        if (type === "date") return esc(fmtDate(value));
        if (type === "estado") return `<span class="tag ${esc(value)}">${esc((ESTADOS_CITA.find((e) => e[0] === value) || [, value])[1])}</span>`;
        if (type) return esc(labelFor(type, value));
        return esc(String(value ?? "—").slice(0, 90));
    };
    view.innerHTML = `
        <div class="toolbar">
            <h1>${esc(res.title)}</h1>
            <a class="button" href="#/${name}/nuevo">${esc(res.nuevo)}</a>
        </div>
        <form class="search" id="search"><input name="q" type="search" placeholder="Buscar" value="${esc(query)}" aria-label="Buscar"><button class="secondary">Buscar</button></form>
        <div class="table-wrap"><table>
            <thead><tr>${res.columns.map((c) => `<th scope="col">${esc(c[1])}</th>`).join("")}<th></th></tr></thead>
            <tbody>${data.results.map((row) => `<tr>${res.columns.map((c) => `<td>${cell(row, c)}</td>`).join("")}
                <td class="actions"><a href="#/${name}/${row.id}">Editar</a><button class="linkish" data-delete="${row.id}">Eliminar</button></td></tr>`).join("")
                || `<tr><td colspan="${res.columns.length + 1}">No hay registros.</td></tr>`}</tbody>
        </table></div>
        <p class="muted pager">${data.count} registros${data.previous ? ' · <button class="linkish" data-page="-1">Anterior</button>' : ""}${data.next ? ' · <button class="linkish" data-page="1">Siguiente</button>' : ""}</p>`;
    $("#search").addEventListener("submit", (e) => { e.preventDefault(); renderList(view, name, 1, e.target.q.value.trim()); });
    view.querySelectorAll("[data-page]").forEach((b) => b.addEventListener("click", () => renderList(view, name, page + Number(b.dataset.page), query)));
    view.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", async () => {
        if (!confirm(`¿Eliminar este registro de ${res.title.toLowerCase()}?`)) return;
        try {
            await api.del(`/api/${name}/${b.dataset.delete}/`);
            delete state.cache[name];
            flash("Registro eliminado (204 No Content).");
            renderList(view, name, page, query);
        } catch (err) { flash(err.message, "error"); }
    }));
}

function fieldHtml(field, value, options) {
    const id = `f-${field.name}`;
    const req = field.required ? " required" : "";
    let input;
    if (field.type === "fk") {
        const rows = options.filter((r) => !field.onlyActive || r.activo !== false || r.id === value);
        input = `<select id="${id}" name="${field.name}"${req}><option value="">—</option>${rows.map((r) =>
            `<option value="${r.id}"${r.id === value ? " selected" : ""}>${esc(labelFor(field.ref, r.id))}</option>`).join("")}</select>`;
    } else if (field.type === "select") {
        input = `<select id="${id}" name="${field.name}">${field.options.map(([v, l]) =>
            `<option value="${v}"${v === (value ?? field.options[0][0]) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    } else if (field.type === "textarea") {
        input = `<textarea id="${id}" name="${field.name}"${req}>${esc(value ?? "")}</textarea>`;
    } else {
        const type = { datetime: "datetime-local", date: "date", email: "email", number: "number" }[field.type] || "text";
        const val = field.type === "datetime" ? toLocalInput(value) : (value ?? "");
        input = `<input id="${id}" name="${field.name}" type="${type}"${field.step ? ` step="${field.step}"` : ""} value="${esc(val)}"${req}>`;
    }
    return `<p class="field"><label for="${id}">${esc(field.label)}</label>${input}<span class="field-error" data-error="${field.name}"></span></p>`;
}

async function renderForm(view, name, id) {
    const res = RESOURCES[name];
    const refs = res.fields.filter((f) => f.type === "fk").map((f) => f.ref);
    await Promise.all(refs.map(related));
    const row = id ? await api.get(`/api/${name}/${id}/`) : {};
    view.innerHTML = `
        <a class="back" href="#/${name}">Volver a ${esc(res.title.toLowerCase())}</a>
        <form class="card form" id="record-form" novalidate>
            <h1>${id ? `Editar ${esc(res.singular)}` : esc(res.nuevo)}</h1>
            ${res.help ? `<p class="muted">${esc(res.help)}</p>` : ""}
            <p class="alert error" id="form-error" hidden></p>
            ${res.fields.map((f) => fieldHtml(f, row[f.name], state.cache[f.ref] || [])).join("")}
            <div class="row"><button type="submit">${id ? "Guardar cambios" : "Crear"}</button><a href="#/${name}">Cancelar</a></div>
        </form>`;
    $("#record-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.target;
        form.querySelectorAll("[data-error]").forEach((e) => { e.textContent = ""; });
        $("#form-error").hidden = true;
        const body = {};
        for (const field of res.fields) {
            const raw = form.elements[field.name].value.trim();
            let value;
            if (field.type === "fk") value = raw ? Number(raw) : null;
            else if (field.type === "number") value = raw ? (field.step ? raw : Number(raw)) : null;
            else if (field.type === "datetime") value = raw ? new Date(raw).toISOString() : null;
            else if (field.type === "date") value = raw || null;
            else value = raw;  // Texto: "" permite que la API responda "no puede estar en blanco".
            if (value === null && field.omitEmpty) continue;
            body[field.name] = value;
        }
        try {
            if (id) await api.patch(`/api/${name}/${id}/`, body);
            else await api.post(`/api/${name}/`, body);
            delete state.cache[name];
            flash(id ? "Cambios guardados (200 OK)." : "Registro creado (201 Created).");
            location.hash = `#/${name}`;
        } catch (err) {
            if (err.status === 400 && err.data && typeof err.data === "object" && !Array.isArray(err.data)) {
                let general = [];
                for (const [key, messages] of Object.entries(err.data)) {
                    const slot = form.querySelector(`[data-error="${key}"]`);
                    const text = [].concat(messages).join(" ");
                    if (slot) slot.textContent = text; else general.push(text);
                }
                $("#form-error").textContent = general.join(" ") || "Revisa los campos marcados (400 Bad Request).";
            } else {
                $("#form-error").textContent = err.message;
            }
            $("#form-error").hidden = false;
        }
    });
}

// ---------- Arranque ----------
$("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("#login-error");
    error.hidden = true;
    const button = event.target.querySelector("button");
    button.disabled = true;
    try {
        await login(event.target.username.value.trim(), event.target.password.value);
        event.target.password.value = "";
        if (!location.hash || location.hash === "#/") location.hash = "#/inicio";
        await showApp();
    } catch (err) {
        error.textContent = err.status === 401 ? "Usuario o contraseña incorrectos." : err.message;
        error.hidden = false;
    } finally {
        button.disabled = false;
    }
});
$("#logout").addEventListener("click", () => logout(true));
window.addEventListener("hashchange", route);

(async function start() {
    if (await refreshTokens()) {
        try { await showApp(); return; } catch { /* sesión inválida */ }
    }
    showLogin();
})();
