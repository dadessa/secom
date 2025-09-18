# dashboard_secom.py
# SECOM • Dashboard de Processos (Dash)
# - Lê planilha Google Sheets (XLSX via export)
# - Seleciona aba, filtra e plota gráficos + tabela detalhada
# - Tema Claro/Escuro (padrão Claro)
# - Botão "Atualizar dados" força limpeza do cache
# - Download do recorte filtrado em CSV
# - Sobe mesmo se a planilha falhar (DF vazio) e loga no console

from __future__ import annotations

import os
import sys
import traceback
from io import BytesIO
from functools import lru_cache
from typing import Iterable, List, Tuple

import requests
import pandas as pd
import numpy as np
import plotly.express as px

from dash import (
    Dash, dcc, html, dash_table, Input, Output, State, no_update
)
from flask import Flask

# ====== Configuração ======

DEFAULT_EXCEL_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/"
    "export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)

EXCEL_URL = os.environ.get("EXCEL_URL", DEFAULT_EXCEL_URL).strip()

EXPECTED_COLS = [
    "CAMPANHA",
    "SECRETARIA",
    "AGÊNCIA",
    "VALOR DO ESPELHO",
    "PROCESSO",
    "EMPENHO",
    "DATA DO EMPENHO",
    "COMPETÊNCIA",
    "OBSERVAÇÃO",
    "ESPELHO DIANA",
    "ESPELHO",
    "PDF",
]

LINK_COLS = ["PROCESSO", "EMPENHO", "ESPELHO DIANA", "ESPELHO", "PDF"]


def _log(*a):
    print(*a, file=sys.stdout, flush=True)


def _download_bytes(url: str) -> bytes:
    if not url:
        raise ValueError("EXCEL_URL não configurada.")
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    return r.content


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=EXPECTED_COLS + ["COMPETÊNCIA_DT"])


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Normaliza nomes prováveis
    mapping = {
        "VALOR": "VALOR DO ESPELHO",
        "VALOR_ESPELHO": "VALOR DO ESPELHO",
        "AGENCIA": "AGÊNCIA",
        "COMPETENCIA": "COMPETÊNCIA",
        "OBSERVACAO": "OBSERVAÇÃO",
        "DATA EMPENHO": "DATA DO EMPENHO",
        "DATA_EMPENHO": "DATA DO EMPENHO",
    }
    new_cols = []
    for c in df.columns:
        k = str(c).strip()
        k_up = k.upper()
        k = mapping.get(k_up, k)
        new_cols.append(k)
    df.columns = new_cols

    # Garante todas as colunas esperadas
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    # Tipagem
    df["VALOR DO ESPELHO"] = pd.to_numeric(df["VALOR DO ESPELHO"], errors="coerce").fillna(0.0)

    # Competência (mensal) e Data do Empenho
    comp = pd.to_datetime(df["COMPETÊNCIA"], errors="coerce", dayfirst=True)
    # se vier "YYYY-MM" como texto também funciona
    df["COMPETÊNCIA_DT"] = comp.dt.to_period("M").dt.to_timestamp()

    df["DATA DO EMPENHO"] = pd.to_datetime(df["DATA DO EMPENHO"], errors="coerce", dayfirst=True)

    # Strings limpas
    for c in ["CAMPANHA", "SECRETARIA", "AGÊNCIA", "PROCESSO", "EMPENHO", "OBSERVAÇÃO", "ESPELHO DIANA", "ESPELHO", "PDF"]:
        df[c] = df[c].astype(str).replace({"nan": "", "None": ""}).str.strip()

    return df


@lru_cache(maxsize=8)
def list_sheets(url: str) -> Tuple[str, ...]:
    try:
        content = _download_bytes(url)
        xl = pd.ExcelFile(BytesIO(content))
        return tuple(xl.sheet_names)
    except Exception as e:
        _log("ERRO list_sheets:", repr(e))
        traceback.print_exc()
        return tuple()


