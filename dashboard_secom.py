import os
import io
import json
import time
from datetime import datetime
from dateutil import parser as dtparser

import requests
import polars as pl
import plotly.express as px
import plotly.graph_objects as go

from dash import Dash, html, dcc, Input, Output, State, dash_table, no_update

# -----------------------------
# Config / helpers
# -----------------------------

APP_TITLE = "SECOM – Monitor"
DEFAULT_THEME = "light"  # claro por padrão
PLOT_TEMPLATES = {"light": "plotly_white", "dark": "plotly_dark"}

# URLs / abas
GSHEET_BASE = os.getenv(
    "GSHEET_BASE",
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=csv&gid={gid}",
)
GSHEET_TABS = os.getenv("GSHEET_TABS", '{"Geral":0}')

try:
    TAB_MAP = {k: int(v) for k, v in json.loads(GSHEET_TABS).items()}
except Exception:
    TAB_MAP = {"Geral": 0}

TAB_OPTIONS = [{"label": name, "value": str(gid)} for name, gid in TAB_MAP.items()]
DEFAULT_GID = str(next(iter(TAB_MAP.values())))  # primeiro da lista

# Campos esperados (use nomes exatamente como estão na planilha)
# Ajuste os aliases para cobrir variações comuns.
ALIASES = {
    "CAMPANHA": ["CAMPANHA", "CAMPANHAS"],
    "SECRETARIA": ["SECRETARIA", "ÓRGÃO", "ORGAO"],
    "AGÊNCIA": ["AGÊNCIA", "AGENCIA"],
    "VALOR DO ESPELHO": ["VALOR DO ESPELHO", "VALOR", "VALOR_TOTAL", "TOTAL"],
    "PROCESSO": ["PROCESSO", "LINK PROCESSO", "URL PROCESSO"],
    "EMPENHO": ["EMPENHO", "LINK EMPENHO", "URL EMPENHO"],
    "DATA DO EMPENHO": ["DATA DO EMPENHO", "DT EMPENHO", "DATA_EMPENHO"],
    "COMPETÊNCIA": ["COMPETÊNCIA", "COMPETENCIA", "COMPETÊNCIA_TXT", "COMPETENCIA_TXT", "COMPETÊNCIA_DT", "COMPETENCIA_DT"],
    "OBSERVAÇÃO": ["OBSERVAÇÃO", "OBSERVACAO", "OBSERVAÇÕES", "OBS"],
    "ESPELHO DIANA": ["ESPELHO DIANA", "DIANA"],
    "ESPELHO": ["ESPELHO"],
    "PDF": ["PDF", "LINK PDF"],
}

# Limites visuais para evitar “expansão infinita”
GRAPH_HEIGHT = 420
CARD_MAX_HEIGHT = 460

def _guess_col(df: pl.DataFrame, canonical: str) -> str | None:
    """Encontra nome de coluna equivalente na planilha usando ALIASES."""
    if canonical in df.columns:
        return canonical
    wanted = [c.lower() for c in ALIASES.get(canonical, [])]
    mapping = {c.lower(): c for c in df.columns}
    for candidate in wanted:
        if candidate in mapping:
            return mapping[candidate]
    # fallback: match por início
    for c in df.columns:
        if c.lower().startswith(canonical.lower()):
            return c
    return None

def _to_brl(x) -> str:
    try:
        v = float(x)
        # formato BRL simples
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return ""

def _parse_date(s: str | None) -> datetime | None:
    if s is None or s == "":
        return None
    # aceita dd/mm/aaaa, aaaa-mm-dd, etc
    try:
        return dtparser.parse(str(s), dayfirst=True)
    except Exception:
        return None

def _fetch_csv_for_gid(gid: str) -> pl.DataFrame:
    url = GSHEET_BASE.format(gid=gid)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    # Polars lida direto com bytes CSV
    return pl.read_csv(io.BytesIO(r.content), infer_schema_length=5000, ignore_errors=True)

