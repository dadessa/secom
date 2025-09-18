# dashboard_secom.py
# -*- coding: utf-8 -*-

import os
import io
import math
import sys
import json
import time
import traceback
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import requests
import pandas as pd
import numpy as np
from io import BytesIO

import plotly.express as px
import plotly.graph_objects as go

from dash import Dash, dcc, html, dash_table, Input, Output, State, ctx, no_update
from dash.dash_table.Format import Format, Scheme, Group

# -----------------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------------

# URL pública do Google Sheets (exporta XLSX)
DEFAULT_EXCEL_URL = os.environ.get(
    "EXCEL_URL",
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)

REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "40"))
DEFAULT_THEME = os.environ.get("DEFAULT_THEME", "light")  # 'light' ou 'dark'
GRAPH_HEIGHT = int(os.environ.get("GRAPH_HEIGHT", "420"))

# Nomes de colunas esperadas (mapeadas/normalizadas)
COL_ALIASES: Dict[str, str] = {
    # chave possível -> nome canônico
    "campanha": "CAMPANHA",
    "CAMPANHA": "CAMPANHA",

    "secretaria": "SECRETARIA",
    "SECRETARIA": "SECRETARIA",

    "agência": "AGENCIA",
    "AGÊNCIA": "AGENCIA",
    "agencia": "AGENCIA",
    "AGENCIA": "AGENCIA",

    "valor do espelho": "VALOR",
    "VALOR DO ESPELHO": "VALOR",
    "VALOR_DO_ESPELHO": "VALOR",
    "VALOR": "VALOR",

    "processo": "PROCESSO",
    "PROCESSO": "PROCESSO",

    "empenho": "EMPENHO",
    "EMPENHO": "EMPENHO",

    "data do empenho": "DATA_DO_EMPENHO",
    "DATA DO EMPENHO": "DATA_DO_EMPENHO",
    "DATA_DO_EMPENHO": "DATA_DO_EMPENHO",

    "competência": "COMPETENCIA_TXT",
    "COMPETÊNCIA": "COMPETENCIA_TXT",
    "COMPETÊNCIA_TXT": "COMPETENCIA_TXT",
    "COMPETENCIA_TXT": "COMPETENCIA_TXT",

    "competência_dt": "COMPETENCIA_DT",
    "COMPETÊNCIA_DT": "COMPETENCIA_DT",
    "COMPETENCIA_DT": "COMPETENCIA_DT",

    "observação": "OBSERVACAO",
    "OBSERVAÇÃO": "OBSERVACAO",
    "OBSERVACAO": "OBSERVACAO",

    "espelho diana": "ESPELHO_DIANA",
    "ESPELHO DIANA": "ESPELHO_DIANA",
    "ESPELHO_DIANA": "ESPELHO_DIANA",

    "espelho": "ESPELHO",
    "ESPELHO": "ESPELHO",

    "pdf": "PDF",
    "PDF": "PDF",
}

DISPLAY_COLUMNS = [
    "CAMPANHA",
    "SECRETARIA",
    "AGENCIA",
    "VALOR_FMT",
    "PROCESSO_MD",
    "EMPENHO_MD",
    "DATA_DO_EMPENHO",
    "COMPETENCIA_LABEL",
    "OBSERVACAO",
    "ESPELHO_DIANA_MD",
    "ESPELHO_MD",
    "PDF_MD",
]

# -----------------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------------

def _fetch_excel_bytes(url: str) -> BytesIO:
    """Baixa a planilha (XLSX) e retorna como BytesIO. Levanta Exception se falhar."""
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Falha ao baixar planilha (HTTP {r.status_code}). Verifique se o link está público.")
    return BytesIO(r.content)

def _safe_str(x) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    return s

def _is_url(x: str) -> bool:
    x = _safe_str(x).lower()
    return x.startswith("http://") or x.startswith("https://")

