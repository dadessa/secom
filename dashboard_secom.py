# -*- coding: utf-8 -*-
"""
SECOM • Dashboard (Dash)
- Lê planilha via EXCEL_URL (Google Sheets/Drive/Dropbox/OneDrive) OU arquivo local.
- Temas: claro/escuro (aplicados via CSS variables e no Plotly).
- Filtros: Secretaria, Agência, Campanha, Competência (mês), Período (Data do Empenho), Busca.
- Totalizadores e gráfico, mais tabela detalhada com links (markdown) e export para XLSX.
"""

import os
import io
import time
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from dash import Dash, html, dcc, dash_table, Input, Output
import plotly.graph_objects as go

# =============== Config =================
EXCEL_PATH = os.environ.get("EXCEL_PATH", os.path.join("data", "CONTROLE DE PROCESSOS SECOM.xlsx"))
EXCEL_URL = os.environ.get("EXCEL_URL", "").strip()
EXCEL_BEARER_TOKEN = os.environ.get("EXCEL_BEARER_TOKEN", "").strip()
EXCEL_HTTP_USERNAME = os.environ.get("EXCEL_HTTP_USERNAME", "").strip()
EXCEL_HTTP_PASSWORD = os.environ.get("EXCEL_HTTP_PASSWORD", "").strip()
SHEET_NAME = os.environ.get("SHEET_NAME", None)

MISSING_DATA_WARNING = ""

# =============== Tema (apenas claro/escuro) ===============
THEME = {
    "light": {"template": "plotly_white", "font": "#0F172A", "grid": "#E5E7EB"},
    "dark":  {"template": "plotly_dark",  "font": "#E6ECFF", "grid": "#22304A"},
}
def set_theme(theme: str) -> str:
    return theme if theme in {"light", "dark"} else "light"