def _normalize_df(df: pl.DataFrame) -> pl.DataFrame:
    # Garantir que todas as colunas existam (mesmo que vazias)
    cols = {}
    for key in ALIASES.keys():
        col = _guess_col(df, key)
        cols[key] = col

    # Renomear para nomes canônicos onde existirem
    rename_map = {}
    for canonical, found in cols.items():
        if found and found != canonical:
            rename_map[found] = canonical
    if rename_map:
        df = df.rename(rename_map)

    # Criar colunas ausentes vazias
    for canonical, found in cols.items():
        if found is None and canonical not in df.columns:
            df = df.with_columns(pl.lit(None).alias(canonical))

    # TIPAGEM
    # Valor
    df = df.with_columns(
        pl.col("VALOR DO ESPELHO")
        .cast(str)
        .str.replace_all(r"[R\$\s\.]", "")
        .str.replace(",", ".")
        .cast(pl.Float64, strict=False)
        .fill_null(0.0)
    )
    # Datas e Competência TXT
    df = df.with_columns(
        [
            pl.col("DATA DO EMPENHO").cast(str).map_elements(_parse_date).alias("DATA DO EMPENHO_DT"),
            pl.col("COMPETÊNCIA").cast(str).alias("COMPETÊNCIA_TXT"),
        ]
    )
    # Competência normalizada (mês/ano)
    def comp_norm(s: str | None) -> str | None:
        if not s:
            return None
        # tenta “mm/aaaa”, “mmm/aaaa” ou “aaaa-mm”
        try:
            d = _parse_date("01/" + s) or _parse_date(s + "-01")
            if d:
                return d.strftime("%Y-%m")
        except Exception:
            pass
        return s  # devolve original se não identificar

    df = df.with_columns(
        pl.col("COMPETÊNCIA_TXT").map_elements(comp_norm).alias("COMPETÊNCIA_NORM")
    )

    # Strings seguras (evita None no DataTable)
    for sc in ["CAMPANHA", "SECRETARIA", "AGÊNCIA", "PROCESSO", "EMPENHO", "OBSERVAÇÃO", "ESPELHO DIANA", "ESPELHO", "PDF"]:
        if sc in df.columns:
            df = df.with_columns(pl.col(sc).cast(str).fill_null(""))

    return df

def _make_figs(df: pl.DataFrame, theme: str):
    template = PLOT_TEMPLATES.get(theme, PLOT_TEMPLATES[DEFAULT_THEME])

    # Evolução mensal
    evol = (
        df.filter(pl.col("COMPETÊNCIA_NORM").is_not_null())
          .groupby("COMPETÊNCIA_NORM")
          .agg(pl.col("VALOR DO ESPELHO").sum().alias("TOTAL"))
          .sort("COMPETÊNCIA_NORM")
    )
    fig_evol = px.area(
        evol.to_pandas(),  # Plotly precisa de pandas internamente; conversão rápida
        x="COMPETÊNCIA_NORM", y="TOTAL",
        title="Evolução Mensal – Valor do Espelho",
        template=template,
    )
    fig_evol.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=GRAPH_HEIGHT)

    # Top 10 Secretarias
    top_sec = (
        df.groupby("SECRETARIA")
          .agg(pl.col("VALOR DO ESPELHO").sum().alias("TOTAL"))
          .sort("TOTAL", descending=True)
          .head(10)
    )
    fig_sec = px.bar(
        top_sec.to_pandas(),
        x="TOTAL", y="SECRETARIA", orientation="h",
        title="Top 10 Secretarias",
        template=template,
    )
    fig_sec.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=GRAPH_HEIGHT, yaxis=dict(automargin=True))

    # Top 10 Agências
    top_ag = (
        df.groupby("AGÊNCIA")
          .agg(pl.col("VALOR DO ESPELHO").sum().alias("TOTAL"))
          .sort("TOTAL", descending=True)
          .head(10)
    )
    fig_ag = px.bar(
        top_ag.to_pandas(),
        x="TOTAL", y="AGÊNCIA", orientation="h",
        title="Top 10 Agências",
        template=template,
    )
    fig_ag.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=GRAPH_HEIGHT, yaxis=dict(automargin=True))

    # Treemap Secretaria → Agência
    treemap_df = (
        df.groupby(["SECRETARIA", "AGÊNCIA"])
          .agg(pl.col("VALOR DO ESPELHO").sum().alias("TOTAL"))
          .sort("TOTAL", descending=True)
    ).to_pandas()
    fig_tree = px.treemap(
        treemap_df, path=["SECRETARIA", "AGÊNCIA"], values="TOTAL",
        title="Proporção por Secretaria → Agência",
        template=template,
    )
    fig_tree.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=GRAPH_HEIGHT)

    # Campanhas por valor (Pareto simples em barra)
    camp = (
        df.groupby("CAMPANHA")
          .agg(pl.col("VALOR DO ESPELHO").sum().alias("TOTAL"))
          .sort("TOTAL", descending=True)
          .head(20)
    ).to_pandas()
    fig_camp = px.bar(
        camp,
        x="TOTAL", y="CAMPANHA", orientation="h",
        title="Campanhas por Valor (Top 20)",
        template=template,
    )
    fig_camp.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=GRAPH_HEIGHT, yaxis=dict(automargin=True))

    return fig_evol, fig_sec, fig_ag, fig_tree, fig_camp