@lru_cache(maxsize=32)
def load_sheet(url: str, sheet_name: str | None) -> pd.DataFrame:
    """Carrega uma aba específica; se None, concatena todas."""
    try:
        content = _download_bytes(url)
        if sheet_name:
            df = pd.read_excel(BytesIO(content), sheet_name=sheet_name, dtype=str)
            return _normalize_columns(df)

        xl = pd.ExcelFile(BytesIO(content))
        dfs = []
        for s in xl.sheet_names:
            d = pd.read_excel(BytesIO(content), sheet_name=s, dtype=str)
            d = _normalize_columns(d)
            d["__ABA__"] = s
            dfs.append(d)
        if not dfs:
            return _empty_df()
        return pd.concat(dfs, ignore_index=True)
    except Exception as e:
        _log("ERRO load_sheet:", repr(e))
        traceback.print_exc()
        return _empty_df()


def clear_cache():
    list_sheets.cache_clear()
    load_sheet.cache_clear()


def _sorted_unique_strings(series: pd.Series) -> List[str]:
    vals = series.fillna("").astype(str).str.strip()
    vals = vals[vals != ""].unique().tolist()
    vals = [v for v in vals if v]  # remove vazios
    return sorted(vals, key=lambda x: x.lower())


def _format_brl(x: float | int | None) -> str:
    try:
        v = float(x or 0.0)
    except Exception:
        v = 0.0
    # pt-BR simples sem locale
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _link_md(url: str, label: str) -> str:
    u = (url or "").strip()
    if u.startswith("http://") or u.startswith("https://"):
        return f"[{label}]({u})"
    return ""


def _table_payload(df: pd.DataFrame) -> Tuple[List[dict], List[dict]]:
    if df.empty:
        cols = [
            {"name": "CAMPANHA", "id": "CAMPANHA"},
            {"name": "SECRETARIA", "id": "SECRETARIA"},
            {"name": "AGÊNCIA", "id": "AGÊNCIA"},
            {"name": "VALOR DO ESPELHO", "id": "VALOR_FMT"},
            {"name": "PROCESSO", "id": "PROCESSO_MD", "presentation": "markdown"},
            {"name": "EMPENHO", "id": "EMPENHO_MD", "presentation": "markdown"},
            {"name": "DATA DO EMPENHO", "id": "DATA_EMPENHO_FMT"},
            {"name": "COMPETÊNCIA", "id": "COMP_TXT"},
            {"name": "OBSERVAÇÃO", "id": "OBSERVAÇÃO"},
            {"name": "DIANA", "id": "DIANA_MD", "presentation": "markdown"},
            {"name": "ESPELHO", "id": "ESPELHO_MD", "presentation": "markdown"},
            {"name": "PDF", "id": "PDF_MD", "presentation": "markdown"},
        ]
        return [], cols

    d = df.copy()

    # campos formatados
    d["VALOR_FMT"] = d["VALOR DO ESPELHO"].apply(_format_brl)
    d["DATA_EMPENHO_FMT"] = d["DATA DO EMPENHO"].dt.strftime("%d/%m/%Y").fillna("")
    # competência texto (Mês/Ano ou YYYY-MM se preferir)
    d["COMP_TXT"] = d["COMPETÊNCIA_DT"].dt.strftime("%Y-%m").fillna(d["COMPETÊNCIA"].astype(str))

    d["PROCESSO_MD"] = d["PROCESSO"].apply(lambda u: _link_md(u, "Processo"))
    d["EMPENHO_MD"] = d["EMPENHO"].apply(lambda u: _link_md(u, "Empenho"))
    d["DIANA_MD"] = d["ESPELHO DIANA"].apply(lambda u: _link_md(u, "Diana"))
    d["ESPELHO_MD"] = d["ESPELHO"].apply(lambda u: _link_md(u, "Espelho"))
    d["PDF_MD"] = d["PDF"].apply(lambda u: _link_md(u, "PDF"))

    cols = [
        {"name": "CAMPANHA", "id": "CAMPANHA"},
        {"name": "SECRETARIA", "id": "SECRETARIA"},
        {"name": "AGÊNCIA", "id": "AGÊNCIA"},
        {"name": "VALOR DO ESPELHO", "id": "VALOR_FMT"},
        {"name": "PROCESSO", "id": "PROCESSO_MD", "presentation": "markdown"},
        {"name": "EMPENHO", "id": "EMPENHO_MD", "presentation": "markdown"},
        {"name": "DATA DO EMPENHO", "id": "DATA_EMPENHO_FMT"},
        {"name": "COMPETÊNCIA", "id": "COMP_TXT"},
        {"name": "OBSERVAÇÃO", "id": "OBSERVAÇÃO"},
        {"name": "DIANA", "id": "DIANA_MD", "presentation": "markdown"},
        {"name": "ESPELHO", "id": "ESPELHO_MD", "presentation": "markdown"},
        {"name": "PDF", "id": "PDF_MD", "presentation": "markdown"},
    ]

    order = [c["id"] for c in cols]
    data = d[order].to_dict("records")
    return data, cols