def _to_brl(v) -> str:
    try:
        if pd.isna(v):
            return "R$ 0,00"
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nomes de colunas para canônicos e cria campos derivados."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(set(COL_ALIASES.values())))

    # Renomeia
    rename_map = {}
    for c in df.columns:
        key = _safe_str(c).lower()
        if key in COL_ALIASES:
            rename_map[c] = COL_ALIASES[key]

    df = df.rename(columns=rename_map).copy()

    # Garante todas as colunas esperadas
    for col in set(COL_ALIASES.values()):
        if col not in df.columns:
            df[col] = np.nan

    # Tipos
    # Valor
    df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce")

    # Datas
    if "DATA_DO_EMPENHO" in df.columns:
        df["DATA_DO_EMPENHO"] = pd.to_datetime(df["DATA_DO_EMPENHO"], errors="coerce", dayfirst=True)

    # Competência: usa COMPETENCIA_DT se existir, senão tenta parse de COMPETENCIA_TXT, senão DATA_DO_EMPENHO
    comp_dt = pd.to_datetime(df.get("COMPETENCIA_DT"), errors="coerce", dayfirst=True)

    if comp_dt.isna().all():
        comp_txt = df.get("COMPETENCIA_TXT")
        if comp_txt is not None:
            comp_dt = pd.to_datetime(comp_txt, errors="coerce", dayfirst=True)
        else:
            comp_dt = pd.to_datetime(df.get("DATA_DO_EMPENHO"), errors="coerce", dayfirst=True)

    # normaliza pro primeiro dia do mês
    comp_dt = comp_dt.dt.to_period("M").dt.to_timestamp()
    df["COMPETENCIA_DT"] = comp_dt
    # rótulo (MMM/YYYY)
    df["COMPETENCIA_LABEL"] = df["COMPETENCIA_DT"].dt.strftime("%m/%Y")

    # Strings base para filtros
    df["CAMPANHA"] = df["CAMPANHA"].apply(_safe_str)
    df["SECRETARIA"] = df["SECRETARIA"].apply(_safe_str)
    df["AGENCIA"] = df["AGENCIA"].apply(_safe_str)
    df["OBSERVACAO"] = df["OBSERVACAO"].apply(_safe_str)

    # Links → colunas markdown
    for col, text in [
        ("PROCESSO", "Processo"),
        ("EMPENHO", "Empenho"),
        ("ESPELHO_DIANA", "Diana"),
        ("ESPELHO", "Espelho"),
        ("PDF", "PDF"),
    ]:
        md_col = f"{col}_MD"
        urls = df[col].apply(_safe_str)
        df[md_col] = urls.apply(lambda u: f"[{text}]({u})" if _is_url(u) else "")

    # Valor formatado
    df["VALOR_FMT"] = df["VALOR"].apply(_to_brl)

    # Remove linhas totalmente vazias (sem valor e sem texto em chaves principais)
    base_cols = ["CAMPANHA", "SECRETARIA", "AGENCIA", "VALOR", "DATA_DO_EMPENHO", "COMPETENCIA_DT"]
    df = df.dropna(how="all", subset=base_cols)

    # Ordenação consistente
    df = df.reset_index(drop=True)
    return df

def _load_sheet_from_url(url: str, sheet_name: Optional[str]) -> Tuple[pd.DataFrame, List[str]]:
    """
    Carrega um sheet específico da planilha (por nome).
    Se sheet_name for None, usa o primeiro.
    Retorna (df_normalizado, lista_de_abas).
    """
    bio = _fetch_excel_bytes(url)
    xl = pd.ExcelFile(bio)
    sheet_names = xl.sheet_names or []
    if not sheet_names:
        return pd.DataFrame(columns=list(set(COL_ALIASES.values()))), []

    chosen = sheet_name if sheet_name in sheet_names else sheet_names[0]
    raw = xl.parse(chosen)
    df = _normalize_columns(raw)
    return df, sheet_names

def _opt_list(series: pd.Series) -> List[Dict[str, str]]:
    """Gera options seguros p/ Dropdown (evita erro de comparar int com str)."""
    vals = sorted({ _safe_str(x) for x in series.dropna() if _safe_str(x) })
    return [{"label": v, "value": v} for v in vals]