def _filter_df(df: pl.DataFrame, secretaria: list[str], agencia: list[str], campanha: list[str], d_start: str | None, d_end: str | None) -> pl.DataFrame:
    flt = df
    if secretaria:
        flt = flt.filter(pl.col("SECRETARIA").is_in(secretaria))
    if agencia:
        flt = flt.filter(pl.col("AGÊNCIA").is_in(agencia))
    if campanha:
        flt = flt.filter(pl.col("CAMPANHA").is_in(campanha))
    if d_start:
        try:
            ds = dtparser.parse(d_start, dayfirst=True)
            flt = flt.filter(pl.col("DATA DO EMPENHO_DT") >= ds)
        except Exception:
            pass
    if d_end:
        try:
            de = dtparser.parse(d_end, dayfirst=True)
            flt = flt.filter(pl.col("DATA DO EMPENHO_DT") <= de)
        except Exception:
            pass
    return flt

def _table_data(df: pl.DataFrame) -> tuple[list[dict], list[dict]]:
    # Formatar para DataTable com links e currency
    rows = []
    for rec in df.select([
        "CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","PROCESSO","EMPENHO","DATA DO EMPENHO_DT","COMPETÊNCIA_TXT","OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"
    ]).to_dicts():
        # Links
        def linkify(url: str, text: str) -> str:
            if url and url.strip().lower().startswith("http"):
                return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'
            return ""

        rows.append({
            "CAMPANHA": rec.get("CAMPANHA",""),
            "SECRETARIA": rec.get("SECRETARIA",""),
            "AGÊNCIA": rec.get("AGÊNCIA",""),
            "VALOR DO ESPELHO": _to_brl(rec.get("VALOR DO ESPELHO", 0)),
            "PROCESSO": linkify(rec.get("PROCESSO",""), "Processo"),
            "EMPENHO": linkify(rec.get("EMPENHO",""), "Empenho"),
            "DATA DO EMPENHO": rec.get("DATA DO EMPENHO_DT").strftime("%d/%m/%Y") if rec.get("DATA DO EMPENHO_DT") else "",
            "COMPETÊNCIA": rec.get("COMPETÊNCIA_TXT",""),
            "OBSERVAÇÃO": rec.get("OBSERVAÇÃO",""),
            "ESPELHO DIANA": linkify(rec.get("ESPELHO DIANA",""), "Diana"),
            "ESPELHO": linkify(rec.get("ESPELHO",""), "Espelho"),
            "PDF": linkify(rec.get("PDF",""), "PDF"),
        })

    columns = [
        {"name":"CAMPANHA","id":"CAMPANHA","presentation":"markdown"},
        {"name":"SECRETARIA","id":"SECRETARIA"},
        {"name":"AGÊNCIA","id":"AGÊNCIA"},
        {"name":"VALOR DO ESPELHO","id":"VALOR DO ESPELHO"},
        {"name":"PROCESSO","id":"PROCESSO","presentation":"markdown"},
        {"name":"EMPENHO","id":"EMPENHO","presentation":"markdown"},
        {"name":"DATA DO EMPENHO","id":"DATA DO EMPENHO"},
        {"name":"COMPETÊNCIA","id":"COMPETÊNCIA"},
        {"name":"OBSERVAÇÃO","id":"OBSERVAÇÃO"},
        {"name":"ESPELHO DIANA","id":"ESPELHO DIANA","presentation":"markdown"},
        {"name":"ESPELHO","id":"ESPELHO","presentation":"markdown"},
        {"name":"PDF","id":"PDF","presentation":"markdown"},
    ]
    return rows, columns


