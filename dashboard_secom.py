
import os
import io
import re
from datetime import datetime
import unicodedata
import requests
import numpy as np
import pandas as pd

import dash
from dash import html, dcc, dash_table, Input, Output, State, ctx
import plotly.express as px
import plotly.graph_objects as go

# ------------- Config ---------------------------------------------------------

DEFAULT_SHEET_URL = (
    os.environ.get(
        "EXCEL_URL",
        "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
    )
)

APP_TITLE = "SECOM • Dashboard de Processos"

# ------------- Helpers --------------------------------------------------------

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = _strip_accents(s)
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\n", " ")
    return s

def normalize_google_url(url: str) -> str:
    """
    Aceita links /edit#gid= ou /export?format=xlsx e normaliza para o formato export XLSX.
    """
    if not url:
        return DEFAULT_SHEET_URL
    url = url.strip()
    # Já está no formato export
    if "/export" in url and "format=xlsx" in url:
        return url
    # Converte /edit?gid=... ou /edit#gid=...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if m:
        file_id = m.group(1)
        return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx&id={file_id}"
    return url

def fetch_excel_bytes(url: str) -> bytes:
    """
    Baixa o arquivo Excel remoto. Lança exceção se falhar.
    """
    url = normalize_google_url(url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content

def list_sheets(url: str) -> list[str]:
    data = fetch_excel_bytes(url)
    with pd.ExcelFile(io.BytesIO(data)) as xl:
        return list(xl.sheet_names)

def _to_numeric_brl(x):
    """
    Converte 'R$ 1.234,56' -> 1234.56; aceita número já numérico.
    """
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x)
    s = s.replace("R$", "").replace(" ", "").replace(".", "").replace("\u00A0", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return np.nan

# mapeamento flexível de nomes de colunas
COLMAP = {
    "valor": [
        "valor do espelho",
        "valor espelho",
        "valor do  espelho",
        "valor",
        "valor_total",
        "total",
    ],
    "secretaria": ["secretaria", "sec", "orgao", "órgão"],
    "agencia": ["agencia", "agência", "fornecedor", "ag"],
    "campanha": ["campanha", "acao", "ação"],
    "processo": ["processo", "link processo", "url processo"],
    "empenho": ["empenho", "link empenho", "url empenho"],
    "obs": ["observacao", "observação", "obs", "descricao", "descrição"],
    "espelho_diana": ["espelho diana", "diana", "link diana"],
    "espelho": ["espelho", "link espelho"],
    "pdf": ["pdf", "link pdf"],
    "data_empenho": ["data do empenho", "data empenho", "empenho data"],
    "competencia": ["competencia", "competência", "mes competencia", "competencia (mes)"],
}

def _find_col(df: pd.DataFrame, keys: list[str]) -> str | None:
    cols_norm = {_norm(c): c for c in df.columns}
    for k in keys:
        nk = _norm(k)
        for cnorm, corig in cols_norm.items():
            if nk == cnorm:
                return corig
    # tenta contains
    for k in keys:
        nk = _norm(k)
        candidates = [orig for cn, orig in cols_norm.items() if nk in cn]
        if candidates:
            return candidates[0]
    return None

def load_sheet(url: str, sheet_name: str) -> pd.DataFrame:
    data = fetch_excel_bytes(url)
    with pd.ExcelFile(io.BytesIO(data)) as xl:
        if sheet_name is None or sheet_name not in xl.sheet_names:
            # pega a primeira
            sheet_name = xl.sheet_names[0]
        df = xl.parse(sheet_name=sheet_name, dtype=str)  # lê como texto para padronizar depois
    # remove colunas totalmente vazias
    df = df.dropna(axis=1, how="all")
    # tenta detectar colunas importantes
    cols = {}
    for key, aliases in COLMAP.items():
        col = _find_col(df, aliases)
        cols[key] = col

    # cria cópias padronizadas (tudo em upper sem acentos, mas preservamos originais para mostrar)
    out = pd.DataFrame()
    if cols["secretaria"]:
        out["SECRETARIA"] = df[cols["secretaria"]].fillna("").astype(str).str.strip()
    else:
        out["SECRETARIA"] = ""

    if cols["agencia"]:
        out["AGENCIA"] = df[cols["agencia"]].fillna("").astype(str).str.strip()
    else:
        out["AGENCIA"] = ""

    if cols["campanha"]:
        out["CAMPANHA"] = df[cols["campanha"]].fillna("").astype(str).str.strip()
    else:
        out["CAMPANHA"] = ""

    if cols["valor"] and cols["valor"] in df.columns:
        out["VALOR"] = df[cols["valor"]].apply(_to_numeric_brl).fillna(0.0)
    else:
        # tenta achar uma coluna que pareça número
        num_cols = []
        for c in df.columns:
            if df[c].dropna().shape[0] == 0:
                continue
            sample = str(df[c].dropna().iloc[0])
            if re.search(r"\d", sample):
                num_cols.append(c)
        out["VALOR"] = df[num_cols[0]].apply(_to_numeric_brl).fillna(0.0) if num_cols else 0.0

    # datas
    comp_txt = df[cols["competencia"]].astype(str) if cols["competencia"] else None
    data_emp = df[cols["data_empenho"]].astype(str) if cols["data_empenho"] else None

    def _parse_date(s):
        try:
            return pd.to_datetime(s, dayfirst=True, errors="coerce")
        except Exception:
            return pd.NaT

    out["DATA DO EMPENHO"] = _parse_date(data_emp) if data_emp is not None else pd.NaT

    # COMPETÊNCIA_DT primeiro dia do mês
    comp_dt = None
    if comp_txt is not None:
        # tenta 'MM/YYYY', 'YYYY-MM', 'YYYY/MM', 'mmm/YY'
        def to_month_start(x):
            x = str(x).strip()
            if not x or x.lower() in ("nan", "nat"):
                return pd.NaT
            # normaliza separador
            x2 = x.replace("\\", "/").replace("-", "/")
            # tenta dd/mm/yyyy
            m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", x2)
            if m:
                dd, mm, yy = m.groups()
                try:
                    dt = datetime(int(yy if len(yy)==4 else (2000+int(yy))), int(mm), 1)
                    return pd.Timestamp(dt)
                except Exception:
                    return pd.NaT
            # tenta mm/yyyy
            m = re.match(r"^(\d{1,2})/(\d{2,4})$", x2)
            if m:
                mm, yy = m.groups()
                try:
                    dt = datetime(int(yy if len(yy)==4 else (2000+int(yy))), int(mm), 1)
                    return pd.Timestamp(dt)
                except Exception:
                    return pd.NaT
            # tenta yyyy/mm
            m = re.match(r"^(\d{4})/(\d{1,2})$", x2)
            if m:
                yy, mm = m.groups()
                try:
                    dt = datetime(int(yy), int(mm), 1)
                    return pd.Timestamp(dt)
                except Exception:
                    return pd.NaT
            # tenta yyyy-mm
            try:
                dt = pd.to_datetime(x, format="%Y-%m", errors="coerce")
                if pd.notna(dt):
                    return pd.Timestamp(datetime(dt.year, dt.month, 1))
            except Exception:
                pass
            # fallback genérico
            dt = pd.to_datetime(x, dayfirst=True, errors="coerce")
            if pd.notna(dt):
                return pd.Timestamp(datetime(dt.year, dt.month, 1))
            return pd.NaT

        comp_dt = comp_txt.apply(to_month_start)
        out["COMPETENCIA"] = comp_txt.fillna("")
    else:
        out["COMPETENCIA"] = ""
        comp_dt = pd.Series(pd.NaT, index=out.index)

    # se nao tiver competencia, usa mês da data do empenho
    comp_dt = comp_dt.fillna(out["DATA DO EMPENHO"].dt.to_period("M").dt.to_timestamp())

    out["COMPETENCIA_DT"] = comp_dt
    out["COMPETENCIA_TXT"] = out["COMPETENCIA"].where(out["COMPETENCIA"]!="",
                                                       out["COMPETENCIA_DT"].dt.strftime("%Y-%m"))

    # links
    def _mk_link(col, text):
        if col and col in df.columns:
            s = df[col].fillna("")
            def mk(v):
                v = str(v).strip()
                if v.startswith("http"):
                    return f"[{text}]({v})"
                return ""
            return s.apply(mk)
        return ""
    out["PROCESSO"] = _mk_link(cols["processo"], "Processo")
    out["EMPENHO"] = _mk_link(cols["empenho"], "Empenho")
    out["ESPELHO DIANA"] = _mk_link(cols["espelho_diana"], "Diana")
    out["ESPELHO"] = _mk_link(cols["espelho"], "Espelho")
    out["PDF"] = _mk_link(cols["pdf"], "PDF")
    out["OBSERVACAO"] = df[cols["obs"]].fillna("").astype(str) if cols["obs"] else ""

    # garante dtypes
    out["VALOR"] = pd.to_numeric(out["VALOR"], errors="coerce").fillna(0.0)
    if "DATA DO EMPENHO" in out.columns:
        try:
            out["DATA DO EMPENHO"] = pd.to_datetime(out["DATA DO EMPENHO"], errors="coerce")
        except Exception:
            pass

    # limpa linhas totalmente vazias (sem secretaria, agencia, campanha e valor 0)
    mask_any = (out[["SECRETARIA","AGENCIA","CAMPANHA"]].astype(str).agg("".join, axis=1).str.len() > 0) | (out["VALOR"]!=0)
    out = out[mask_any].reset_index(drop=True)
    return out

# -------------------- Dash ----------------------------------------------------

external_scripts = []
external_stylesheets = [
    # fonte e reset básico
    "https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.min.css",
]

app = dash.Dash(__name__, title=APP_TITLE, external_scripts=external_scripts, external_stylesheets=external_stylesheets)
server = app.server

# Tema por CSS variável: claro é padrão
THEME_CSS = """
:root{
  --bg: #0b1220;
  --card:#0f172a;
  --text:#e2e8f0;
  --muted:#94a3b8;
  --accent:#4f46e5;
  --grid:#1e293b;
  --table:#0f172a;
}
.light{
  --bg: #f7fafc;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#475569;
  --accent:#4338ca;
  --grid:#e2e8f0;
  --table:#ffffff;
}
body{background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, 'Helvetica Neue', Arial, 'Apple Color Emoji','Segoe UI Emoji','Segoe UI Symbol';}
.app-container{padding:16px; max-width: 1400px; margin: 0 auto;}
.hstack{display:flex; gap:12px; align-items:center; flex-wrap:wrap}
.controls{display:grid; grid-template-columns: repeat(5, 1fr) 380px; gap:12px;}
.card{background: var(--card); border:1px solid var(--grid); border-radius:12px; padding:12px;}
.kpi{display:flex; flex-direction:column; gap:6px;}
.kpi .label{color:var(--muted); font-size:.85rem}
.kpi .value{font-size:1.3rem; font-weight:700}
.section-title{margin:12px 0 8px; font-weight:700}
.dash-table-container .dash-table{background:var(--table)}
a{color:var(--accent)}
"""

app.index_string = f"""
<!DOCTYPE html>
<html>
<head>
    {{%metas%}}
    <title>{APP_TITLE}</title>
    {{%favicon%}}
    {{%css%}}
    <style>{THEME_CSS}</style>
</head>
<body class="light">
    <div id="react-entry-point">{{%app_entry%}}</div>
    <footer>{{%config%}}{{%scripts%}}</footer>
</body>
</html>
"""

def px_template(theme: str):
    gridcolor = "rgba(148,163,184,.25)" if theme=="light" else "rgba(148,163,184,.18)"
    paper_bg = "rgba(0,0,0,0)"
    plot_bg = "rgba(0,0,0,0)"
    font_color = "#0f172a" if theme=="light" else "#e2e8f0"
    template = dict(
        layout={
            "paper_bgcolor": paper_bg,
            "plot_bgcolor": plot_bg,
            "font": {"color": font_color},
            "xaxis": {"gridcolor": gridcolor},
            "yaxis": {"gridcolor": gridcolor},
            "legend": {"orientation":"h", "y": -0.2},
            "margin": dict(l=30,r=20,t=40,b=60)
        }
    )
    return template

# Stores
app.layout = html.Div(
    className="app-container",
    children=[
        dcc.Store(id="store-data"),
        dcc.Store(id="store-theme", data="light"),
        dcc.Store(id="store-sheets", data=[]),

        html.Div(className="hstack", children=[
            html.H2(APP_TITLE, style={"margin":"0"}),
            html.Div(style={"marginLeft":"auto","display":"flex","alignItems":"center","gap":"8px"}, children=[
                html.Span("Tema:"),
                dcc.RadioItems(
                    id="theme",
                    options=[{"label":"Claro","value":"light"},{"label":"Escuro","value":"dark"}],
                    value="light",  # padrão: claro
                    inline=True
                ),
                html.Button("Atualizar dados", id="btn-refresh", n_clicks=0, className="card")
            ]),
        ]),
        html.Small("Dados dinâmicos via Google Sheets", style={"color":"var(--muted)"}),
        html.Div(className="controls", children=[
            dcc.Dropdown(id="sheet-name", placeholder="Escolha a aba...", options=[]),
            dcc.Dropdown(id="f-secretaria", placeholder="Selecione...", multi=True),
            dcc.Dropdown(id="f-agencia", placeholder="Selecione...", multi=True),
            dcc.Dropdown(id="f-campanha", placeholder="Selecione...", multi=True),
            dcc.Dropdown(id="f-competencia", placeholder="Selecione...", multi=True),
            dcc.Input(id="sheet-url", type="text", debounce=True, value=DEFAULT_SHEET_URL),
        ]),

        html.Div(className="hstack", style={"marginTop":"12px"}, children=[
            html.Div(className="card kpi", style={"flex":"1"}, children=[
                html.Div("Total (Valor do Espelho)", className="label"),
                html.Div(id="kpi-total", className="value")
            ]),
            html.Div(className="card kpi", style={"flex":"1"}, children=[
                html.Div("Qtd. de linhas", className="label"),
                html.Div(id="kpi-rows", className="value")
            ]),
            html.Div(className="card kpi", style={"flex":"1"}, children=[
                html.Div("Mediana por linha", className="label"),
                html.Div(id="kpi-mediana", className="value")
            ]),
            html.Div(className="card kpi", style={"flex":"1"}, children=[
                html.Div("Processos distintos", className="label"),
                html.Div(id="kpi-proc", className="value")
            ]),
        ]),

        html.Div(className="hstack", children=[
            html.Div(style={"flex":"1"}, className="card", children=[
                html.Div("Evolução mensal", className="section-title"),
                dcc.Graph(id="g-evolucao")
            ]),
            html.Div(style={"flex":"1"}, className="card", children=[
                html.Div("Top 10 Secretarias", className="section-title"),
                dcc.Graph(id="g-top-secretarias")
            ]),
        ]),

        html.Div(className="hstack", children=[
            html.Div(style={"flex":"1"}, className="card", children=[
                html.Div("Top 10 Agências", className="section-title"),
                dcc.Graph(id="g-top-agencias")
            ]),
            html.Div(style={"flex":"1"}, className="card", children=[
                html.Div("Treemap Secretaria → Agência", className="section-title"),
                dcc.Graph(id="g-treemap")
            ]),
        ]),

        html.Div(className="card", children=[
            html.Div("Campanhas por valor (Pareto)", className="section-title"),
            dcc.Graph(id="g-campanhas")
        ]),

        html.Div(className="card", children=[
            html.Div("Dados detalhados", className="section-title"),
            dash_table.DataTable(
                id="tbl",
                page_size=15,
                filter_action="native",
                sort_action="native",
                sort_mode="multi",
                style_table={"overflowX":"auto"},
                style_cell={"padding":"8px",'backgroundColor':'var(--table)','color':'var(--text)'},
                style_header={'backgroundColor':'var(--grid)','color':'var(--text)','fontWeight':'bold'},
                markdown_options={"link_target":"_blank"},
                row_selectable=False,
                page_action="native",
            )
        ]),

        html.Div(id="error", style={"color":"#ef4444","marginTop":"8px"})
    ]
)

# ---------------------- Callbacks --------------------------------------------

@app.callback(
    Output("store-sheets","data"),
    Output("sheet-name","options"),
    Output("sheet-name","value"),
    Output("error","children"),
    Input("btn-refresh","n_clicks"),
    Input("sheet-url","value"),
    prevent_initial_call=False,
)
def update_sheet_list(n_clicks, url):
    try:
        u = normalize_google_url(url or DEFAULT_SHEET_URL)
        sheets = list_sheets(u)
        opts = [{"label": s, "value": s} for s in sheets]
        value = sheets[0] if sheets else None
        return sheets, opts, value, ""
    except Exception as e:
        return [], [], None, f"Erro ao listar abas: {e}"

@app.callback(
    Output("store-data","data"),
    Output("f-secretaria","options"),
    Output("f-agencia","options"),
    Output("f-campanha","options"),
    Output("f-competencia","options"),
    Output("error","children"),
    Input("sheet-name","value"),
    Input("btn-refresh","n_clicks"),
    State("sheet-url","value"),
    prevent_initial_call=False,
)
def load_data(sheet_name, n_clicks, url):
    if not sheet_name:
        return None, [], [], [], [], ""
    try:
        df = load_sheet(url or DEFAULT_SHEET_URL, sheet_name)
        # opções
        sec_opts = [{"label": s, "value": s} for s in sorted([x for x in df["SECRETARIA"].unique() if x])]
        age_opts = [{"label": s, "value": s} for s in sorted([x for x in df["AGENCIA"].unique() if x])]
        cam_opts = [{"label": s, "value": s} for s in sorted([x for x in df["CAMPANHA"].unique() if x])]
        comp_opts = [{"label": s, "value": s} for s in sorted([x for x in df["COMPETENCIA_TXT"].fillna("").unique() if x])]
        return df.to_dict("records"), sec_opts, age_opts, cam_opts, comp_opts, ""
    except Exception as e:
        return None, [], [], [], [], f"Erro ao carregar dados: {e}"

def _filter_df(records, sec, age, cam, comp):
    if not records:
        return pd.DataFrame(columns=["SECRETARIA","AGENCIA","CAMPANHA","VALOR","DATA DO EMPENHO","COMPETENCIA_DT","COMPETENCIA_TXT","PROCESSO","EMPENHO","ESPELHO DIANA","ESPELHO","PDF","OBSERVACAO"])
    df = pd.DataFrame.from_records(records)
    if sec:
        df = df[df["SECRETARIA"].isin(sec)]
    if age:
        df = df[df["AGENCIA"].isin(age)]
    if cam:
        df = df[df["CAMPANHA"].isin(cam)]
    if comp:
        df = df[df["COMPETENCIA_TXT"].isin(comp)]
    return df

def brl(x):
    try:
        return "R$ {:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

@app.callback(
    Output("kpi-total","children"),
    Output("kpi-rows","children"),
    Output("kpi-mediana","children"),
    Output("kpi-proc","children"),
    Output("g-evolucao","figure"),
    Output("g-top-secretarias","figure"),
    Output("g-top-agencias","figure"),
    Output("g-treemap","figure"),
    Output("g-campanhas","figure"),
    Output("tbl","columns"),
    Output("tbl","data"),
    Output("error","children"),
    Input("store-data","data"),
    Input("f-secretaria","value"),
    Input("f-agencia","value"),
    Input("f-campanha","value"),
    Input("f-competencia","value"),
    Input("theme","value"),
)
def redraw(records, sec, age, cam, comp, theme):
    try:
        df = _filter_df(records, sec, age, cam, comp)
        template = px_template(theme or "light")

        # KPIs
        total = brl(df["VALOR"].sum()) if not df.empty else "R$ 0,00"
        rows = f"{len(df):,}".replace(",", ".")
        med = brl(df["VALOR"].median()) if not df.empty else "R$ 0,00"
        processos_distintos = df["PROCESSO"].replace("", np.nan).dropna().nunique() if "PROCESSO" in df else 0

        # Evolução mensal
        if not df.empty and "COMPETENCIA_DT" in df:
            m = df.groupby("COMPETENCIA_DT", dropna=True)["VALOR"].sum().reset_index()
            m = m.sort_values("COMPETENCIA_DT")
            fig1 = px.area(m, x="COMPETENCIA_DT", y="VALOR")
            fig1.update_traces(mode="lines+markers")
            fig1.update_layout(template=template, yaxis_title="Valor", xaxis_title="Competência")
        else:
            fig1 = go.Figure().update_layout(template=template)

        # Top 10 Secretarias
        if not df.empty:
            s = df.groupby("SECRETARIA")["VALOR"].sum().nlargest(10).sort_values(ascending=True)
            fig2 = px.bar(s, x=s.values, y=s.index, orientation="h")
            fig2.update_layout(template=template, xaxis_title="Valor", yaxis_title=None)
        else:
            fig2 = go.Figure().update_layout(template=template)

        # Top 10 Agências
        if not df.empty:
            a = df.groupby("AGENCIA")["VALOR"].sum().nlargest(10).sort_values(ascending=True)
            fig3 = px.bar(a, x=a.values, y=a.index, orientation="h")
            fig3.update_layout(template=template, xaxis_title="Valor", yaxis_title=None)
        else:
            fig3 = go.Figure().update_layout(template=template)

        # Treemap
        if not df.empty:
            t = df.groupby(["SECRETARIA","AGENCIA"], dropna=False)["VALOR"].sum().reset_index()
            fig4 = px.treemap(t, path=["SECRETARIA","AGENCIA"], values="VALOR")
            fig4.update_layout(template=template)
        else:
            fig4 = go.Figure().update_layout(template=template)

        # Campanhas Pareto
        if not df.empty:
            c = df.groupby("CAMPANHA")["VALOR"].sum().sort_values(ascending=False).head(20).reset_index()
            c["acum"] = c["VALOR"].cumsum()/c["VALOR"].sum()*100.0
            fig5 = go.Figure()
            fig5.add_bar(x=c["CAMPANHA"], y=c["VALOR"], name="Valor")
            fig5.add_scatter(x=c["CAMPANHA"], y=c["acum"], name="% acumulado", yaxis="y2", mode="lines+markers")
            fig5.update_layout(
                template=template,
                yaxis=dict(title="Valor"),
                yaxis2=dict(overlaying="y", side="right", title="%"),
                margin=dict(l=30,r=40,t=40,b=80),
            )
        else:
            fig5 = go.Figure().update_layout(template=template)

        # Tabela
        if not df.empty:
            show_cols = [
                "CAMPANHA","SECRETARIA","AGENCIA","VALOR",
                "PROCESSO","EMPENHO","DATA DO EMPENHO","COMPETENCIA_TXT",
                "OBSERVACAO","ESPELHO DIANA","ESPELHO","PDF"
            ]
            existing = [c for c in show_cols if c in df.columns]
            dt_cols = []
            for c in existing:
                if c=="VALOR":
                    dt_cols.append({"name":"VALOR DO ESPELHO", "id":c, "type":"numeric", "format": dict(locale="pt-BR", nully="R$ 0,00", spec=",.2f")})
                elif c in ("PROCESSO","EMPENHO","ESPELHO DIANA","ESPELHO","PDF"):
                    dt_cols.append({"name":c, "id":c, "presentation":"markdown"})
                else:
                    dt_cols.append({"name":c, "id":c})
            data = df.copy()
            # formata data
            if "DATA DO EMPENHO" in data:
                data["DATA DO EMPENHO"] = pd.to_datetime(data["DATA DO EMPENHO"], errors="coerce").dt.strftime("%d/%m/%Y")
            # valor em número (datatable cuida do formato), mas garantimos números
            data["VALOR"] = pd.to_numeric(data["VALOR"], errors="coerce").fillna(0.0)
            data = data[existing].to_dict("records")
        else:
            dt_cols, data = [], []

        return total, rows, med, str(processos_distintos), fig1, fig2, fig3, fig4, fig5, dt_cols, data, ""
    except Exception as e:
        return "R$ 0,00","0","R$ 0,00","0", go.Figure(),go.Figure(),go.Figure(),go.Figure(),go.Figure(),[],[], f"Erro ao desenhar: {e}"

# Tema: troca a classe do <body> via clientside.
# Como o Dash 3 não expõe body facilmente, aplicamos via clientside callback no document.documentElement
app.clientside_callback(
    """
    function(value){
        try{
            const body = document.querySelector('body');
            if(!body) return "";
            body.classList.remove('light','dark');
            body.classList.add(value || 'light');
        }catch(e){}
        return "";
    }
    """,
    Output("error","children"),
    Input("theme","value"),
    prevent_initial_call=False
)

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False)
