# -*- coding: utf-8 -*-
"""
SECOM • Dashboard (Dash)
- Lê planilha via EXCEL_URL (Google Sheets/Drive, Dropbox, OneDrive) ou arquivo local.
- Apenas temas Claro/Escuro.
- Filtros: Secretaria, Agência, Campanha, Competência, Período (Data do Empenho), Busca.
- Totalizadores: Registros, Valor total, Nº Secretarias, Nº Agências.
- Gráfico de barras por Secretaria.
- Tabela detalhada com links (markdown) e export.
"""

import os
import io
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from dash import Dash, html, dcc, dash_table, Input, Output
import plotly.graph_objects as go

# ===================== Config =====================
EXCEL_PATH = os.environ.get("EXCEL_PATH", os.path.join("data", "CONTROLE DE PROCESSOS SECOM.xlsx"))
EXCEL_URL = os.environ.get("EXCEL_URL", "").strip()
EXCEL_BEARER_TOKEN = os.environ.get("EXCEL_BEARER_TOKEN", "").strip()
EXCEL_HTTP_USERNAME = os.environ.get("EXCEL_HTTP_USERNAME", "").strip()
EXCEL_HTTP_PASSWORD = os.environ.get("EXCEL_HTTP_PASSWORD", "").strip()

SHEET_NAME = os.environ.get("SHEET_NAME", None)  # se não definido, lê todas as abas
MISSING_DATA_WARNING = ""

# ===================== Tema (apenas Claro/Escuro) =====================
THEME = {
    "light": {"template": "plotly_white", "font": "#0F172A", "grid": "#E9EDF5"},
    "dark":  {"template": "plotly_dark",  "font": "#E6ECFF", "grid": "#22304A"},
}

def set_theme(theme: str) -> str:
    return theme if theme in {"light", "dark"} else "light"