# -----------------------------
# App
# -----------------------------

external_scripts = []
external_stylesheets = []

app = Dash(__name__, external_scripts=external_scripts, external_stylesheets=external_stylesheets)
server = app.server
app.title = APP_TITLE

# CSS simples para layout com sidebar fixa
APP_CSS = html.Style("""
:root { --sidebar-w: 320px; }
* { box-sizing: border-box; }
body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }
.container { display: flex; min-height: 100vh; overflow: hidden; }
.sidebar {
  width: var(--sidebar-w);
  flex: 0 0 var(--sidebar-w);
  border-right: 1px solid #e6e6e6;
  padding: 16px;
  background: #fafafa;
}
.content {
  flex: 1 1 auto;
  min-width: 0;
  padding: 16px;
  overflow: auto;
}
.card {
  border: 1px solid #eee; border-radius: 12px; padding: 12px; margin-bottom: 16px;
  background: #fff;
  max-height: """ + str(CARD_MAX_HEIGHT) + """px; overflow: hidden;
}
.card h3 { margin: 0 0 6px 0; font-size: 16px; }
.graph-wrap { height: """ + str(GRAPH_HEIGHT) + """px; }
.kpi { display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 12px; }
.kpi .item { border: 1px dashed #e7e7e7; border-radius: 10px; padding: 10px; background:#fff; }
.row { display:grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.footer-space { height: 24px; }
.select { margin-bottom: 12px; }
.small { font-size: 12px; color:#666; }
.dark body, .dark .sidebar { background:#121212; color:#ddd; }
.dark .sidebar { border-right-color:#2a2a2a; }
.dark .content { background:#0c0c0c; }
.dark .card { background:#161616; border-color:#2a2a2a; }
""")