def _apply_filters(
    df: pd.DataFrame,
    f_sec: List[str] | None,
    f_age: List[str] | None,
    f_cam: List[str] | None,
    f_comp: List[str] | None,
    search: str | None,
) -> pd.DataFrame:
    if df.empty:
        return df

    d = df.copy()

    def _isin(col, values):
        if not values:
            return pd.Series(True, index=d.index)
        v = [str(x).strip() for x in values if str(x).strip()]
        return d[col].astype(str).isin(v)

    mask = pd.Series(True, index=d.index)

    mask &= _isin("SECRETARIA", f_sec)
    mask &= _isin("AGÊNCIA", f_age)
    mask &= _isin("CAMPANHA", f_cam)

    if f_comp:
        # valores enviados como YYYY-MM
        comps = [str(x).strip() for x in f_comp if str(x).strip()]
        m2 = d["COMPETÊNCIA_DT"].dt.strftime("%Y-%m").isin(comps)
        # fallback textual se não tiver COMPETÊNCIA_DT
        m3 = d["COMPETÊNCIA"].astype(str).isin(comps)
        mask &= (m2 | m3)

    if search:
        s = search.strip().lower()
        if s:
            txt_cols = ["PROCESSO", "EMPENHO", "OBSERVAÇÃO", "CAMPANHA"]
            m = pd.Series(False, index=d.index)
            for c in txt_cols:
                m |= d[c].astype(str).str.lower().str.contains(s, na=False)
            mask &= m

    return d[mask].copy()


# ====== App ======

external_scripts = []
external_stylesheets = []

app = Dash(__name__, suppress_callback_exceptions=True, external_scripts=external_scripts, external_stylesheets=external_stylesheets)
server: Flask = app.server
app.title = "SECOM • Dashboard de Processos"

# Endpoint de saúde para Render
@server.route("/healthz")
def healthz():
    return "ok", 200

# ---- Layout ----