def style_fig(fig, theme="light"):
    t = THEME.get(set_theme(theme), THEME["light"])
    fig.update_layout(
        template=t["template"],
        font=dict(color=t["font"], size=13),
        margin=dict(l=12, r=12, t=48, b=12),
    )
    fig.update_xaxes(gridcolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"])
    return fig

# ===================== Helpers de Data =====================
def _try_parse_date(s: pd.Series) -> pd.Series:
    # tenta %d/%m/%Y; se falhar, usa parsing com dayfirst
    a = pd.to_datetime(s, errors="coerce", format="%d/%m/%Y")
    b = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return a.fillna(b)

def _fmt_currency(v) -> str:
    try:
        x = float(v)
    except Exception:
        return "R$ 0,00"
    return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _resolve_excel_path() -> Optional[str]:
    # tenta EXCEL_PATH; se não existir, tenta achar .xlsx em ./data
    if EXCEL_PATH and os.path.exists(EXCEL_PATH):
        return EXCEL_PATH
    data_dir = "data"
    if os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            if fn.lower().endswith(".xlsx"):
                return os.path.join(data_dir, fn)
    return None

def _date_bounds(df: pd.DataFrame, col: str) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    if col not in df.columns or df[col].dtype.kind != "M":
        return None, None
    return df[col].min(), df[col].max()

# --- Helpers: opções para dropdown ---
def _options_for(df: pd.DataFrame, col: str):
    """Retorna options para dcc.Dropdown no formato [{'label','value'}]."""
    try:
        if col not in df.columns:
            return []
        ser = df[col].dropna()
        # normaliza p/ string, remove espaços e vazios
        ser = ser.astype(str).str.strip()
        ser = ser[ser != ""]
        valores = sorted(ser.unique().tolist())
        return [{"label": v, "value": v} for v in valores]
    except Exception:
        return []

# ===================== Download de planilha (URL) =====================
def _normalize_excel_url(url: str) -> str:
    """Normaliza links populares para download direto (Sheets/Drive/Dropbox/OneDrive)."""
    u = (url or "").strip()
    if not u:
        return u

    # Dropbox: força dl=1
    if "dropbox.com" in u:
        if "dl=0" in u:
            u = u.replace("dl=0", "dl=1")
        elif "dl=1" not in u and "raw=1" not in u:
            sep = "&" if "?" in u else "?"
            u = f"{u}{sep}dl=1"

    # Google Drive/Sheets → export xlsx (respeita gid quando houver)
    if "drive.google.com" in u or "docs.google.com" in u:
        import re as _re
        m = _re.search(r"/d/([a-zA-Z0-9_-]{20,})", u) or _re.search(r"[?&]id=([a-zA-Z0-9_-]{20,})", u)
        gid = None
        mg = _re.search(r"[?&#]gid=(\d+)", u)
        if mg:
            gid = mg.group(1)
        if m:
            fid = m.group(1)
            u = f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx&id={fid}"
            if gid:
                u = f"{u}&gid={gid}"

    # OneDrive/SharePoint: adiciona download=1
    if "onedrive.live.com" in u or "sharepoint.com" in u:
        sep = "&" if "?" in u else "?"
        u = f"{u}{sep}download=1"

    return u

def _download_excel_bytes(url: str) -> io.BytesIO:
    import requests
    u = _normalize_excel_url(url)
    headers = {"User-Agent": "SECOM-Dashboard/1.0", "Accept": "*/*"}
    auth = None
    if EXCEL_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {EXCEL_BEARER_TOKEN}"
    elif EXCEL_HTTP_USERNAME and EXCEL_HTTP_PASSWORD:
        auth = (EXCEL_HTTP_USERNAME, EXCEL_HTTP_PASSWORD)
    r = requests.get(u, headers=headers, auth=auth, timeout=45)
    r.raise_for_status()
    return io.BytesIO(r.content)

# ===================== Leitura & Normalização =====================
BASE_COLUMNS = [
    "CAMPANHA","SECRETARIA","AGÊNCIA",
    "ESPELHO DIANA","ESPELHO","PDF",
    "VALOR DO ESPELHO","PROCESSO","EMPENHO",
    "DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO"
]

def _coerce_and_rename(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip() for c in d.columns]

    # Possíveis variações -> padrão
    rename_map = {
        "VALOR": "VALOR DO ESPELHO",
        "VALOR_ESPELHO": "VALOR DO ESPELHO",
        "VALOR DO ESPELHO (R$)": "VALOR DO ESPELHO",
        "DATA EMPENHO": "DATA DO EMPENHO",
        "DATA_DO_EMPENHO": "DATA DO EMPENHO",
        "OBS": "OBSERVAÇÃO",
        "SECRETÁRIA": "SECRETARIA",
        "AGENCIA": "AGÊNCIA",
    }
    for k, v in rename_map.items():
        if k in d.columns and v not in d.columns:
            d = d.rename(columns={k: v})

    for col in BASE_COLUMNS:
        if col not in d.columns:
            d[col] = np.nan

    # Tipos
    d["VALOR DO ESPELHO"] = pd.to_numeric(d["VALOR DO ESPELHO"], errors="coerce").fillna(0.0)
    d["DATA DO EMPENHO"] = _try_parse_date(d["DATA DO EMPENHO"])

    # Competência auxiliar (mês/ano)
    comp = d["COMPETÊNCIA"].astype(str).str.strip()
    comp_dt = pd.to_datetime(comp, errors="coerce", format="%m/%Y")
    comp_dt2 = pd.to_datetime(comp, errors="coerce", dayfirst=True)
    d["COMPETÊNCIA_DT"] = comp_dt.fillna(comp_dt2)
    d["COMPETÊNCIA_TXT"] = comp.where(d["COMPETÊNCIA_DT"].isna(), d["COMPETÊNCIA_DT"].dt.to_period("M").astype(str))

    # Links como string
    for c in ["ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"]:
        d[c] = d[c].astype(str)

    # Remove linhas totalmente vazias (chaves)
    d = d[~(d["SECRETARIA"].isna() & d["AGÊNCIA"].isna() & d["CAMPANHA"].isna() & d["PROCESSO"].isna())].copy()

    return d[BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"]]

def _read_all_sheets(xl: pd.ExcelFile) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    if SHEET_NAME:
        try:
            frames.append(_coerce_and_rename(pd.read_excel(xl, sheet_name=SHEET_NAME)))
        except Exception:
            pass
    else:
        for s in xl.sheet_names:
            try:
                df = pd.read_excel(xl, sheet_name=s)
                frames.append(_coerce_and_rename(df))
            except Exception:
                continue
    if frames:
        out = pd.concat(frames, ignore_index=True, sort=False)
        return out
    return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])