app.layout = html.Div([
    APP_CSS,
    dcc.Store(id="data-cache"),           # armazena registros filtrados (records)
    dcc.Store(id="raw-cache"),            # armazena dados crus da aba (records)
    dcc.Download(id="download-data"),     # para baixar CSV

    html.Div(className="container", children=[
        # ------------------ Sidebar ------------------
        html.Div(className="sidebar", children=[
            html.H3("Filtros"),
            html.Div(className="select", children=[
                html.Label("Aba (Planilha)"),
                dcc.Dropdown(
                    id="sel-aba",
                    options=TAB_OPTIONS,
                    value=DEFAULT_GID,
                    clearable=False,
                ),
                html.Span("Defina a variável GSHEET_TABS para listar mais abas (nome → gid).", className="small")
            ]),
            html.Div(className="select", children=[
                html.Label("Secretaria"),
                dcc.Dropdown(id="f-sec", options=[], multi=True, placeholder="Todas"),
            ]),
            html.Div(className="select", children=[
                html.Label("Agência"),
                dcc.Dropdown(id="f-ag", options=[], multi=True, placeholder="Todas"),
            ]),
            html.Div(className="select", children=[
                html.Label("Campanha"),
                dcc.Dropdown(id="f-camp", options=[], multi=True, placeholder="Todas"),
            ]),
            html.Div(className="select", children=[
                html.Label("Período (Data do Empenho)"),
                dcc.DatePickerRange(id="f-date"),
            ]),
            html.Div(style={"display":"flex","gap":"8px","marginTop":"12px"}, children=[
                html.Button("Atualizar dados", id="btn-refresh", n_clicks=0),
                html.Button("Baixar CSV", id="btn-download", n_clicks=0),
            ]),
            html.Hr(),
            html.Label("Tema"),
            dcc.RadioItems(
                id="theme",
                options=[{"label":"Claro","value":"light"},{"label":"Escuro","value":"dark"}],
                value=DEFAULT_THEME,  # claro por padrão
                inline=True,
            ),
        ]),

        # ------------------ Conteúdo ------------------
        html.Div(className="content", children=[
            html.H2(APP_TITLE),

            html.Div(className="kpi", children=[
                html.Div(className="item", children=[
                    html.Div("Total (filtro)"),
                    html.H3(id="kpi-total")
                ]),
                html.Div(className="item", children=[
                    html.Div("Qtd. Registros"),
                    html.H3(id="kpi-qtd")
                ]),
                html.Div(className="item", children=[
                    html.Div("Secretarias distintas"),
                    html.H3(id="kpi-sec")
                ]),
                html.Div(className="item", children=[
                    html.Div("Agências distintas"),
                    html.H3(id="kpi-ag")
                ]),
            ]),

            html.Div(className="row", children=[
                html.Div(className="card", children=[
                    html.Div(className="graph-wrap", children=[dcc.Graph(id="fig-evol")])
                ]),
                html.Div(className="card", children=[
                    html.Div(className="graph-wrap", children=[dcc.Graph(id="fig-tree")])
                ]),
            ]),
            html.Div className:="row", children=[
                html.Div(className="card", children=[
                    html.Div(className="graph-wrap", children=[dcc.Graph(id="fig-sec")])
                ]),
                html.Div(className="card", children=[
                    html.Div(className="graph-wrap", children=[dcc.Graph(id="fig-ag")])
                ]),
            ]),
            html.Div(className="card", children=[
                html.Div(className="graph-wrap", children=[dcc.Graph(id="fig-camp")])
            ]),

            html.Div(className="card", children=[
                html.H3("Tabela detalhada"),
                dash_table.DataTable(
                    id="tbl",
                    columns=[],
                    data=[],
                    page_size=12,
                    sort_action="native",
                    filter_action="native",
                    style_table={"overflowX":"auto","maxHeight": str(GRAPH_HEIGHT) + "px", "overflowY":"auto"},
                    style_cell={"whiteSpace":"normal","height":"auto","fontSize":"13px"},
                    style_header={"fontWeight":"bold"},
                    markdown_options={"link_target":"_blank"},
                    dangerously_allow_html=True,  # para tag <a> na coluna
                )
            ]),

            html.Div(className="footer-space"),
        ]),
    ])
])

# -----------------------------
# Callbacks
# -----------------------------