app.layout = html.Div(
    id="root",
    className="theme-light",  # padrão CLARO
    children=[
        dcc.Store(id="store-current-sheet"),
        dcc.Download(id="download-data"),
        html.Div(
            className="header",
            children=[
                html.H2("SECOM • Dashboard de Processos"),
                html.Div(
                    className="toolbar",
                    children=[
                        html.Span("Tema:"),
                        dcc.RadioItems(
                            id="theme",
                            options=[
                                {"label": "Claro", "value": "claro"},
                                {"label": "Escuro", "value": "escuro"},
                            ],
                            value="claro",  # padrão claro
                            inline=True,
                            inputStyle={"margin-right": "4px", "margin-left": "12px"},
                        ),
                        html.Button("Atualizar dados", id="btn-refresh", n_clicks=0, className="btn"),
                        dcc.Input(
                            id="excel-url",
                            value=EXCEL_URL,
                            type="text",
                            placeholder="URL de export do Google Sheets (xlsx)",
                            style={"minWidth": "420px", "marginLeft": "8px"},
                        ),
                    ],
                ),
            ],
        ),

        html.Div(
            className="filters",
            children=[
                html.Div(
                    children=[
                        html.Label("Aba da planilha"),
                        dcc.Dropdown(id="sheet-picker", placeholder="Escolha a aba...", clearable=False),
                    ],
                    style={"minWidth": "280px"},
                ),
                html.Div(
                    children=[
                        html.Label("Secretaria"),
                        dcc.Dropdown(id="f_secretaria", multi=True, placeholder="Selecione..."),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label("Agência"),
                        dcc.Dropdown(id="f_agencia", multi=True, placeholder="Selecione..."),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label("Campanha"),
                        dcc.Dropdown(id="f_campanha", multi=True, placeholder="Selecione..."),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label("Período (Competência)"),
                        dcc.Dropdown(id="f_compet", multi=True, placeholder="Selecione..."),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label("Busca (processo / observação / campanha)"),
                        dcc.Input(id="f_search", type="text", placeholder="Digite um termo", style={"width": "100%"}),
                    ],
                    style={"minWidth": "320px"},
                ),
                html.Div(
                    children=[
                        html.Label(""),
                        html.Button("Baixar CSV", id="btn-download", className="btn"),
                    ],
                    style={"alignSelf": "end"},
                ),
            ],
            style={"display": "grid", "gridTemplateColumns": "280px 1fr 1fr 1fr 1fr 320px 160px", "gap": "12px"},
        ),

        # KPIs
        html.Div(
            className="kpis",
            children=[
                html.Div([html.Div("Total (Valor do Espelho)", className="kpi-title"), html.H3(id="kpi_total")], className="card"),
                html.Div([html.Div("Qtd. de linhas", className="kpi-title"), html.H3(id="kpi_rows")], className="card"),
                html.Div([html.Div("Mediana por linha", className="kpi-title"), html.H3(id="kpi_med")], className="card"),
                html.Div([html.Div("Processos distintos", className="kpi-title"), html.H3(id="kpi_proc")], className="card"),
            ],
            style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "12px", "marginTop": "10px"},
        ),

        # Gráficos
        html.Div(
            className="charts",
            children=[
                html.Div([html.H4("Evolução mensal"), dcc.Graph(id="g_evolucao", figure=px.scatter())], className="card"),
                html.Div([html.H4("Top 10 Secretarias"), dcc.Graph(id="g_top_sec", figure=px.scatter())], className="card"),
                html.Div([html.H4("Top 10 Agências"), dcc.Graph(id="g_top_ag", figure=px.scatter())], className="card"),
                html.Div([html.H4("Treemap Secretaria → Agência"), dcc.Graph(id="g_treemap", figure=px.scatter())], className="card"),
                html.Div([html.H4("Campanhas por valor"), dcc.Graph(id="g_campanhas", figure=px.scatter())], className="card"),
            ],
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginTop": "10px"},
        ),

        html.Div(
            className="table-wrap card",
            children=[
                html.H4("Dados detalhados"),
                dash_table.DataTable(
                    id="tbl_detalhe",
                    page_size=12,
                    filter_action="native",
                    sort_action="native",
                    style_table={"overflowX": "auto"},
                    style_as_list_view=True,
                    style_header={"fontWeight": "600"},
                    style_cell={"padding": "8px", "whiteSpace": "normal", "height": "auto"},
                ),
            ],
            style={"marginTop": "10px"},
        ),
    ],
)

# ====== Callbacks ======

# Tema Claro/Escuro
@app.callback(
    Output("root", "className"),
    Input("theme", "value"),
    prevent_initial_call=False,
)
def set_theme(theme_value: str):
    return "theme-light" if (theme_value or "claro") == "claro" else "theme-dark"


# Popular lista de abas + limpar cache quando clicar em atualizar
@app.callback(
    Output("sheet-picker", "options"),
    Output("sheet-picker", "value"),
    Input("btn-refresh", "n_clicks"),
    State("excel-url", "value"),
    prevent_initial_call=False,
)
def refresh_sheets(n_clicks, url):
    url = (url or "").strip()
    # limpa cache para forçar novo download
    clear_cache()
    sheets = list_sheets(url)
    options = [{"label": s, "value": s} for s in sheets]
    value = options[0]["value"] if options else None
    return options, value