def _apply_filters(
    df: pd.DataFrame,
    secretaria_sel: List[str],
    agencia_sel: List[str],
    campanha_sel: List[str],
    date_ini: Optional[str],
    date_fim: Optional[str],
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()

    if secretaria_sel:
        out = out[out["SECRETARIA"].isin(secretaria_sel)]
    if agencia_sel:
        out = out[out["AGENCIA"].isin(agencia_sel)]
    if campanha_sel:
        out = out[out["CAMPANHA"].isin(campanha_sel)]

    if date_ini:
        try:
            di = pd.to_datetime(date_ini)
            out = out[(out["DATA_DO_EMPENHO"].isna()) | (out["DATA_DO_EMPENHO"] >= di)]
        except Exception:
            pass
    if date_fim:
        try:
            dfim = pd.to_datetime(date_fim)
            out = out[(out["DATA_DO_EMPENHO"].isna()) | (out["DATA_DO_EMPENHO"] <= dfim)]
        except Exception:
            pass

    return out

def _fig_template(theme: str) -> str:
    return "plotly_white" if theme == "light" else "plotly_dark"

# -----------------------------------------------------------------------------
# APP
# -----------------------------------------------------------------------------

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server  # para o gunicorn

# Layout
app.layout = html.Div(
    id="theme-wrapper",
    className="theme-light",  # padrão claro
    children=[
        # Stores
        dcc.Store(id="store-theme", data=DEFAULT_THEME if DEFAULT_THEME in ("light", "dark") else "light"),
        dcc.Store(id="store-df"),          # df atual (sheet + filtros aplicados na callback de gráficos/tabela)
        dcc.Store(id="store-raw-df"),      # df bruto do sheet selecionado (sem filtros)
        dcc.Store(id="store-sheets"),      # lista de abas
        dcc.Store(id="store-error"),       # mensagem de erro

        dcc.Interval(id="init-load", interval=100, n_intervals=0, max_intervals=1),  # carrega ao iniciar

        # Cabeçalho / barra de controle
        html.Div(
            className="topbar",
            children=[
                html.Div(
                    className="brand",
                    children=[
                        html.H2("SECOM — Painel de Processos", className="app-title"),
                        html.Div(id="error-banner", className="error-banner", style={"display": "none"}),
                    ],
                ),
                html.Div(
                    className="controls",
                    children=[
                        # Tema
                        html.Div(
                            className="control",
                            children=[
                                html.Label("Tema"),
                                dcc.RadioItems(
                                    id="radio-theme",
                                    options=[
                                        {"label": "Claro", "value": "light"},
                                        {"label": "Escuro", "value": "dark"},
                                    ],
                                    value="light",  # padrão
                                    inline=True,
                                ),
                            ],
                        ),
                        # Atualizar
                        html.Div(
                            className="control",
                            children=[
                                html.Label(""),
                                html.Button("Atualizar dados", id="btn-refresh", n_clicks=0, className="btn"),
                            ],
                        ),
                        # Download
                        html.Div(
                            className="control",
                            children=[
                                html.Label(""),
                                html.Button("Baixar (Excel)", id="btn-download", n_clicks=0, className="btn"),
                                dcc.Download(id="download-xlsx"),
                            ],
                        ),
                    ],
                ),
            ],
        ),

        # Linha de filtros
        html.Div(
            className="filters",
            children=[
                html.Div(
                    className="filter",
                    children=[
                        html.Label("Aba (planilha)"),
                        dcc.Dropdown(id="dd-sheet", options=[], value=None, placeholder="Selecione a aba…", clearable=False),
                    ],
                ),
                html.Div(
                    className="filter",
                    children=[
                        html.Label("Secretaria"),
                        dcc.Dropdown(id="dd-secretaria", options=[], multi=True, placeholder="(todas)"),
                    ],
                ),
                html.Div(
                    className="filter",
                    children=[
                        html.Label("Agência"),
                        dcc.Dropdown(id="dd-agencia", options=[], multi=True, placeholder="(todas)"),
                    ],
                ),
                html.Div(
                    className="filter",
                    children=[
                        html.Label("Campanha"),
                        dcc.Dropdown(id="dd-campanha", options=[], multi=True, placeholder="(todas)"),
                    ],
                ),
                html.Div(
                    className="filter",
                    children=[
                        html.Label("Data do Empenho"),
                        dcc.DatePickerRange(
                            id="date-range",
                            start_date=None,
                            end_date=None,
                            display_format="DD/MM/YYYY",
                            minimum_nights=0,
                            clearable=True,
                        ),
                    ],
                ),
            ],
        ),

        # Cards de totais
        html.Div(
            className="cards",
            children=[
                html.Div(className="card", children=[html.Div("Total (filtrado)"), html.H3(id="card-total")]),
                html.Div(className="card", children=[html.Div("Secretarias"), html.H3(id="card-qtd-secretarias")]),
                html.Div(className="card", children=[html.Div("Agências"), html.H3(id="card-qtd-agencias")]),
                html.Div(className="card", children=[html.Div("Registros"), html.H3(id="card-qtd-registros")]),
            ],
        ),

        # Gráficos
        html.Div(
            className="grid",
            children=[
                html.Div(className="graph-card", children=[dcc.Graph(id="g-evolucao", style={"height": GRAPH_HEIGHT, "width": "100%"})]),
                html.Div(className="graph-card", children=[dcc.Graph(id="g-top-secretaria", style={"height": GRAPH_HEIGHT, "width": "100%"})]),
                html.Div(className="graph-card", children=[dcc.Graph(id="g-top-agencia", style={"height": GRAPH_HEIGHT, "width": "100%"})]),
                html.Div(className="graph-card", children=[dcc.Graph(id="g-treemap", style={"height": GRAPH_HEIGHT, "width": "100%"})]),
                html.Div(className="graph-card", children=[dcc.Graph(id="g-campanhas", style={"height": GRAPH_HEIGHT, "width": "100%"})]),
            ],
        ),

        # Tabela
        html.Div(
            className="table-wrap",
            children=[
                dash_table.DataTable(
                    id="tbl",
                    data=[],
                    columns=[
                        {"name": "CAMPANHA", "id": "CAMPANHA"},
                        {"name": "SECRETARIA", "id": "SECRETARIA"},
                        {"name": "AGÊNCIA", "id": "AGENCIA"},
                        {"name": "VALOR DO ESPELHO", "id": "VALOR_FMT"},
                        {"name": "PROCESSO", "id": "PROCESSO_MD", "presentation": "markdown"},
                        {"name": "EMPENHO", "id": "EMPENHO_MD", "presentation": "markdown"},
                        {"name": "DATA DO EMPENHO", "id": "DATA_DO_EMPENHO"},
                        {"name": "COMPETÊNCIA", "id": "COMPETENCIA_LABEL"},
                        {"name": "OBSERVAÇÃO", "id": "OBSERVACAO"},
                        {"name": "ESPELHO DIANA", "id": "ESPELHO_DIANA_MD", "presentation": "markdown"},
                        {"name": "ESPELHO", "id": "ESPELHO_MD", "presentation": "markdown"},
                        {"name": "PDF", "id": "PDF_MD", "presentation": "markdown"},
                    ],
                    page_size=12,
                    sort_action="native",
                    filter_action="native",
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
                        "fontSize": "14px",
                        "padding": "8px",
                        "whiteSpace": "nowrap",
                        "textOverflow": "ellipsis",
                        "maxWidth": 320,
                    },
                    style_header={"fontWeight": "600"},
                    markdown_options={"link_target": "_blank"},
                    export_format="xlsx",
                )
            ],
        ),
    ],
)