# Carregar/atualizar dados crus ao trocar aba ou clicar atualizar (e também no load inicial)
@app.callback(
    Output("raw-cache", "data"),
    Output("f-sec", "options"),
    Output("f-ag", "options"),
    Output("f-camp", "options"),
    Output("f-date", "min_date_allowed"),
    Output("f-date", "max_date_allowed"),
    Input("sel-aba", "value"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def load_data(selected_gid, n_clicks):
    gid = selected_gid or DEFAULT_GID
    try:
        df = _fetch_csv_for_gid(gid)
        df = _normalize_df(df)

        # opções filtros
        def opts(col):
            if col in df.columns:
                vals = [v for v in df[col].unique().to_list() if v and v != "None"]
                vals = sorted(vals, key=lambda x: str(x).lower())
                return [{"label": v, "value": v} for v in vals]
            return []

        sec_opts = opts("SECRETARIA")
        ag_opts  = opts("AGÊNCIA")
        camp_opts= opts("CAMPANHA")

        # datas
        dmin = df["DATA DO EMPENHO_DT"].drop_nulls().min() if "DATA DO EMPENHO_DT" in df.columns else None
        dmax = df["DATA DO EMPENHO_DT"].drop_nulls().max() if "DATA DO EMPENHO_DT" in df.columns else None
        dmin_s = dmin.strftime("%Y-%m-%d") if dmin else None
        dmax_s = dmax.strftime("%Y-%m-%d") if dmax else None

        # guardar como records (sem pandas)
        records = df.to_dicts()
        return records, sec_opts, ag_opts, camp_opts, dmin_s, dmax_s

    except Exception as e:
        # Falha ao baixar/parsear
        return [], [], [], [], None, None

# Aplicar filtros e gerar tudo
@app.callback(
    Output("data-cache", "data"),
    Output("kpi-total", "children"),
    Output("kpi-qtd", "children"),
    Output("kpi-sec", "children"),
    Output("kpi-ag", "children"),
    Output("fig-evol", "figure"),
    Output("fig-sec", "figure"),
    Output("fig-ag", "figure"),
    Output("fig-tree", "figure"),
    Output("fig-camp", "figure"),
    Output("tbl", "columns"),
    Output("tbl", "data"),
    Input("raw-cache", "data"),
    Input("f-sec", "value"),
    Input("f-ag", "value"),
    Input("f-camp", "value"),
    Input("f-date", "start_date"),
    Input("f-date", "end_date"),
    Input("theme", "value"),
)
def apply_filters(raw_records, secs, ags, camps, ds, de, theme):
    if not raw_records:
        # vazio
        empty_fig = go.Figure().update_layout(template=PLOT_TEMPLATES.get(theme, PLOT_TEMPLATES[DEFAULT_THEME]), height=GRAPH_HEIGHT)
        return [], "R$ 0,00", "0", "0", "0", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, [], []

    df = pl.DataFrame(raw_records)
    flt = _filter_df(df, secs or [], ags or [], camps or [], ds, de)

    total = flt["VALOR DO ESPELHO"].sum() if "VALOR DO ESPELHO" in flt.columns else 0
    qtd   = flt.height
    nsec  = flt["SECRETARIA"].n_unique() if "SECRETARIA" in flt.columns else 0
    nag   = flt["AGÊNCIA"].n_unique()    if "AGÊNCIA" in flt.columns else 0

    fig_evol, fig_sec, fig_ag, fig_tree, fig_camp = _make_figs(flt, theme)

    rows, columns = _table_data(flt)
    return (
        flt.to_dicts(),
        _to_brl(total),
        str(qtd),
        str(nsec),
        str(nag),
        fig_evol, fig_sec, fig_ag, fig_tree, fig_camp,
        columns, rows
    )

# Download CSV do conjunto filtrado
@app.callback(
    Output("download-data", "data"),
    Input("btn-download", "n_clicks"),
    State("data-cache", "data"),
    prevent_initial_call=True,
)
def download_data(n_clicks, cached):
    if not cached:
        return no_update
    df = pl.DataFrame(cached)
    # Ordena por competência e valor como padrão
    if "COMPETÊNCIA_NORM" in df.columns:
        df = df.sort(["COMPETÊNCIA_NORM", "VALOR DO ESPELHO"])
    csv_bytes = df.write_csv().encode("utf-8")
    fname = f"secom_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return dict(content=csv_bytes, filename=fname, type="text/csv")
    

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=False)