# Atualiza opções dos filtros ao trocar de aba
@app.callback(
    Output("f_secretaria", "options"),
    Output("f_agencia", "options"),
    Output("f_campanha", "options"),
    Output("f_compet", "options"),
    Input("sheet-picker", "value"),
    State("excel-url", "value"),
    prevent_initial_call=False,
)
def update_filter_options(sheet, url):
    if not sheet:
        return [], [], [], []
    df = load_sheet((url or "").strip(), sheet)
    if df.empty:
        return [], [], [], []
    sec_opts = [{"label": v, "value": v} for v in _sorted_unique_strings(df["SECRETARIA"])]
    age_opts = [{"label": v, "value": v} for v in _sorted_unique_strings(df["AGÊNCIA"])]
    cam_opts = [{"label": v, "value": v} for v in _sorted_unique_strings(df["CAMPANHA"])]

    comp_series = df["COMPETÊNCIA_DT"].dt.strftime("%Y-%m").fillna(df["COMPETÊNCIA"].astype(str))
    comp_vals = _sorted_unique_strings(comp_series)
    comp_opts = [{"label": v, "value": v} for v in comp_vals]

    return sec_opts, age_opts, cam_opts, comp_opts


# Atualiza KPIs, gráficos e tabela conforme filtros
@app.callback(
    Output("kpi_total", "children"),
    Output("kpi_rows", "children"),
    Output("kpi_med", "children"),
    Output("kpi_proc", "children"),
    Output("g_evolucao", "figure"),
    Output("g_top_sec", "figure"),
    Output("g_top_ag", "figure"),
    Output("g_treemap", "figure"),
    Output("g_campanhas", "figure"),
    Output("tbl_detalhe", "data"),
    Output("tbl_detalhe", "columns"),
    Input("sheet-picker", "value"),
    Input("f_secretaria", "value"),
    Input("f_agencia", "value"),
    Input("f_campanha", "value"),
    Input("f_compet", "value"),
    Input("f_search", "value"),
    State("excel-url", "value"),
    prevent_initial_call=False,
)
def update_outputs(sheet, v_sec, v_age, v_cam, v_comp, search, url):
    url = (url or "").strip()
    if not sheet:
        empty_fig = px.scatter()
        data, cols = _table_payload(_empty_df())
        return "R$ 0,00", "0", "R$ 0,00", "0", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, data, cols

    df = load_sheet(url, sheet)
    if df.empty:
        empty_fig = px.scatter()
        data, cols = _table_payload(df)
        return "R$ 0,00", "0", "R$ 0,00", "0", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, data, cols

    # Filtros
    dff = _apply_filters(df, v_sec, v_age, v_cam, v_comp, search)

    # KPIs
    total = dff["VALOR DO ESPELHO"].sum() if not dff.empty else 0.0
    med = float(dff["VALOR DO ESPELHO"].median()) if not dff.empty else 0.0
    nrows = len(dff)
    nproc = dff["PROCESSO"].replace("", np.nan).nunique() if not dff.empty else 0

    kpi_total = _format_brl(total)
    kpi_med = _format_brl(med)
    kpi_rows = f"{nrows:,}".replace(",", ".")
    kpi_proc = f"{nproc:,}".replace(",", ".")

    # --- Gráficos ---

    # Evolução mensal
    if dff["COMPETÊNCIA_DT"].notna().any():
        evo = dff.dropna(subset=["COMPETÊNCIA_DT"]).groupby("COMPETÊNCIA_DT", as_index=False)["VALOR DO ESPELHO"].sum()
        evo = evo.sort_values("COMPETÊNCIA_DT")
        fig_evo = px.line(evo, x="COMPETÊNCIA_DT", y="VALOR DO ESPELHO", markers=True)
        fig_evo.update_layout(yaxis_title="Valor", xaxis_title="Competência", hovermode="x unified")
    else:
        fig_evo = px.scatter()

    # Top 10 Secretarias (horizontal)
    if not dff.empty:
        g1 = (
            dff.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"]
            .sum()
            .sort_values("VALOR DO ESPELHO", ascending=False)
            .head(10)
        )
        fig_sec = px.bar(g1, x="VALOR DO ESPELHO", y="SECRETARIA", orientation="h")
        fig_sec.update_layout(yaxis_title="", xaxis_title="Valor")
    else:
        fig_sec = px.scatter()

    # Top 10 Agências (horizontal)
    if not dff.empty:
        g2 = (
            dff.groupby("AGÊNCIA", as_index=False)["VALOR DO ESPELHO"]
            .sum()
            .sort_values("VALOR DO ESPELHO", ascending=False)
            .head(10)
        )
        fig_age = px.bar(g2, x="VALOR DO ESPELHO", y="AGÊNCIA", orientation="h")
        fig_age.update_layout(yaxis_title="", xaxis_title="Valor")
    else:
        fig_age = px.scatter()

    # Treemap Secretaria → Agência
    if not dff.empty:
        g3 = (
            dff.groupby(["SECRETARIA", "AGÊNCIA"], as_index=False)["VALOR DO ESPELHO"]
            .sum()
            .sort_values("VALOR DO ESPELHO", ascending=False)
        )
        fig_tree = px.treemap(g3, path=["SECRETARIA", "AGÊNCIA"], values="VALOR DO ESPELHO")
    else:
        fig_tree = px.scatter()

    # Campanhas por valor (Top N)
    if not dff.empty:
        g4 = (
            dff.groupby("CAMPANHA", as_index=False)["VALOR DO ESPELHO"]
            .sum()
            .sort_values("VALOR DO ESPELHO", ascending=False)
            .head(15)
        )
        fig_cam = px.bar(g4, x="CAMPANHA", y="VALOR DO ESPELHO")
        fig_cam.update_layout(xaxis_title="", yaxis_title="Valor")
    else:
        fig_cam = px.scatter()

    # Tabela
    data, cols = _table_payload(dff)

    return kpi_total, kpi_rows, kpi_med, kpi_proc, fig_evo, fig_sec, fig_age, fig_tree, fig_cam, data, cols