# -----------------------------------------------------------------------------
# CALLBACKS
# -----------------------------------------------------------------------------

@app.callback(
    Output("store-raw-df", "data"),
    Output("store-sheets", "data"),
    Output("dd-sheet", "options"),
    Output("dd-sheet", "value"),
    Output("dd-secretaria", "options"),
    Output("dd-agencia", "options"),
    Output("dd-campanha", "options"),
    Output("date-range", "start_date"),
    Output("date-range", "end_date"),
    Output("store-error", "data"),
    Input("init-load", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
    Input("dd-sheet", "value"),
    State("store-sheets", "data"),
    prevent_initial_call=False,
)
def load_data(_init, n_clicks, sheet_value, sheets_cache):
    """
    Carrega/recarega dados da nuvem.
    - Ao iniciar (interval 1x) carrega planilha e define sheet default.
    - Ao clicar em Atualizar, recarrega usando sheet selecionado (se houver).
    - Ao trocar o sheet, recarrega esse sheet.
    """
    trigger = ctx.triggered_id
    url = DEFAULT_EXCEL_URL

    try:
        # Decide qual sheet carregar: se valor atual existe, tenta ele, senão primeiro
        df, all_sheets = _load_sheet_from_url(url, sheet_value)

        # options dos filtros
        opt_sec = _opt_list(df["SECRETARIA"])
        opt_age = _opt_list(df["AGENCIA"])
        opt_cam = _opt_list(df["CAMPANHA"])

        # datas
        min_dt = df["DATA_DO_EMPENHO"].min()
        max_dt = df["DATA_DO_EMPENHO"].max()
        start_date = min_dt.date().isoformat() if pd.notna(min_dt) else None
        end_date = max_dt.date().isoformat() if pd.notna(max_dt) else None

        # valor inicial do dd-sheet
        dd_opts = [{"label": s, "value": s} for s in all_sheets]
        dd_val = sheet_value if (sheet_value in all_sheets) else (all_sheets[0] if all_sheets else None)

        # devolve df bruto serializado
        raw_records = df.to_dict("records")

        return (
            raw_records,
            all_sheets,
            dd_opts,
            dd_val,
            opt_sec, opt_age, opt_cam,
            start_date, end_date,
            "",
        )

    except Exception as e:
        err = f"Erro ao carregar planilha: {e}"
        # Retorna estruturas vazias para não quebrar a tela
        return (
            [],
            [],
            [],
            None,
            [],
            [],
            [],
            None,
            None,
            err,
        )

@app.callback(
    Output("theme-wrapper", "className"),
    Output("store-theme", "data"),
    Input("radio-theme", "value"),
    prevent_initial_call=False,
)
def set_theme(theme_val):
    theme = theme_val if theme_val in ("light", "dark") else "light"
    return (f"theme-{theme}", theme)

@app.callback(
    Output("error-banner", "children"),
    Output("error-banner", "style"),
    Input("store-error", "data"),
)
def show_error(err_text):
    if err_text:
        return (err_text, {"display": "block"})
    return ("", {"display": "none"})

@app.callback(
    Output("store-df", "data"),
    Output("card-total", "children"),
    Output("card-qtd-secretarias", "children"),
    Output("card-qtd-agencias", "children"),
    Output("card-qtd-registros", "children"),
    Output("g-evolucao", "figure"),
    Output("g-top-secretaria", "figure"),
    Output("g-top-agencia", "figure"),
    Output("g-treemap", "figure"),
    Output("g-campanhas", "figure"),
    Output("tbl", "data"),
    Input("store-raw-df", "data"),
    Input("dd-secretaria", "value"),
    Input("dd-agencia", "value"),
    Input("dd-campanha", "value"),
    Input("date-range", "start_date"),
    Input("date-range", "end_date"),
    Input("store-theme", "data"),
)
def update_all(raw_records, sec_sel, ag_sel, cam_sel, d_ini, d_fim, theme):
    template = _fig_template(theme)
    df = pd.DataFrame(raw_records or [])

    if df.empty:
        empty_fig = go.Figure()
        empty_fig.update_layout(template=template, title="Sem dados")
        return (
            [], "R$ 0,00", "0", "0", "0",
            empty_fig, empty_fig, empty_fig, empty_fig, empty_fig,
            [],
        )

    # aplica filtros
    sec_sel = sec_sel or []
    ag_sel = ag_sel or []
    cam_sel = cam_sel or []

    dff = _apply_filters(df, sec_sel, ag_sel, cam_sel, d_ini, d_fim)

    # totalizadores
    total = dff["VALOR"].sum(skipna=True)
    total_fmt = _to_brl(total)
    n_sec = dff["SECRETARIA"].nunique()
    n_age = dff["AGENCIA"].nunique()
    n_reg = len(dff)

    # ----------------- Gráfico: Evolução mensal -----------------
    evol = (
        dff.dropna(subset=["COMPETENCIA_DT"])
           .groupby("COMPETENCIA_DT", as_index=False)
           .agg(VALOR=("VALOR", "sum"))
           .sort_values("COMPETENCIA_DT")
    )
    if evol.empty:
        fig_evol = go.Figure()
    else:
        fig_evol = px.area(
            evol, x="COMPETENCIA_DT", y="VALOR",
            title="Evolução mensal — soma do VALOR DO ESPELHO",
            labels={"COMPETENCIA_DT": "Competência (mês)", "VALOR": "Valor"},
            template=template,
        )
        fig_evol.update_traces(mode="lines+markers")
        fig_evol.update_layout(yaxis_tickformat=",", hovermode="x unified")

    # ----------------- Top 10 Secretarias -----------------
    top_sec = (
        dff.groupby("SECRETARIA", as_index=False)
           .agg(VALOR=("VALOR", "sum"))
           .sort_values("VALOR", ascending=False)
           .head(10)
    )
    if top_sec.empty:
        fig_sec = go.Figure()
    else:
        fig_sec = px.bar(
            top_sec, x="VALOR", y="SECRETARIA",
            orientation="h",
            title="Top 10 Secretarias por valor",
            labels={"VALOR": "Valor", "SECRETARIA": "Secretaria"},
            template=template,
        )
        fig_sec.update_layout(yaxis={"categoryorder": "total ascending"})

    # ----------------- Top 10 Agências -----------------
    top_age = (
        dff.groupby("AGENCIA", as_index=False)
           .agg(VALOR=("VALOR", "sum"))
           .sort_values("VALOR", ascending=False)
           .head(10)
    )
    if top_age.empty:
        fig_age = go.Figure()
    else:
        fig_age = px.bar(
            top_age, x="VALOR", y="AGENCIA",
            orientation="h",
            title="Top 10 Agências por valor",
            labels={"VALOR": "Valor", "AGENCIA": "Agência"},
            template=template,
        )
        fig_age.update_layout(yaxis={"categoryorder": "total ascending"})

    # ----------------- Treemap (Secretaria → Agência) -----------------
    treemap_df = (
        dff.groupby(["SECRETARIA", "AGENCIA"], as_index=False)
           .agg(VALOR=("VALOR", "sum"))
    )
    if treemap_df.empty:
        fig_tree = go.Figure()
    else:
        fig_tree = px.treemap(
            treemap_df,
            path=["SECRETARIA", "AGENCIA"],
            values="VALOR",
            title="Proporção por Secretaria → Agência",
            template=template,
        )

    # ----------------- Campanhas por valor (Top N) -----------------
    camp = (
        dff.groupby("CAMPANHA", as_index=False)
           .agg(VALOR=("VALOR", "sum"))
           .sort_values("VALOR", ascending=False)
           .head(15)
    )
    if camp.empty:
        fig_camp = go.Figure()
    else:
        fig_camp = px.bar(
            camp, x="VALOR", y="CAMPANHA",
            orientation="h",
            title="Campanhas por valor (Top 15)",
            labels={"VALOR": "Valor", "CAMPANHA": "Campanha"},
            template=template,
        )
        fig_camp.update_layout(yaxis={"categoryorder": "total ascending"})

    # Alturas estáveis (evita “crescimento infinito”)
    for f in (fig_evol, fig_sec, fig_age, fig_tree, fig_camp):
        f.update_layout(height=GRAPH_HEIGHT)

    # ----------------- Tabela detalhada -----------------
    table_df = dff.copy()
    # Ordena por valor (desc) e, em seguida, por data
    table_df = table_df.sort_values(["VALOR", "DATA_DO_EMPENHO"], ascending=[False, True])
    # Formata DATA
    if "DATA_DO_EMPENHO" in table_df.columns:
        table_df["DATA_DO_EMPENHO"] = table_df["DATA_DO_EMPENHO"].dt.strftime("%d/%m/%Y")

    tbl_records = table_df[DISPLAY_COLUMNS].fillna("").to_dict("records")

    return (
        dff.to_dict("records"),
        total_fmt,
        str(n_sec),
        str(n_age),
        str(n_reg),
        fig_evol, fig_sec, fig_age, fig_tree, fig_camp,
        tbl_records,
    )

@app.callback(
    Output("download-xlsx", "data"),
    Input("btn-download", "n_clicks"),
    State("store-df", "data"),
    prevent_initial_call=True,
)
def download_filtered(n_clicks, dff_records):
    if not n_clicks:
        return no_update
    df = pd.DataFrame(dff_records or [])
    if df.empty:
        # mesmo assim gera um arquivo com header
        df = pd.DataFrame(columns=["CAMPANHA","SECRETARIA","AGENCIA","VALOR","DATA_DO_EMPENHO","COMPETENCIA_DT","OBSERVACAO","PROCESSO","EMPENHO","ESPELHO_DIANA","ESPELHO","PDF"])
    # Exporta para Excel em memória
    def _to_xlsx_bytes(dfexp: pd.DataFrame) -> bytes:
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            dfexp.to_excel(writer, index=False, sheet_name="filtrado")
        bio.seek(0)
        return bio.read()

    data = _to_xlsx_bytes(df)
    fname = f"secom_filtrado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return dcc.send_bytes(data, filename=fname)

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Execução local
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