def style_fig(fig, theme="light"):
    t = THEME.get(set_theme(theme), THEME["light"])
    fig.update_layout(template=t["template"], font=dict(color=t["font"], size=13),
                      margin=dict(l=12,r=12,t=48,b=12), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"])
    return fig

# =============== Helpers de Data ===============
def _try_parse_date(s: pd.Series) -> pd.Series:
    a = pd.to_datetime(s, errors="coerce", format="%d/%m/%Y")
    b = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return a.fillna(b)

def _parse_brl_number(x) -> float:
    """Converte 'R$ 1.234.567,89' (ou variações) em float."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    t = str(x).strip()
    if not t or t.lower() in {"nan", "none"}:
        return 0.0
    t = (t.replace("R$", "").replace("r$", "")
           .replace("\xa0", " ").replace(" ", "")
           .replace(".", "").replace(",", "."))
    try:
        return float(t)
    except Exception:
        try:
            return float(str(x))
        except Exception:
            return 0.0

def _fmt_currency(v) -> str:
    try:
        x = float(v)
    except Exception:
        x = 0.0
    return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _resolve_excel_path() -> Optional[str]:
    if EXCEL_PATH and os.path.exists(EXCEL_PATH):
        return EXCEL_PATH
    if os.path.isdir("data"):
        for fn in os.listdir("data"):
            if fn.lower().endswith(".xlsx"):
                return os.path.join("data", fn)
    return None

def _date_bounds(df: pd.DataFrame, col: str) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    if col not in df.columns or df[col].dtype.kind != "M" or df.empty:
        return None, None
    return df[col].min(), df[col].max()

def _options_for(df: pd.DataFrame, col: str):
    if col not in df.columns or df.empty:
        return []
    ser = df[col].dropna().astype(str).str.strip()
    ser = ser[ser != ""]
    valores = sorted(ser.unique().tolist(), key=lambda s: s.lower())
    return [{"label": v, "value": v} for v in valores]

# =============== Download de planilha (URL) ===============
def _normalize_excel_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u

    if "dropbox.com" in u:
        if "dl=0" in u:
            u = u.replace("dl=0", "dl=1")
        elif "dl=1" not in u and "raw=1" not in u:
            u = f"{u}{'&' if '?' in u else '?'}dl=1"

    if "drive.google.com" in u or "docs.google.com" in u:
        import re
        m = re.search(r"/d/([a-zA-Z0-9_-]{20,})", u) or re.search(r"[?&]id=([a-zA-Z0-9_-]{20,})", u)
        gid = None
        mg = re.search(r"[?&#]gid=(\d+)", u)
        if mg:
            gid = mg.group(1)
        if m:
            fid = m.group(1)
            u = f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx&id={fid}"
            if gid:
                u = f"{u}&gid={gid}"

    if "onedrive.live.com" in u or "sharepoint.com" in u:
        u = f"{u}{'&' if '?' in u else '?'}download=1"

    return u

def _download_excel_bytes(url: str) -> io.BytesIO:
    import requests
    u = _normalize_excel_url(url)
    headers = {"User-Agent": "SECOM-Dashboard/1.0", "Accept": "*/*", "Cache-Control": "no-cache"}
    auth = None
    if EXCEL_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {EXCEL_BEARER_TOKEN}"
    elif EXCEL_HTTP_USERNAME and EXCEL_HTTP_PASSWORD:
        auth = (EXCEL_HTTP_USERNAME, EXCEL_HTTP_PASSWORD)
    # cache bust para evitar CDN do Sheets/Drive retornar conteúdo antigo
    params = {"_": str(int(time.time()))}
    r = requests.get(u, headers=headers, auth=auth, params=params, timeout=45)
    r.raise_for_status()
    return io.BytesIO(r.content)

# =============== Leitura & Normalização ===============
BASE_COLUMNS = [
    "CAMPANHA","SECRETARIA","AGÊNCIA",
    "ESPELHO DIANA","ESPELHO","PDF",
    "VALOR DO ESPELHO","PROCESSO","EMPENHO",
    "DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO"
]

def _coerce_and_rename(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip() for c in d.columns]

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

    # Cria faltantes
    for col in BASE_COLUMNS:
        if col not in d.columns:
            d[col] = np.nan

    # Tipos
    if d["VALOR DO ESPELHO"].dtype.kind in {"O", "U", "S"}:
        d["VALOR DO ESPELHO"] = d["VALOR DO ESPELHO"].apply(_parse_brl_number)
    else:
        d["VALOR DO ESPELHO"] = pd.to_numeric(d["VALOR DO ESPELHO"], errors="coerce").fillna(0.0)

    d["DATA DO EMPENHO"] = _try_parse_date(d["DATA DO EMPENHO"])

    comp = d["COMPETÊNCIA"].astype(str).str.strip()
    comp_dt = pd.to_datetime(comp, errors="coerce", format="%m/%Y")
    comp_dt2 = pd.to_datetime(comp, errors="coerce", dayfirst=True)
    d["COMPETÊNCIA_DT"] = comp_dt.fillna(comp_dt2)
    d["COMPETÊNCIA_TXT"] = comp.where(d["COMPETÊNCIA_DT"].isna(),
                                      d["COMPETÊNCIA_DT"].dt.to_period("M").astype(str))

    for c in ["ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"]:
        d[c] = d[c].astype(str)

    d = d[~(d["SECRETARIA"].isna() & d["AGÊNCIA"].isna() &
            d["CAMPANHA"].isna() & d["PROCESSO"].isna())].copy()

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
                frames.append(_coerce_and_rename(pd.read_excel(xl, sheet_name=s)))
            except Exception:
                continue
    if frames:
        return pd.concat(frames, ignore_index=True, sort=False)
    return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])

def _load_from_excel_bytes(buf: io.BytesIO) -> pd.DataFrame:
    global MISSING_DATA_WARNING
    try:
        xl = pd.ExcelFile(buf)
    except Exception as e:
        MISSING_DATA_WARNING = f"Não foi possível abrir a planilha remota: {e}"
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])
    return _read_all_sheets(xl)

def _load_local(path: str) -> pd.DataFrame:
    try:
        xl = pd.ExcelFile(path)
        return _read_all_sheets(xl)
    except Exception:
        return _coerce_and_rename(pd.read_excel(path, sheet_name=SHEET_NAME))

def _load_data() -> pd.DataFrame:
    global MISSING_DATA_WARNING
    # 1) URL (preferido)
    if EXCEL_URL:
        try:
            buf = _download_excel_bytes(EXCEL_URL)
            dfurl = _load_from_excel_bytes(buf)
            if not dfurl.empty:
                return dfurl.fillna("")
            else:
                MISSING_DATA_WARNING = "Planilha remota vazia/não reconhecida."
        except Exception as e:
            MISSING_DATA_WARNING = f"Falha ao baixar planilha remota: {e}"

    # 2) Fallback local
    path = _resolve_excel_path()
    if not path:
        MISSING_DATA_WARNING = MISSING_DATA_WARNING or "Nenhuma planilha encontrada e EXCEL_URL não configurada."
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])
    try:
        return _load_local(path).fillna("")
    except Exception as e:
        MISSING_DATA_WARNING = f"Falha ao abrir planilha local: {e}"
        return pd.DataFrame(columns=BASE_COLUMNS + ["COMPETÊNCIA_DT","COMPETÊNCIA_TXT"])

# Base inicial
DF_BASE = _load_data()

# =============== App ===============
app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

# =============== Layout ===============
app.layout = html.Div(
    id="page",
    className="page light",
    children=[
        html.Div(
            className="container",
            children=[
                html.Div(
                    className="sidebar",
                    children=[
                        html.H1("SECOM • Controle de Processos", className="title"),
                        html.Div(className="box", children=[
                            html.Label("Tema"),
                            dcc.RadioItems(
                                id="theme",
                                options=[{"label":"Claro","value":"light"},{"label":"Escuro","value":"dark"}],
                                value="light",
                                inline=True,
                            ),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Secretaria"),
                            dcc.Dropdown(id="f_secretaria",
                                         options=_options_for(DF_BASE, "SECRETARIA"),
                                         multi=True, placeholder="Todas"),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Agência"),
                            dcc.Dropdown(id="f_agencia",
                                         options=_options_for(DF_BASE, "AGÊNCIA"),
                                         multi=True, placeholder="Todas"),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Campanha"),
                            dcc.Dropdown(id="f_campanha",
                                         options=_options_for(DF_BASE, "CAMPANHA"),
                                         multi=True, placeholder="Todas"),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Competência (mês)"),
                            dcc.Dropdown(id="f_comp",
                                         options=_options_for(DF_BASE, "COMPETÊNCIA_TXT"),
                                         multi=True, placeholder="Todas"),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Período (Data do Empenho)"),
                            dcc.DatePickerRange(
                                id="f_periodo",
                                start_date=_date_bounds(DF_BASE, "DATA DO EMPENHO")[0],
                                end_date=_date_bounds(DF_BASE, "DATA DO EMPENHO")[1],
                                min_date_allowed=_date_bounds(DF_BASE, "DATA DO EMPENHO")[0],
                                max_date_allowed=_date_bounds(DF_BASE, "DATA DO EMPENHO")[1],
                                display_format="DD/MM/YYYY",
                            ),
                        ]),
                        html.Div(className="box", children=[
                            html.Label("Busca (processo / observação)"),
                            dcc.Input(id="f_busca", type="text", debounce=True,
                                      placeholder="Digite um termo", style={"width":"100%"}),
                        ]),
                        html.Div(className="box", children=[
                            html.Button("Atualizar dados (↻)", id="btn_reload", n_clicks=0, className="btn"),
                        ]),
                        html.Div(MISSING_DATA_WARNING, id="warn", className="warn"),
                    ],
                ),
                html.Div(
                    className="content",
                    children=[
                        html.Div(className="kpis", children=[
                            html.Div(className="kpi",
                                     children=[html.Div("Registros", className="kpi-label"),
                                               html.Div(id="kpi_total", className="kpi-value")]),
                            html.Div(className="kpi",
                                     children=[html.Div("Valor total", className="kpi-label"),
                                               html.Div(id="kpi_valor", className="kpi-value")]),
                            html.Div(className="kpi",
                                     children=[html.Div("Secretarias", className="kpi-label"),
                                               html.Div(id="kpi_secr", className="kpi-value")]),
                            html.Div(className="kpi",
                                     children=[html.Div("Agências", className="kpi-label"),
                                               html.Div(id="kpi_ag", className="kpi-value")]),
                        ]),
                        html.Div(className="card", children=[dcc.Graph(id="fig_bar_secretaria")]),
                        html.Div(className="card", children=[
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
                        ]),
                    ],
                ),
            ],
        ),
        dcc.Store(id="store_df", data=DF_BASE.to_json(date_format="iso", orient="split")),
    ],
)

# =============== Callbacks ===============
@app.callback(Output("page", "className"), Input("theme", "value"))
def _swap_theme(theme):
    return f"page {set_theme(theme)}"

@app.callback(
    Output("store_df", "data"),
    Output("warn", "children"),
    Input("btn_reload", "n_clicks"),
    prevent_initial_call=True,
)
def reload_base(n_clicks):
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

def _filtrar(df: pd.DataFrame,
             secre: Optional[List[str]],
             ag: Optional[List[str]],
             camp: Optional[List[str]],
             comp: Optional[List[str]],
             ini: Optional[str], fim: Optional[str],
             termo: Optional[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    dff = df.copy()
    if secre: dff = dff[dff["SECRETARIA"].astype(str).isin(secre)]
    if ag:    dff = dff[dff["AGÊNCIA"].astype(str).isin(ag)]
    if camp:  dff = dff[dff["CAMPANHA"].astype(str).isin(camp)]
    if comp:  dff = dff[dff["COMPETÊNCIA_TXT"].astype(str).isin(comp)]
    if ini and fim and "DATA DO EMPENHO" in dff and dff["DATA DO EMPENHO"].dtype.kind=="M":
        ini_dt, fim_dt = pd.to_datetime(ini), pd.to_datetime(fim)
        dff = dff[(dff["DATA DO EMPENHO"] >= ini_dt) & (dff["DATA DO EMPENHO"] <= fim_dt)]
    if termo:
        t = str(termo).strip().lower()
        if t:
            mask = pd.Series(False, index=dff.index)
            for c in ["PROCESSO","OBSERVAÇÃO","CAMPANHA","SECRETARIA","AGÊNCIA","EMPENHO"]:
                if c in dff.columns:
                    mask |= dff[c].astype(str).str.lower().str.contains(t, na=False)
            dff = dff[mask]
    return dff

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

    total = len(dff)
    soma = _fmt_currency(dff["VALOR DO ESPELHO"].sum() if "VALOR DO ESPELHO" in dff.columns else 0.0)
    nsecr = dff["SECRETARIA"].nunique() if "SECRETARIA" in dff.columns else 0
    nag = dff["AGÊNCIA"].nunique() if "AGÊNCIA" in dff.columns else 0

    fig = go.Figure()
    if not dff.empty and {"SECRETARIA","VALOR DO ESPELHO"} <= set(dff.columns):
        g = (dff.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"]
               .sum().sort_values("VALOR DO ESPELHO", ascending=False).head(15))
        fig.add_bar(x=g["SECRETARIA"], y=g["VALOR DO ESPELHO"],
                    text=[_fmt_currency(v) for v in g["VALOR DO ESPELHO"]])
        fig.update_traces(textposition="outside")
    fig.update_layout(title="Valor por Secretaria")
    style_fig(fig, theme)

    show_cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","PROCESSO","EMPENHO",
                 "DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"]
    present = [c for c in show_cols if c in dff.columns]
    dtable = dff.copy()

    def to_md(u: str, label: str) -> str:
        u = (u or "").strip()
        if not u or u.lower() in {"nan","none"}:
            return ""
        return f"[{label}]({u})"

    for col, label in [("ESPELHO DIANA","Diana"),("ESPELHO","Espelho"),
                       ("PDF","PDF"),("PROCESSO","Processo"),("EMPENHO","Empenho")]:
        if col in dtable.columns:
            dtable[col] = dtable[col].astype(str).apply(lambda x: to_md(x, label))

    if "VALOR DO ESPELHO" in dtable.columns:
        dtable["VALOR DO ESPELHO"] = dtable["VALOR DO ESPELHO"].apply(_fmt_currency)

    columns = []
    for c in present:
        col_def = {"name": c, "id": c}
        if c in {"ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"}:
            col_def["presentation"] = "markdown"
        columns.append(col_def)
    data = dtable[present].to_dict("records")

    return (f"{total:,}".replace(",", "."),
            soma,
            f"{nsecr:,}".replace(",", "."),
            f"{nag:,}".replace(",", "."),
            fig, columns, data)

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