def _load_from_excel_bytes(buf: io.BytesIO) -> pd.DataFrame:
    global MISSING_DATA_WARNING
    try:
        xl = pd.ExcelFile(buf)
    except Exception as e:
        MISSING_DATA_WARNING = f"Não foi possível abrir a planilha da URL: {e}"
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])
    return _read_all_sheets(xl)

def _load_local(path: str) -> pd.DataFrame:
    try:
        xl = pd.ExcelFile(path)
        return _read_all_sheets(xl)
    except Exception:
        # fallback: leitura direta
        return pd.read_excel(path, sheet_name=SHEET_NAME)

def _load_data() -> pd.DataFrame:
    global MISSING_DATA_WARNING
    # 1) Preferir URL
    if EXCEL_URL:
        try:
            buf = _download_excel_bytes(EXCEL_URL)
            dfurl = _load_from_excel_bytes(buf)
            if not dfurl.empty:
                return dfurl.fillna("")
            else:
                MISSING_DATA_WARNING = MISSING_DATA_WARNING or "Planilha remota vazia ou não reconhecida."
        except Exception as e:
            MISSING_DATA_WARNING = f"Falha ao baixar a planilha da URL: {e}"
            # continua para tentar local

    # 2) Fallback local
    path = _resolve_excel_path()
    if not path:
        MISSING_DATA_WARNING = MISSING_DATA_WARNING or "Nenhuma planilha .xlsx encontrada localmente e EXCEL_URL não disponível."
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])

    try:
        df = _load_local(path)
    except Exception as e:
        MISSING_DATA_WARNING = f"Falha ao abrir a planilha local: {e}"
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])

    return df.fillna("")

# Carrega base inicial
DF_BASE = _load_data()

# ===================== App =====================
app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

# ===================== Layout =====================
app.layout = html.Div(
    [
        html.Div(
            [
                html.H1("SECOM • Controle de Processos", className="title"),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Tema"),
                                dcc.RadioItems(
                                    id="theme",
                                    options=[
                                        {"label": "Claro", "value": "light"},
                                        {"label": "Escuro", "value": "dark"},
                                    ],
                                    value="light",
                                    inline=True,
                                ),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Secretaria"),
                                dcc.Dropdown(id="f_secretaria", options=_options_for(DF_BASE, "SECRETARIA"), multi=True, placeholder="Todas"),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Agência"),
                                dcc.Dropdown(id="f_agencia", options=_options_for(DF_BASE, "AGÊNCIA"), multi=True, placeholder="Todas"),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Campanha"),
                                dcc.Dropdown(id="f_campanha", options=_options_for(DF_BASE, "CAMPANHA"), multi=True, placeholder="Todas"),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Competência (mês)"),
                                dcc.Dropdown(id="f_comp", options=_options_for(DF_BASE, "COMPETÊNCIA_TXT"), multi=True, placeholder="Todas"),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Período (Data do Empenho)"),
                                dcc.DatePickerRange(
                                    id="f_periodo",
                                    start_date=_date_bounds(DF_BASE, "DATA DO EMPENHO")[0],
                                    end_date=_date_bounds(DF_BASE, "DATA DO EMPENHO")[1],
                                    min_date_allowed=_date_bounds(DF_BASE, "DATA DO EMPENHO")[0],
                                    max_date_allowed=_date_bounds(DF_BASE, "DATA DO EMPENHO")[1],
                                    display_format="DD/MM/YYYY",
                                ),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Label("Busca (processo / observação)"),
                                dcc.Input(id="f_busca", type="text", placeholder="Digite um termo", debounce=True, style={"width":"100%"}),
                            ],
                            className="box",
                        ),
                        html.Div(
                            [
                                html.Button("Atualizar dados (↻)", id="btn_reload", n_clicks=0, className="btn"),
                            ],
                            className="box",
                        ),
                        html.Div(MISSING_DATA_WARNING, id="warn", className="warn"),
                    ],
                    className="sidebar",
                ),

                html.Div(
                    [
                        html.Div(
                            [
                                html.Div([html.Div("Registros", className="kpi-label"), html.Div(id="kpi_total", className="kpi-value")], className="kpi"),
                                html.Div([html.Div("Valor total", className="kpi-label"), html.Div(id="kpi_valor", className="kpi-value")], className="kpi"),
                                html.Div([html.Div("Secretarias", className="kpi-label"), html.Div(id="kpi_secr", className="kpi-value")], className="kpi"),
                                html.Div([html.Div("Agências", className="kpi-label"), html.Div(id="kpi_ag", className="kpi-value")], className="kpi"),
                            ],
                            className="kpis",
                        ),
                        html.Div(
                            [
                                dcc.Graph(id="fig_bar_secretaria"),
                            ],
                            className="card",
                        ),
                        html.Div(
                            [
                                dash_table.DataTable(
                                    id="tbl",
                                    page_size=15,
                                    sort_action="native",
                                    filter_action="native",
                                    fixed_rows={"headers": True},
                                    style_table={"height": "520px", "overflowY": "auto"},
                                    style_cell={"minWidth": 100, "whiteSpace": "normal", "height": "auto"},
                                    export_format="xlsx",
                                    export_headers="display",
                                    markdown_options={"link_target": "_blank"},
                                )
                            ],
                            className="card",
                        ),
                    ],
                    className="content",
                ),
            ],
            className="container",
        ),
        dcc.Store(id="store_df", data=DF_BASE.to_json(date_format="iso", orient="split")),
    ]
)

