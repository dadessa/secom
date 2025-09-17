
import io
import os
import re
import json
import math
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional

import requests
import pandas as pd
import numpy as np

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash import Dash, dcc, html, dash_table, Input, Output, State, ctx

# ------------------------------
# Config
# ------------------------------

DEFAULT_SHEETS_EXPORT_URL = os.environ.get(
    "EXCEL_URL",
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)
SHEET_NAME = os.environ.get("SHEET_NAME", None)  # se quiser travar uma aba específica

APP_TITLE = "SECOM • Controle de Processos"

# Mapeamento de aliases para nomes de colunas canônicos do dashboard
COLUMN_ALIASES: Dict[str, str] = {
    # canônicos -> possíveis nomes (variações comuns);
    "SECRETARIA": "SECRETARIA|SEC(RETARIA)?",
    "AGÊNCIA": "AG(Ê|E)NCIA|AGENCIA",
    "CAMPANHA": "CAMPANHA",
    "VALOR DO ESPELHO": "VALOR ?(DO )?ESPELHO|VALOR",
    "PROCESSO": "PROCESSO|URL.PROCESSO",
    "EMPENHO": "EMPENHO|URL.EMPENHO",
    "DATA DO EMPENHO": "DATA( DO)? EMPENHO|DT.?EMPENHO|EMISSAO.?EMPENHO",
    "COMPETÊNCIA": "COMP(Ê|E)T(Ê|E)NCIA(_TXT)?|COMPETENCIA.?TXT",
    "OBSERVAÇÃO": "OBSERVA(Ç|C)AO|OBSERVAÇÃO|OBS",
    "ESPELHO DIANA": "ESPELHO.?DIANA|DIANA",
    "ESPELHO": "^ESPELHO$|LINK.?ESPELHO",
    "PDF": "PDF|LINK.?PDF",
}

# ------------------------------
# Utilitários
# ------------------------------