# Download CSV do recorte filtrado
@app.callback(
    Output("download-data", "data"),
    Input("btn-download", "n_clicks"),
    State("sheet-picker", "value"),
    State("f_secretaria", "value"),
    State("f_agencia", "value"),
    State("f_campanha", "value"),
    State("f_compet", "value"),
    State("f_search", "value"),
    State("excel-url", "value"),
    prevent_initial_call=True,
)
def download_csv(n, sheet, v_sec, v_age, v_cam, v_comp, search, url):
    if not n or not sheet:
        return no_update
    df = load_sheet((url or "").strip(), sheet)
    if df.empty:
        # devolve CSV vazio com cabeçalho
        return dcc.send_string(_empty_df().to_csv(index=False), "dados_filtrados.csv")

    dff = _apply_filters(df, v_sec, v_age, v_cam, v_comp, search)
    return dcc.send_data_frame(dff.to_csv, "dados_filtrados.csv", index=False)


# ====== Estilos básicos embutidos (opcional) ======
# Se você já possui assets/style.css no repositório, pode remover este bloco!
app.clientside_callback(
    """
    function(n) {
        // apenas para forçar a carga dos estilos embutidos na primeira renderização
        return '';
    }
    """,
    Output("store-current-sheet", "data"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)

# Pequeno CSS para tema claro/escuro (use assets/style.css para algo mais elaborado)
STYLE_TAG = html.Style("""
:root { --bg:#0f1220; --card:#151a2c; --text:#f5f7fb; --muted:#aab1c5; }
.theme-light { --bg:#f6f7fb; --card:#ffffff; --text:#14161a; --muted:#616b7a; }

body { background: var(--bg); color: var(--text); font-family: Inter,system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,'Helvetica Neue','Noto Sans',Arial,'Apple Color Emoji','Segoe UI Emoji','Segoe UI Symbol'; }
#root { padding: 16px 18px 28px; }

.header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.toolbar { display:flex; align-items:center; gap:10px; }

.filters label { font-size:12px; color:var(--muted); margin-bottom:4px; display:block; }
.card { background: var(--card); border-radius:12px; padding:12px 14px; box-shadow: 0 1px 0 rgba(0,0,0,.04); }
.kpi-title { font-size:12px; color:var(--muted); }
h2,h3,h4 { margin: 6px 0; }
.btn { padding:8px 12px; border:none; border-radius:8px; background:#3b82f6; color:#fff; cursor:pointer; }
.btn:hover { filter:brightness(1.05); }
.dash-table-container .dash-spreadsheet-container table { color: var(--text); }
""")

# injeta o style no layout
app.layout.children.insert(0, STYLE_TAG)


if __name__ == "__main__":
    # Execução local: python dashboard_secom.py
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False)