# ===================== Filtro base =====================
def _filtrar(df: pd.DataFrame,
             secre: Optional[List[str]],
             ag: Optional[List[str]],
             camp: Optional[List[str]],
             comp: Optional[List[str]],
             ini: Optional[str],
             fim: Optional[str],
             termo: Optional[str]) -> pd.DataFrame:

    if df is None or df.empty:
        return df

    dff = df.copy()

    if secre:
        dff = dff[dff["SECRETARIA"].astype(str).isin(secre)]
    if ag:
        dff = dff[dff["AGÊNCIA"].astype(str).isin(ag)]
    if camp:
        dff = dff[dff["CAMPANHA"].astype(str).isin(camp)]
    if comp:
        dff = dff[dff["COMPETÊNCIA_TXT"].astype(str).isin(comp)]
    if ini and fim and "DATA DO EMPENHO" in dff.columns and dff["DATA DO EMPENHO"].dtype.kind == "M":
        ini_dt = pd.to_datetime(ini)
        fim_dt = pd.to_datetime(fim)
        dff = dff[(dff["DATA DO EMPENHO"] >= ini_dt) & (dff["DATA DO EMPENHO"] <= fim_dt)]

    if termo:
        t = str(termo).strip().lower()
        if t:
            mask = pd.Series(False, index=dff.index)
            for c in ["PROCESSO","OBSERVAÇÃO","CAMPANHA","SECRETARIA","AGÊNCIA","EMPENHO"]:
                if c in dff.columns:
                    mask = mask | dff[c].astype(str).str.lower().str.contains(t, na=False)
            dff = dff[mask]

    return dff

# ===================== Callbacks =====================
@app.callback(
    Output("store_df", "data"),
    Output("warn", "children"),
    Input("btn_reload", "n_clicks"),
    prevent_initial_call=True,
)
def reload_base(n_clicks):
    """Recarrega a base (usa EXCEL_URL se disponível) e guarda no Store."""
    global DF_BASE, MISSING_DATA_WARNING
    DF_BASE = _load_data()
    return DF_BASE.to_json(date_format="iso", orient="split"), MISSING_DATA_WARNING

