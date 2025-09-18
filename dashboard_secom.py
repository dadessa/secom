import os
import io
import json
import requests
import pandas as pd
from datetime import datetime
from dash import Dash, html, dcc, Output, Input, State, dash_table
import plotly.express as px

# ========= Config =========
EXCEL_URL = os.environ.get("EXCEL_URL", "").strip()

app = Dash(__name__)
server = app.server  # para gunicorn

# ========= Helpers =========
def _fetch_excel(url: str) -> pd.ExcelFile:
    if not url:
        raise ValueError("EXCEL_URL não definido.")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return pd.ExcelFile(io.BytesIO(r.content))

def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    # Padroniza colunas esperadas (ajuste nomes conforme sua planilha real)
    # Tenta detectar/renomear variações comuns
    rename_map = {
        "COMPETÊNCIA_DT": "COMPETÊNCIA_DT",
        "COMPETÊNCIA_TXT": "COMPETÊNCIA_TXT",
        "VALOR DO ESPELHO": "VALOR DO ESPELHO",
        "SECRETARIA": "SECRETARIA",
        "AGÊNCIA": "AGÊNCIA",
        "CAMPANHA": "CAMPANHA",
        "PROCESSO": "PROCESSO",
        "EMPENHO": "EMPENHO",
        "DATA DO EMPENHO": "DATA DO EMPENHO",
        "OBSERVAÇÃO": "OBSERVAÇÃO",
        "ESPELHO DIANA": "ESPELHO DIANA",
        "ESPELHO": "ESPELHO",
        "PDF": "PDF",
    }
    # Normaliza colunas para maiúsculas sem acento (aproximação simples)
    df.columns = [c.strip() for c in df.columns]
    # Aplica renomeação somente onde existir
    for k, v in list(rename_map.items()):
        if k in df.columns:
            rename_map[k] = v
        else:
            # tenta variações simples
            cand = [c for c in df.columns if c.lower().replace(" ", "") == k.lower().replace(" ", "")]
            if cand:
                rename_map[cand[0]] = v
    df = df.rename(columns=rename_map)

    # Conversões
    if "VALOR DO ESPELHO" in df.columns:
        df["VALOR DO ESPELHO"] = pd.to_numeric(df["VALOR DO ESPELHO"], errors="coerce").fillna(0.0)

    # Datas
    for col in ["COMPETÊNCIA_DT", "DATA DO EMPENHO"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    # Competência textual derivada, se não existir
    if "COMPETÊNCIA_TXT" not in df.columns:
        if "COMPETÊNCIA_DT" in df.columns:
            df["COMPETÊNCIA_TXT"] = df["COMPETÊNCIA_DT"].dt.strftime("%Y-%m")
        else:
            # tenta deduzir de algum texto existente
            df["COMPETÊNCIA_TXT"] = ""

    # Campos de texto
    for c in ["SECRETARIA", "AGÊNCIA", "CAMPANHA", "OBSERVAÇÃO"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    # Links
    for c in ["PROCESSO", "EMPENHO", "ESPELHO DIANA", "ESPELHO", "PDF"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    return df.fillna("")

def _df_to_table(df: pd.DataFrame) -> dash_table.DataTable:
    # Monta colunas com links clicáveis
    cols = []
    def linkify(col):
        return {
            "name": col,
            "id": col,
            "presentation": "markdown"
        }

    for c in df.columns:
        if c in ["PROCESSO", "EMPENHO", "ESPELHO DIANA", "ESPELHO", "PDF"]:
            cols.append(linkify(c))
        else:
            cols.append({"name": c, "id": c})

    # Converte colunas de link para markdown clicável
    df_md = df.copy()
    for c in ["PROCESSO", "EMPENHO", "ESPELHO DIANA", "ESPELHO", "PDF"]:
        if c in df_md.columns:
            df_md[c] = df_md[c].apply(lambda u: f"[{c.split()[0].title()}]({u})" if isinstance(u, str) and u.startswith("http") else "")

    # Formatação BRL
    if "VALOR DO ESPELHO" in df_md.columns:
        df_md["VALOR DO ESPELHO"] = df_md["VALOR DO ESPELHO"].apply(
            lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if pd.notnull(x) and x != "" else ""
        )

    # Datas amigáveis
    for c in ["DATA DO EMPENHO"]:
        if c in df_md.columns:
            df_md[c] = pd.to_datetime(df_md[c], errors="coerce").dt.strftime("%d/%m/%Y")

    return dash_table.DataTable(
        data=df_md.to_dict("records"),
        columns=cols,
        page_size=20,
        style_table={"overflowX": "auto", "maxHeight": "calc(100vh - 280px)", "overflowY": "auto"},
        style_cell={"fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial", "fontSize": 14, "whiteSpace": "normal", "height": "auto"},
        markdown_options={"link_target": "_blank"},
    )

# ========= Layout (sidebar + conteúdo) =========
app.layout = html.Div(
    style={
        "display": "flex",
        "height": "100vh",
        "background": "#fafafa",  # tema claro padrão
        "color": "#111",
        "fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial"
    },
    children=[
        # Sidebar
        html.Div(
            id="sidebar",
            style={
                "flex": "0 0 320px",
                "borderRight": "1px solid #e5e5e5",
                "padding": "16px",
                "background": "#fff",
                "overflowY": "auto"
            },
            children=[
                html.H3("Filtros", style={"marginTop": 0, "marginBottom": 16}),
                html.Div([
                    html.Label("Aba da planilha"),
                    dcc.Dropdown(id="sheet", placeholder="Selecione a aba…"),
                ], style={"marginBottom": 12}),
                html.Div([
                    html.Label("Secretaria"),
                    dcc.Dropdown(id="f_secretaria", multi=True, placeholder="Selecione…"),
                ], style={"marginBottom": 12}),
                html.Div([
                    html.Label("Agência"),
                    dcc.Dropdown(id="f_agencia", multi=True, placeholder="Selecione…"),
                ], style={"marginBottom": 12}),
                html.Div([
                    html.Label("Competência (texto)"),
                    dcc.Dropdown(id="f_competencia", multi=True, placeholder="Ex.: 2025-01"),
                ], style={"marginBottom": 12}),
                html.Div([
                    html.Button("Atualizar dados", id="btn-refresh", n_clicks=0, style={"width": "100%", "padding": "10px", "background": "#111", "color": "#fff", "border": "none", "borderRadius": "8px", "cursor": "pointer"})
                ]),
                html.Hr(),
                html.Small([
                    html.Div("Fonte: EXCEL_URL (env var)", style={"opacity": 0.7}),
                ])
            ],
        ),

        # Conteúdo
        html.Div(
            id="content",
            style={"flex": "1", "minWidth": 0, "padding": "16px", "overflow": "auto"},
            children=[
                html.H2("Dashboard SECOM", style={"marginTop": 0}),
                html.Div(id="cards", style={"display": "grid", "gridTemplateColumns": "repeat(3, minmax(220px, 1fr))", "gap": "12px", "marginBottom": "12px"}),
                html.Div([
                    dcc.Graph(id="evolucao_mensal"),
                ], style={"marginBottom": 12}),
                html.Div([
                    dcc.Graph(id="top10_secretarias"),
                ], style={"marginBottom": 12}),
                html.Div([
                    dcc.Graph(id="top10_agencias"),
                ], style={"marginBottom": 12}),
                html.Div([
                    dcc.Graph(id="treemap_hierarquico"),
                ], style={"marginBottom": 12}),
                html.Div([
                    dcc.Graph(id="campanhas_valor"),
                ], style={"marginBottom": 12}),
                html.H3("Dados detalhados"),
                html.Div(id="tabela_detalhada"),
                dcc.Store(id="df-store"),
                dcc.Store(id="sheets-store"),
            ],
        )
    ]
)

# ========= Callbacks =========
@app.callback(
    Output("sheets-store", "data"),
    Output("sheet", "options"),
    Output("sheet", "value"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def load_sheets(_):
    # carrega lista de abas
    try:
        xl = _fetch_excel(EXCEL_URL)
        sheets = xl.sheet_names
    except Exception as e:
        sheets = []
    options = [{"label": s, "value": s} for s in sheets]
    default = sheets[0] if sheets else None
    return json.dumps(sheets), options, default

@app.callback(
    Output("df-store", "data"),
    Input("sheet", "value"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def load_data(sheet, _):
    if not sheet:
        return json.dumps({"columns": [], "data": []})
    try:
        xl = _fetch_excel(EXCEL_URL)
        df = xl.parse(sheet_name=sheet, dtype=str)  # lê tudo como texto primeiro
        # tenta converter numérico e datas no _clean_df
        df = _clean_df(df)
        return df.to_json(date_format="iso", orient="split")
    except Exception as e:
        # retorna vazio
        return json.dumps({"columns": [], "data": []})

@app.callback(
    Output("f_secretaria", "options"),
    Output("f_agencia", "options"),
    Output("f_competencia", "options"),
    Input("df-store", "data"),
)
def update_filter_options(df_json):
    try:
        df = pd.read_json(df_json, orient="split")
    except Exception:
        df = pd.DataFrame()
    def opts(col):
        if col in df.columns:
            vals = sorted({v for v in df[col].astype(str).fillna("") if v})
            return [{"label": v, "value": v} for v in vals]
        return []
    return opts("SECRETARIA"), opts("AGÊNCIA"), opts("COMPETÊNCIA_TXT")

def _apply_filters(df, secretarias, agencias, competencias):
    if df.empty:
        return df
    if secretarias:
        df = df[df["SECRETARIA"].isin(secretarias)]
    if agencias:
        df = df[df["AGÊNCIA"].isin(agencias)]
    if competencias:
        df = df[df["COMPETÊNCIA_TXT"].isin(competencias)]
    return df

@app.callback(
    Output("cards", "children"),
    Output("evolucao_mensal", "figure"),
    Output("top10_secretarias", "figure"),
    Output("top10_agencias", "figure"),
    Output("treemap_hierarquico", "figure"),
    Output("campanhas_valor", "figure"),
    Output("tabela_detalhada", "children"),
    Input("df-store", "data"),
    Input("f_secretaria", "value"),
    Input("f_agencia", "value"),
    Input("f_competencia", "value"),
)
def update_outputs(df_json, f_sec, f_age, f_comp):
    try:
        df = pd.read_json(df_json, orient="split")
    except Exception:
        df = pd.DataFrame()

    df = _apply_filters(
        df,
        f_sec if f_sec else [],
        f_age if f_age else [],
        f_comp if f_comp else [],
    )

    # KPIs
    total_valor = float(df["VALOR DO ESPELHO"].sum()) if "VALOR DO ESPELHO" in df else 0.0
    n_linhas = len(df)
    n_campanhas = df["CAMPANHA"].nunique() if "CAMPANHA" in df else 0

    kpi = lambda t, v: html.Div(
        style={"background": "#fff", "border": "1px solid #eee", "borderRadius": "12px", "padding": "16px"},
        children=[html.Div(t, style={"opacity": 0.7}), html.H3(v, style={"margin": 0})]
    )

    cards = [
        kpi("Total (VALOR DO ESPELHO)", f"R$ {total_valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        kpi("Registros", f"{n_linhas:,}".replace(",", ".")),
        kpi("Campanhas distintas", f"{n_campanhas:,}".replace(",", ".")),
    ]

    # Gráficos
    def fig_empty(title):
        return px.scatter(title=title)  # vazio

    # Evolução mensal
    if "VALOR DO ESPELHO" in df.columns:
        base = df.copy()
        if "COMPETÊNCIA_DT" in base.columns and pd.api.types.is_datetime64_any_dtype(base["COMPETÊNCIA_DT"]):
            gb = base.groupby(base["COMPETÊNCIA_DT"].dt.to_period("M"))["VALOR DO ESPELHO"].sum().sort_index()
            evo = gb.reset_index()
            evo["COMPETÊNCIA"] = evo["COMPETÊNCIA_DT"].astype(str)
        else:
            gb = base.groupby("COMPETÊNCIA_TXT")["VALOR DO ESPELHO"].sum()
            evo = gb.reset_index().rename(columns={"COMPETÊNCIA_TXT": "COMPETÊNCIA"})

        fig_evo = px.area(evo, x="COMPETÊNCIA", y="VALOR DO ESPELHO", title="Evolução mensal (soma VALOR DO ESPELHO)")
    else:
        fig_evo = fig_empty("Evolução mensal")

    # Top 10 Secretarias
    if all(c in df.columns for c in ["SECRETARIA", "VALOR DO ESPELHO"]):
        s = df.groupby("SECRETARIA")["VALOR DO ESPELHO"].sum().nlargest(10).sort_values(ascending=True)
        fig_sec = px.bar(s, x=s.values, y=s.index, orientation="h", title="Top 10 Secretarias (por valor)")
    else:
        fig_sec = fig_empty("Top 10 Secretarias")

    # Top 10 Agências
    if all(c in df.columns for c in ["AGÊNCIA", "VALOR DO ESPELHO"]):
        a = df.groupby("AGÊNCIA")["VALOR DO ESPELHO"].sum().nlargest(10).sort_values(ascending=True)
        fig_age = px.bar(a, x=a.values, y=a.index, orientation="h", title="Top 10 Agências (por valor)")
    else:
        fig_age = fig_empty("Top 10 Agências")

    # Treemap Secretaria -> Agência
    if all(c in df.columns for c in ["SECRETARIA", "AGÊNCIA", "VALOR DO ESPELHO"]):
        treemap = df.groupby(["SECRETARIA", "AGÊNCIA"])["VALOR DO ESPELHO"].sum().reset_index()
        fig_tree = px.treemap(treemap, path=["SECRETARIA", "AGÊNCIA"], values="VALOR DO ESPELHO", title="Treemap Secretaria → Agência")
    else:
        fig_tree = fig_empty("Treemap")

    # Campanhas por valor (Top)
    if all(c in df.columns for c in ["CAMPANHA", "VALOR DO ESPELHO"]):
        c = df.groupby("CAMPANHA")["VALOR DO ESPELHO"].sum().nlargest(15).sort_values(ascending=True)
        fig_camp = px.bar(c, x=c.values, y=c.index, orientation="h", title="Campanhas por valor (Top)")
    else:
        fig_camp = fig_empty("Campanhas por valor")

    # Tabela detalhada
    shown_cols = [c for c in [
        "CAMPANHA", "SECRETARIA", "AGÊNCIA", "VALOR DO ESPELHO",
        "PROCESSO", "EMPENHO", "DATA DO EMPENHO", "COMPETÊNCIA_TXT",
        "OBSERVAÇÃO", "ESPELHO DIANA", "ESPELHO", "PDF"
    ] if c in df.columns]
    tbl = _df_to_table(df[shown_cols]) if shown_cols else html.Div("Sem colunas esperadas para montar a tabela.", style={"opacity": 0.7})

    # Ajustes de tamanho responsivo (evita “expansão infinita”)
    for f in [fig_evo, fig_sec, fig_age, fig_tree, fig_camp]:
        f.update_layout(margin=dict(l=20, r=20, t=50, b=20), height=420, autosize=True)

    return cards, fig_evo, fig_sec, fig_age, fig_tree, fig_camp, tbl

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