def _strip_accents(s: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFD', s) if unicodedata.category(ch) != 'Mn')

def _norm(s: str) -> str:
    s = s or ""
    s = str(s)
    s = _strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def _normalize_excel_url(url: str) -> str:
    """Aceita links de view/edição do Google Sheets e converte para export XLSX."""
    if not url:
        return DEFAULT_SHEETS_EXPORT_URL
    if "export?format=xlsx" in url:
        return url
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m:
        return url
    fid = m.group(1)
    return f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx&id={fid}"

def _coerce_brl_number(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    # já é número
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        try:
            return float(s)
        except Exception:
            return np.nan
    # padrão BR (1.234.567,89)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return np.nan

def _as_month_start(dt: pd.Series) -> pd.Series:
    dt = pd.to_datetime(dt, errors="coerce", dayfirst=True)
    return (dt.dt.to_period("M")).dt.to_timestamp()

def _read_google_sheets_xlsx(url: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    url = _normalize_excel_url(url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    file_like = io.BytesIO(resp.content)
    # Pode ter múltiplas abas; se não especificar, concatena todas
    xl = pd.ExcelFile(file_like)
    frames = []
    for name in xl.sheet_names:
        if sheet_name and name != sheet_name:
            continue
        df = xl.parse(name)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    return out

def _canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # cria mapa col_original -> col_canonica
    rename_map = {}
    for col in df.columns:
        col_norm = _norm(col)
        chosen = None
        for canonical, pattern in COLUMN_ALIASES.items():
            pat = re.compile(pattern, flags=re.I)
            if pat.search(_strip_accents(col)):
                chosen = canonical
                break
        if chosen:
            rename_map[col] = chosen
    df = df.rename(columns=rename_map)
    return df

def _prepare_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=list(COLUMN_ALIASES.keys()))
    df = _canonicalize_columns(raw.copy())

    # Garante as colunas canônicas
    for need in COLUMN_ALIASES.keys():
        if need not in df.columns:
            df[need] = np.nan

    # Coerções
    df["VALOR DO ESPELHO"] = df["VALOR DO ESPELHO"].apply(_coerce_brl_number).fillna(0.0)

    # Datas
    # Competência pode vir como texto; cria COMPETENCIA_DT
    comp_raw = df["COMPETÊNCIA"]
    comp_dt = pd.to_datetime(comp_raw, errors="coerce", dayfirst=True)
    # se for yyyy-mm (string), o to_datetime já entende; se vier vazio, usa DATA DO EMPENHO
    if "DATA DO EMPENHO" in df.columns:
        empenho_dt = pd.to_datetime(df["DATA DO EMPENHO"], errors="coerce", dayfirst=True)
    else:
        empenho_dt = pd.NaT
    comp_dt = comp_dt.fillna(empenho_dt)
    df["COMPETENCIA_DT"] = _as_month_start(comp_dt)

    # Normaliza textos para strings
    for c in ["SECRETARIA", "AGÊNCIA", "CAMPANHA", "OBSERVAÇÃO"]:
        df[c] = df[c].astype(str).fillna("")

    # Links em markdown (DataTable: presentation='markdown')
    def mk_link(url, label):
        u = str(url).strip()
        if u and u.lower().startswith(("http://", "https://")):
            # abrirá na mesma aba no DataTable; dashboards geralmente não permitem target="_blank" no markdown
            return f"[{label}]({u})"
        return ""

    for col, label in [("PROCESSO", "Processo"), ("EMPENHO", "Empenho"),
                       ("ESPELHO DIANA", "Diana"), ("ESPELHO", "Espelho"), ("PDF", "PDF")]:
        df[col] = df[col].apply(lambda x: mk_link(x, label))

    # Datas em exibição
    df["DATA DO EMPENHO"] = pd.to_datetime(df["DATA DO EMPENHO"], errors="coerce", dayfirst=True)

    # Para filtros: cria colunas auxiliares (strings)
    df["_SECRETARIA_TXT"] = df["SECRETARIA"].astype(str)
    df["_AGENCIA_TXT"] = df["AGÊNCIA"].astype(str)
    df["_CAMPANHA_TXT"] = df["CAMPANHA"].astype(str)
    df["_COMP_TXT"] = df["COMPETÊNCIA"].astype(str)

    return df

def load_data(url: Optional[str] = None, sheet_name: Optional[str] = SHEET_NAME) -> pd.DataFrame:
    try:
        base = _read_google_sheets_xlsx(url or DEFAULT_SHEETS_EXPORT_URL, sheet_name=sheet_name)
    except Exception as e:
        # se falhar, retorna DF vazio com colunas canônicas para não quebrar layout
        base = pd.DataFrame(columns=list(COLUMN_ALIASES.keys()))
    return _prepare_dataframe(base)

# ------------------------------
# Dash app
# ------------------------------

app = Dash(__name__)
server = app.server

THEMES = {
    "Claro": {
        "bg": "#0b1220",  # mantendo fundo escuro por padrão visual; porém textos claros – ajustamos para 'Claro' como interface clara
        "card": "#0f172a",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "accent": "#60a5fa",
        "template": "plotly_dark",
        "inverted": False,
    },
    "Escuro": {
        "bg": "#0b1220",
        "card": "#0f172a",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "accent": "#8b5cf6",
        "template": "plotly_dark",
        "inverted": True,
    }
}
# Força Claro como tema inicial (conforme pedido anterior)
DEFAULT_THEME = "Claro"


def card(children, theme_name: str, style_extra=None):
    t = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    style = {
        "background": t["card"],
        "color": t["text"],
        "borderRadius": "14px",
        "padding": "14px",
        "boxShadow": "0 2px 6px rgba(0,0,0,.2)",
    }
    if style_extra:
        style.update(style_extra)
    return html.Div(children, style=style)


def stat(label: str, value: str, theme_name: str):
    t = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    return html.Div(
        [
            html.Div(label, style={"fontSize": "12px", "color": t["muted"]}),
            html.Div(value, style={"fontSize": "22px", "fontWeight": 700, "marginTop": "4px"}),
        ]
    )


def layout(theme_name: str = DEFAULT_THEME):
    t = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    return html.Div(
        style={
            "background": t["bg"],
            "minHeight": "100vh",
            "color": t["text"],
            "fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial",
            "padding": "16px 20px",
        },
        children=[
            html.H2(APP_TITLE, style={"marginBottom": "12px"}),
            # Estado (dados em memória + tema)
            dcc.Store(id="store-data"),
            dcc.Store(id="store-theme", data=DEFAULT_THEME),

            # Linha de controles
            card([
                html.Div([
                    html.Div([
                        html.Span("Tema", style={"fontSize": "12px", "color": t["muted"]}),
                        dcc.RadioItems(
                            id="theme",
                            options=[{"label": "Claro", "value": "Claro"},
                                     {"label": "Escuro", "value": "Escuro"}],
                            value=DEFAULT_THEME,
                            inline=True,
                            inputStyle={"marginRight": "6px", "marginLeft": "10px"},
                            style={"marginBottom": "8px"}
                        ),
                    ], style={"minWidth": "160px", "marginRight": "20px"}),
                    html.Div(style={"flex": 1}),
                    html.Button("Atualizar dados (↻)", id="btn-refresh", n_clicks=0,
                                style={"background": t["accent"], "color": "#0b1220", "border": "0",
                                       "padding": "8px 12px", "borderRadius": "10px", "fontWeight": 600})
                ], style={"display": "flex", "alignItems": "center", "gap": "12px"}),

                html.Div([
                    html.Div([html.Label("Secretaria"), dcc.Dropdown(id="f_secretaria", multi=True, placeholder="Todas")]),
                    html.Div([html.Label("Agência"), dcc.Dropdown(id="f_agencia", multi=True, placeholder="Todas")]),
                    html.Div([html.Label("Campanha"), dcc.Dropdown(id="f_campanha", multi=True, placeholder="Todas")]),
                    html.Div([html.Label("Competência (mês)"), dcc.Dropdown(id="f_comp", multi=True, placeholder="Todas")]),
                ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr 1fr", "gap": "10px", "marginTop": "10px"}),

                html.Div([
                    html.Div([html.Label("Período (Data do Empenho)"),
                              dcc.DatePickerRange(id="f_periodo", display_format="DD/MM/YYYY")]),
                    html.Div([html.Label("Busca (processo / observação)"),
                              dcc.Input(id="f_busca", type="text", placeholder="Digite um termo", style={"width": "100%"})]),
                ], style={"display": "grid", "gridTemplateColumns": "380px 1fr", "gap": "10px", "marginTop": "10px"}),
            ], theme_name),

            # Métricas
            html.Div(id="metrics-row", style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "10px", "marginTop": "12px"}),

            # Gráficos
            html.Div([
                card(dcc.Graph(id="g_evolucao"), theme_name),
            ], style={"marginTop": "12px"}),

            html.Div([
                card(dcc.Graph(id="g_secretarias"), theme_name),
                card(dcc.Graph(id="g_agencias"), theme_name),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginTop": "12px"}),

            html.Div([
                card(dcc.Graph(id="g_treemap"), theme_name),
                card(dcc.Graph(id="g_campanhas"), theme_name),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginTop": "12px"}),

            # Tabela
            html.Div([
                card([
                    html.H4("Detalhamento"),
                    dash_table.DataTable(
                        id="tbl",
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        export_format="xlsx",
                        export_headers="display",
                        style_table={"overflowX": "auto"},
                        style_cell={
                            "background": t["card"],
                            "color": t["text"],
                            "border": "0px",
                            "fontSize": 13,
                            "whiteSpace": "normal",
                            "height": "auto",
                        },
                        style_header={
                            "background": t["card"],
                            "color": t["muted"],
                            "fontWeight": 700,
                            "borderBottom": f"1px solid {t['muted']}",
                        },
                        style_data_conditional=[
                            {"if": {"column_id": "VALOR DO ESPELHO"},
                             "textAlign": "right", "fontVariantNumeric": "tabular-nums"},
                        ],
                    )
                ], theme_name),
            ], style={"marginTop": "12px"}),

            # Dados carregados ao montar
            dcc.Interval(id="once", n_intervals=0, interval=500, max_intervals=1),
        ]
    )

app.layout = layout()

# ------------------------------
# Callbacks
# ------------------------------

def make_options(values: pd.Series) -> List[Dict]:
    uniq = sorted({str(x) for x in values if (str(x).strip() and str(x).lower() != "nan")})
    return [{"label": v, "value": v} for v in uniq]

@app.callback(
    Output("store-data", "data"),
    Input("once", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def _load_initial_data(_n, _btn):
    df = load_data(DEFAULT_SHEETS_EXPORT_URL, SHEET_NAME)
    # min/max para o DatePicker
    min_dt = str(df["DATA DO EMPENHO"].min()) if "DATA DO EMPENHO" in df.columns else None
    max_dt = str(df["DATA DO EMPENHO"].max()) if "DATA DO EMPENHO" in df.columns else None
    return {"csv": df.to_csv(index=False), "min_dt": min_dt, "max_dt": max_dt}

@app.callback(
    Output("f_secretaria", "options"),
    Output("f_agencia", "options"),
    Output("f_campanha", "options"),
    Output("f_comp", "options"),
    Output("f_periodo", "min_date_allowed"),
    Output("f_periodo", "max_date_allowed"),
    Input("store-data", "data"),
)
def _fill_filter_options(data):
    if not data:
        raise dash.exceptions.PreventUpdate
    df = pd.read_csv(io.StringIO(data["csv"]))
    # COMPETÊNCIA: usa texto se existir senão mês derivado
    comp_col = "COMPETÊNCIA" if "COMPETÊNCIA" in df.columns else None
    f1 = make_options(df.get("SECRETARIA", pd.Series([], dtype=object)))
    f2 = make_options(df.get("AGÊNCIA", pd.Series([], dtype=object)))
    f3 = make_options(df.get("CAMPANHA", pd.Series([], dtype=object)))
    if comp_col:
        f4 = make_options(df[comp_col])
    else:
        # Deriva do COMPETENCIA_DT -> "YYYY-MM"
        tmp = pd.to_datetime(df.get("COMPETENCIA_DT", pd.Series([], dtype=object)), errors="coerce")
        f4 = make_options(tmp.dt.strftime("%Y-%m"))
    return f1, f2, f3, f4, data.get("min_dt"), data.get("max_dt")

def _apply_filters(df: pd.DataFrame,
                   secretarias: List[str],
                   agencias: List[str],
                   campanhas: List[str],
                   comps: List[str],
                   periodo,
                   busca: str) -> pd.DataFrame:
    out = df.copy()
    if secretarias:
        out = out[out["SECRETARIA"].astype(str).isin(secretarias)]
    if agencias:
        out = out[out["AGÊNCIA"].astype(str).isin(agencias)]
    if campanhas:
        out = out[out["CAMPANHA"].astype(str).isin(campanhas)]
    if comps:
        # comps são strings; se DF tiver COMPETÊNCIA textual, usa direto; senão compara com COMPETENCIA_DT %Y-%m
        if "COMPETÊNCIA" in out.columns and out["COMPETÊNCIA"].notna().any():
            out = out[out["COMPETÊNCIA"].astype(str).isin(comps)]
        else:
            ckey = out["COMPETENCIA_DT"].dt.strftime("%Y-%m")
            out = out[ckey.isin(comps)]
    if periodo and all(periodo):
        ini = pd.to_datetime(periodo[0], errors="coerce")
        fim = pd.to_datetime(periodo[1], errors="coerce")
        if not ini is pd.NaT and not fim is pd.NaT and "DATA DO EMPENHO" in out.columns:
            d = pd.to_datetime(out["DATA DO EMPENHO"], errors="coerce")
            out = out[(d >= ini) & (d <= fim)]
    if busca and busca.strip():
        pat = _norm(busca)
        def has_term(x):
            s = _norm(str(x))
            return pat in s
        mask = (
            out["PROCESSO"].astype(str).map(has_term) |
            out["OBSERVAÇÃO"].astype(str).map(has_term)
        )
        out = out[mask]
    return out

@app.callback(
    Output("metrics-row", "children"),
    Output("g_evolucao", "figure"),
    Output("g_secretarias", "figure"),
    Output("g_agencias", "figure"),
    Output("g_treemap", "figure"),
    Output("g_campanhas", "figure"),
    Output("tbl", "columns"),
    Output("tbl", "data"),
    Input("store-data", "data"),
    Input("f_secretaria", "value"),
    Input("f_agencia", "value"),
    Input("f_campanha", "value"),
    Input("f_comp", "value"),
    Input("f_periodo", "start_date"),
    Input("f_periodo", "end_date"),
    Input("f_busca", "value"),
    Input("theme", "value"),
)
def _update_view(data, f_sec, f_ag, f_camp, f_comp, d_ini, d_fim, busca, theme_name):
    theme_name = theme_name or DEFAULT_THEME
    t = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    template = t["template"]

    if not data:
        empty_fig = go.Figure()
        return [], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, [], []

    df = pd.read_csv(io.StringIO(data["csv"]))
    # Reconstruir tipos
    df["DATA DO EMPENHO"] = pd.to_datetime(df.get("DATA DO EMPENHO"), errors="coerce", dayfirst=True)
    df["COMPETENCIA_DT"] = pd.to_datetime(df.get("COMPETENCIA_DT"), errors="coerce")

    f_df = _apply_filters(df, f_sec or [], f_ag or [], f_camp or [], f_comp or [], (d_ini, d_fim), busca or "")

    # ---- métricas
    total_regs = len(f_df)
    total_val = f_df["VALOR DO ESPELHO"].sum() if "VALOR DO ESPELHO" in f_df.columns else 0.0
    n_secs = f_df["SECRETARIA"].nunique() if "SECRETARIA" in f_df.columns else 0
    n_ags = f_df["AGÊNCIA"].nunique() if "AGÊNCIA" in f_df.columns else 0
    metrics = [
        card(stat("Registros", f"{total_regs:,}".replace(",", ".")), theme_name),
        card(stat("Valor total", "R$ {:,.2f}".format(total_val).replace(",", "X").replace(".", ",").replace("X", ".")), theme_name),
        card(stat("Secretarias", f"{n_secs:,}".replace(",", ".")), theme_name),
        card(stat("Agências", f"{n_ags:,}".replace(",", ".")), theme_name),
    ]

    # ---- Evolução mensal
    evol = f_df.dropna(subset=["COMPETENCIA_DT"]).copy()
    evol = evol.groupby(evol["COMPETENCIA_DT"].dt.to_period("M")).agg({"VALOR DO ESPELHO":"sum"}).reset_index()
    if not evol.empty:
        evol["COMPETENCIA_DT"] = evol["COMPETENCIA_DT"].dt.to_timestamp()
    fig1 = px.area(evol, x="COMPETENCIA_DT", y="VALOR DO ESPELHO", template=template, title="Evolução mensal (soma do Valor)")
    fig1.update_layout(margin=dict(l=20,r=20,t=40,b=20), hovermode="x unified")
    fig1.update_yaxes(tickformat=",.2f")

    # ---- Top 10 Secretarias (horizontal)
    s1 = f_df.groupby("SECRETARIA", dropna=False)["VALOR DO ESPELHO"].sum().sort_values(ascending=False).head(10)[::-1]
    fig2 = px.bar(x=s1.values, y=s1.index, orientation="h", template=template, title="Top 10 Secretarias (por valor)")
    fig2.update_layout(margin=dict(l=20,r=20,t=40,b=20))
    fig2.update_xaxes(tickformat=",.2f")

    # ---- Top 10 Agências (horizontal)
    a1 = f_df.groupby("AGÊNCIA", dropna=False)["VALOR DO ESPELHO"].sum().sort_values(ascending=False).head(10)[::-1]
    fig3 = px.bar(x=a1.values, y=a1.index, orientation="h", template=template, title="Top 10 Agências (por valor)")
    fig3.update_layout(margin=dict(l=20,r=20,t=40,b=20))
    fig3.update_xaxes(tickformat=",.2f")

    # ---- Treemap Secretaria -> Agência
    tm = f_df.groupby(["SECRETARIA","AGÊNCIA"], dropna=False)["VALOR DO ESPELHO"].sum().reset_index()
    fig4 = px.treemap(tm, path=["SECRETARIA","AGÊNCIA"], values="VALOR DO ESPELHO", template=template, title="Proporção por Secretaria → Agência")
    fig4.update_layout(margin=dict(l=10,r=10,t=40,b=10))

    # ---- Campanhas (pareto)
    camp = f_df.groupby("CAMPANHA", dropna=False)["VALOR DO ESPELHO"].sum().sort_values(ascending=False).head(20).reset_index()
    cum = camp["VALOR DO ESPELHO"].cumsum() / camp["VALOR DO ESPELHO"].sum() * 100.0
    fig5 = make_subplots(specs=[[{"secondary_y": True}]])
    fig5.add_trace(go.Bar(x=camp["CAMPANHA"], y=camp["VALOR DO ESPELHO"], name="Valor"), secondary_y=False)
    fig5.add_trace(go.Scatter(x=camp["CAMPANHA"], y=cum, mode="lines+markers", name="Pareto %"), secondary_y=True)
    fig5.update_layout(template=template, title="Campanhas por valor (Pareto)", margin=dict(l=20,r=20,t=40,b=20))
    fig5.update_yaxes(title_text="Valor", secondary_y=False, tickformat=",.")
    fig5.update_yaxes(title_text="% Acumulado", secondary_y=True, range=[0, 100])

    # ---- Tabela detalhada
    show_cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","PROCESSO","EMPENHO","DATA DO EMPENHO",
                 "COMPETÊNCIA","OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"]
    cols = [c for c in show_cols if c in f_df.columns]

    fmt_money = {"type":"numeric", "format": {"locale": {"group": ".", "decimal": ","}, "specifier": ",.2f"}}
    dt_cols = []
    for c in cols:
        if c in ["PROCESSO","EMPENHO","ESPELHO DIANA","ESPELHO","PDF"]:
            dt_cols.append({"name": c, "id": c, "presentation": "markdown"})
        elif c == "VALOR DO ESPELHO":
            dt_cols.append({"name": c, "id": c, **fmt_money})
        elif c == "DATA DO EMPENHO":
            # formato dd/mm/yyyy
            vals = pd.to_datetime(f_df[c], errors="coerce", dayfirst=True).dt.strftime("%d/%m/%Y")
            f_df = f_df.copy()
            f_df[c] = vals
            dt_cols.append({"name": c, "id": c})
        else:
            dt_cols.append({"name": c, "id": c})

    # prepara dados
    data_rows = f_df[cols].to_dict("records")

    return metrics, fig1, fig2, fig3, fig4, fig5, dt_cols, data_rows

# Re-render layout quando trocar o tema (para aplicar estilos nos cartões)
@app.callback(
    Output(component_id=None, component_property="children"),
    Input("theme", "value"),
    prevent_initial_call=True
)
def _rerender(_theme):
    # truque: atualizar app.layout (Dash não permite direto via callback; aqui só para forçar recomputo)
    app.layout = layout(theme_name=_theme)
    return dash.no_update

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