@app.callback(
    Output("f_secretaria", "options"),
    Output("f_agencia", "options"),
    Output("f_campanha", "options"),
    Output("f_comp", "options"),
    Output("f_periodo", "start_date"),
    Output("f_periodo", "end_date"),
    Output("f_periodo", "min_date_allowed"),
    Output("f_periodo", "max_date_allowed"),
    Input("store_df", "data"),
)
def refresh_filter_options(store_json):
    df = DF_BASE if not store_json else pd.read_json(store_json, orient="split")
    s_opts = _options_for(df, "SECRETARIA")
    a_opts = _options_for(df, "AGÊNCIA")
    c_opts = _options_for(df, "CAMPANHA")
    m_opts = _options_for(df, "COMPETÊNCIA_TXT")
    mind, maxd = _date_bounds(df, "DATA DO EMPENHO")
    return s_opts, a_opts, c_opts, m_opts, mind, maxd, mind, maxd

@app.callback(
    Output("kpi_total", "children"),
    Output("kpi_valor", "children"),
    Output("kpi_secr", "children"),
    Output("kpi_ag", "children"),
    Output("fig_bar_secretaria", "figure"),
    Output("tbl", "columns"),
    Output("tbl", "data"),
    Input("store_df", "data"),
    Input("f_secretaria", "value"),
    Input("f_agencia", "value"),
    Input("f_campanha", "value"),
    Input("f_comp", "value"),
    Input("f_periodo", "start_date"),
    Input("f_periodo", "end_date"),
    Input("f_busca", "value"),
    Input("theme", "value"),
)
def atualizar(store_json, secre, ag, camp, comp, ini, fim, termo, theme):
    df = DF_BASE if not store_json else pd.read_json(store_json, orient="split")
    dff = _filtrar(df, secre, ag, camp, comp, ini, fim, termo)

    # KPIs
    total = len(dff)
    soma = _fmt_currency(dff["VALOR DO ESPELHO"].sum() if "VALOR DO ESPELHO" in dff.columns else 0.0)
    nsecr = dff["SECRETARIA"].nunique() if "SECRETARIA" in dff.columns else 0
    nag = dff["AGÊNCIA"].nunique() if "AGÊNCIA" in dff.columns else 0

    # Gráfico: barras por secretaria
    fig = go.Figure()
    if not dff.empty and "SECRETARIA" in dff.columns and "VALOR DO ESPELHO" in dff.columns:
        g = dff.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"].sum().sort_values("VALOR DO ESPELHO", ascending=False).head(15)
        fig.add_bar(x=g["SECRETARIA"], y=g["VALOR DO ESPELHO"], text=[_fmt_currency(v) for v in g["VALOR DO ESPELHO"]])
        fig.update_traces(textposition="outside")
    fig.update_layout(title="Valor por Secretaria")
    style_fig(fig, theme)

    # Tabela detalhada
    show_cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","PROCESSO","EMPENHO","DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"]
    present = [c for c in show_cols if c in dff.columns]
    dtable = dff.copy()

    # Links em markdown
    def to_md(u: str, label: str) -> str:
        u = (u or "").strip()
        if not u or u.lower() in {"nan", "none"}:
            return ""
        return f"[{label}]({u})"

    for col, label in [("ESPELHO DIANA","Diana"), ("ESPELHO","Espelho"), ("PDF","PDF"), ("PROCESSO","Processo"), ("EMPENHO","Empenho")]:
        if col in dtable.columns:
            dtable[col] = dtable[col].astype(str).apply(lambda x: to_md(x, label))

    # Formatação de valor
    if "VALOR DO ESPELHO" in dtable.columns:
        dtable["VALOR DO ESPELHO"] = dtable["VALOR DO ESPELHO"].apply(_fmt_currency)

    # Colunas para DataTable (markdown nas de link)
    columns = []
    for c in present:
        col_def = {"name": c, "id": c}
        if c in {"ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"}:
            col_def["presentation"] = "markdown"
        columns.append(col_def)

    data = dtable[present].to_dict("records")

    return (
        f"{total:,}".replace(",", "."),
        soma,
        f"{nsecr:,}".replace(",", "."),
        f"{nag:,}".replace(",", "."),
        fig,
        columns,
        data,
    )

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
