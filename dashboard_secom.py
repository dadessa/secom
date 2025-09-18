# dashboard_secom.py
# -----------------------------------------------------------
# SECOM – Dashboard de Processos (Dash)
# Lê uma planilha Google Sheets (XLSX) via URL em EXCEL_URL,
# permite escolher a ABA, aplicar filtros e gera os gráficos
# solicitados + tabela detalhada.
# -----------------------------------------------------------

import os
import io
import time
import base64
import requests
import pandas as pd

from dash import Dash, dcc, html, dash_table, Input, Output, State
import plotly.express as px

# ---------------------- Configuração -----------------------

EXCEL_URL = os.getenv("EXCEL_URL", "").strip()

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Dash-SECOM/1.0"
}

GRAPH_HEIGHT = 380  # px, limita altura e evita "expandir infinito"

# ---------------------- Utilitários ------------------------


def _assert_url_ok(url: str):
    if not url or "export?format=xlsx" not in url:
        raise ValueError(
            "EXCEL_URL inválida. Use a URL de export do Google Sheets, ex.: "
            "https://docs.google.com/spreadsheets/d/<ID>/export?format=xlsx&id=<ID>"
        )


def download_excel_bytes(url: str, retries: int = 2, timeout: int = 25) -> bytes:
    """Baixa o XLSX do Google Sheets. Tenta algumas vezes; verifica Content-Type."""
    _assert_url_ok(url)
    last_err = None
    for _ in range(retries + 1):
        try:
            sep = "&" if "?" in url else "?"
            bust = f"{sep}_ts={int(time.time())}"
            r = requests.get(url + bust, headers=REQ_HEADERS, timeout=timeout)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            if "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" not in ctype:
                raise RuntimeError(
                    "Download não retornou XLSX (verifique se a planilha está pública para leitura)."
                )
            return r.content
        except Exception as e:
            last_err = e
            time.sleep(1.2)
    raise RuntimeError(f"Falha ao baixar planilha: {last_err}")


def list_sheets(xlsx_bytes: bytes) -> list[str]:
    with pd.ExcelFile(io.BytesIO(xlsx_bytes)) as xl:
        return xl.sheet_names


def load_sheet_df(xlsx_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    """Carrega a aba selecionada e normaliza colunas e tipos."""
    df = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=sheet_name, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # Mapeia possíveis nomes de colunas → padrão usado no dashboard
    aliases = {
        "VALOR DO ESPELHO": ["VALOR DO ESPELHO", "VALOR_ESPELHO", "VALOR", "VALOR TOTAL", "VALOR_TOTAL"],
        "SECRETARIA": ["SECRETARIA", "ÓRGÃO", "ORGAO"],
        "AGÊNCIA": ["AGÊNCIA", "AGENCIA"],
        "CAMPANHA": ["CAMPANHA"],
        "COMPETÊNCIA": ["COMPETÊNCIA", "COMPETENCIA", "COMPETÊNCIA_TXT", "COMPETÊNCIA (TEXTO)", "COMPETÊNCIA_DT"],
        "DATA DO EMPENHO": ["DATA DO EMPENHO", "DATA_EMPENHO"],
        "PROCESSO": ["PROCESSO", "Nº PROCESSO", "NUMERO PROCESSO", "LINK PROCESSO"],
        "EMPENHO": ["EMPENHO", "Nº EMPENHO", "LINK EMPENHO"],
        "OBSERVAÇÃO": ["OBSERVAÇÃO", "OBSERVACAO"],
        "ESPELHO DIANA": ["ESPELHO DIANA", "DIANA"],
        "ESPELHO": ["ESPELHO", "LINK ESPELHO"],
        "PDF": ["PDF", "LINK PDF"],
    }

    # Cria as colunas "padrão" com base nas alternativas encontradas
    for target, cand_list in aliases.items():
        for c in cand_list:
            if c in df.columns:
                df[target] = df[c]
                break
        if target not in df.columns:
            df[target] = ""

    # Tipagens e limpeza
    # Valor
    df["VALOR DO ESPELHO"] = (
        df["VALOR DO ESPELHO"]
        .astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.extract(r"([-+]?\d*\.?\d+)")[0]
        .astype(float)
        .fillna(0.0)
    )

    # Competência como texto (YYYY-MM preferível)
    df["COMPETÊNCIA"] = df["COMPETÊNCIA"].astype(str).str.strip()

    # Data do empenho como datetime (quando possível)
    try:
        df["DATA DO EMPENHO"] = pd.to_datetime(df["DATA DO EMPENHO"], errors="coerce")
    except Exception:
        pass

    # Campos de filtro sem espaços excedentes
    for col in ["SECRETARIA", "AGÊNCIA", "CAMPANHA"]:
        df[col] = df[col].astype(str).str.strip()

    return df


def brl(v: float) -> str:
    """Formata float em BRL pt-BR simples."""
    if pd.isna(v):
        v = 0.0
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------- App Dash ---------------------------

app = Dash(__name__, suppress_callback_exceptions=True, title="SECOM • Dashboard")
server = app.server  # para gunicorn: dashboard_secom:server

# Sidebar (filtros) + Conteúdo
app.layout = html.Div(
    style={"display": "flex", "gap": "16px", "padding": "16px"},
    children=[
        # -------- Sidebar --------
        html.Div(
            id="sidebar",
            style={
                "width": "320px",
                "minWidth": "280px",
                "maxWidth": "360px",
                "background": "#f6f7f9",
                "border": "1px solid #e6e8eb",
                "borderRadius": "10px",
                "padding": "14px",
                "position": "sticky",
                "top": "12px",
                "height": "fit-content",
            },
            children=[
                html.H3("Filtros", style={"marginTop": 0}),
                html.Label("Aba da planilha"),
                dcc.Dropdown(id="sheet-dropdown", options=[], placeholder="Selecione a aba..."),
                html.Br(),
                html.Label("Secretaria"),
                dcc.Dropdown(id="secretaria-dropdown", multi=True, placeholder="Selecione..."),
                html.Br(),
                html.Label("Agência"),
                dcc.Dropdown(id="agencia-dropdown", multi=True, placeholder="Selecione..."),
                html.Br(),
                html.Label("Campanha"),
                dcc.Dropdown(id="campanha-dropdown", multi=True, placeholder="Selecione..."),
                html.Br(),
                html.Label("Competência (texto)"),
                dcc.Dropdown(id="competencia-dropdown", multi=True, placeholder="Ex.: 2025-01"),
                html.Br(),
                html.Button("Atualizar dados", id="btn-refresh", n_clicks=0, style={
                    "width": "100%", "height": "40px", "background": "#0d6efd",
                    "color": "white", "border": "none", "borderRadius": "8px", "cursor": "pointer"
                }),
                html.Div(
                    f"Fonte: EXCEL_URL (env var)",
                    style={"marginTop": "10px", "fontSize": "12px", "color": "#6b7280"},
                ),
                # Stores
                dcc.Store(id="xlsx-b64"),
                dcc.Store(id="df-json"),
                dcc.Store(id="df-filtered-json"),
            ],
        ),
        # -------- Conteúdo --------
        html.Div(
            id="content",
            style={"flex": 1, "minWidth": 0},
            children=[
                html.H2("Dashboard SECOM"),
                # Cards
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "repeat(3, minmax(220px, 1fr))", "gap": "12px"},
                    children=[
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "12px"},
                            children=[
                                html.Div("Total (VALOR DO ESPELHO)", style={"fontSize": "13px", "color": "#6b7280"}),
                                html.Div(id="card-total", style={"fontWeight": 700, "fontSize": "22px"}),
                            ],
                        ),
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "12px"},
                            children=[
                                html.Div("Registros", style={"fontSize": "13px", "color": "#6b7280"}),
                                html.Div(id="card-registros", style={"fontWeight": 700, "fontSize": "22px"}),
                            ],
                        ),
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "12px"},
                            children=[
                                html.Div("Campanhas distintas", style={"fontSize": "13px", "color": "#6b7280"}),
                                html.Div(id="card-campanhas", style={"fontWeight": 700, "fontSize": "22px"}),
                            ],
                        ),
                    ],
                ),
                html.Br(),
                # Gráficos linha/área e top secretarias
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
                    children=[
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "8px"},
                            children=[
                                html.Div("Evolução mensal", style={"fontWeight": 600, "padding": "4px 8px"}),
                                dcc.Graph(id="fig-evolucao", style={"height": f"{GRAPH_HEIGHT}px"}, config={"displayModeBar": False}),
                            ],
                        ),
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "8px"},
                            children=[
                                html.Div("Top 10 Secretarias", style={"fontWeight": 600, "padding": "4px 8px"}),
                                dcc.Graph(id="fig-top-sec", style={"height": f"{GRAPH_HEIGHT}px"}, config={"displayModeBar": False}),
                            ],
                        ),
                    ],
                ),
                html.Br(),
                # Top agências e treemap
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
                    children=[
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "8px"},
                            children=[
                                html.Div("Top 10 Agências", style={"fontWeight": 600, "padding": "4px 8px"}),
                                dcc.Graph(id="fig-top-ag", style={"height": f"{GRAPH_HEIGHT}px"}, config={"displayModeBar": False}),
                            ],
                        ),
                        html.Div(
                            style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "8px"},
                            children=[
                                html.Div("Treemap Secretaria → Agência", style={"fontWeight": 600, "padding": "4px 8px"}),
                                dcc.Graph(id="fig-treemap", style={"height": f"{GRAPH_HEIGHT}px"}, config={"displayModeBar": False}),
                            ],
                        ),
                    ],
                ),
                html.Br(),
                # Tabela
                html.Div(
                    style={"background": "white", "border": "1px solid #e6e8eb", "borderRadius": "10px", "padding": "8px"},
                    children=[
                        html.Div("Tabela detalhada", style={"fontWeight": 600, "padding": "4px 8px"}),
                        dash_table.DataTable(
                            id="table-detalhe",
                            columns=[
                                {"name": "CAMPANHA", "id": "CAMPANHA"},
                                {"name": "SECRETARIA", "id": "SECRETARIA"},
                                {"name": "AGÊNCIA", "id": "AGÊNCIA"},
                                {"name": "VALOR DO ESPELHO", "id": "VALOR DO ESPELHO"},
                                {"name": "PROCESSO", "id": "PROCESSO"},
                                {"name": "EMPENHO", "id": "EMPENHO"},
                                {"name": "DATA DO EMPENHO", "id": "DATA DO EMPENHO"},
                                {"name": "COMPETÊNCIA", "id": "COMPETÊNCIA"},
                                {"name": "OBSERVAÇÃO", "id": "OBSERVAÇÃO"},
                                {"name": "ESPELHO DIANA", "id": "ESPELHO DIANA"},
                                {"name": "ESPELHO", "id": "ESPELHO"},
                                {"name": "PDF", "id": "PDF"},
                            ],
                            data=[],
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell={"fontFamily": "Inter,system-ui,Arial", "fontSize": 13, "padding": "6px"},
                            style_header={"backgroundColor": "#f3f4f6", "fontWeight": 700},
                        ),
                    ],
                ),
            ],
        ),
    ],
)

# ---------------------- Callbacks --------------------------


@app.callback(
    Output("xlsx-b64", "data"),
    Output("sheet-dropdown", "options"),
    Output("sheet-dropdown", "value"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=False,
)
def cb_download_and_list(_):
    """Baixa a planilha e lista as abas. Também roda no 1º carregamento."""
    try:
        content = download_excel_bytes(EXCEL_URL)
        b64 = base64.b64encode(content).decode("ascii")
        sheets = list_sheets(content)
        opts = [{"label": s, "value": s} for s in sheets]
        default = sheets[0] if sheets else None
        return b64, opts, default
    except Exception as e:
        msg = f"Erro: {e}"
        return None, [{"label": msg, "value": None}], None


@app.callback(
    Output("df-json", "data"),
    Output("secretaria-dropdown", "options"),
    Output("agencia-dropdown", "options"),
    Output("campanha-dropdown", "options"),
    Output("competencia-dropdown", "options"),
    Input("sheet-dropdown", "value"),
    State("xlsx-b64", "data"),
    prevent_initial_call=True,
)
def cb_load_sheet(sheet_name, b64data):
    if not sheet_name or not b64data:
        return None, [], [], [], []
    content = base64.b64decode(b64data.encode("ascii"))
    df = load_sheet_df(content, sheet_name)

    # Opções de filtros
    sec = sorted([s for s in df["SECRETARIA"].dropna().unique() if str(s).strip()])
    ag = sorted([s for s in df["AGÊNCIA"].dropna().unique() if str(s).strip()])
    cam = sorted([s for s in df["CAMPANHA"].dropna().unique() if str(s).strip()])
    comp = sorted([s for s in df["COMPETÊNCIA"].dropna().unique() if str(s).strip()])

    return (
        df.to_json(orient="records", date_format="iso"),
        [{"label": s, "value": s} for s in sec],
        [{"label": s, "value": s} for s in ag],
        [{"label": s, "value": s} for s in cam],
        [{"label": s, "value": s} for s in comp],
    )


@app.callback(
    Output("df-filtered-json", "data"),
    Output("card-total", "children"),
    Output("card-registros", "children"),
    Output("card-campanhas", "children"),
    Output("fig-evolucao", "figure"),
    Output("fig-top-sec", "figure"),
    Output("fig-top-ag", "figure"),
    Output("fig-treemap", "figure"),
    Output("table-detalhe", "data"),
    Input("df-json", "data"),
    Input("secretaria-dropdown", "value"),
    Input("agencia-dropdown", "value"),
    Input("campanha-dropdown", "value"),
    Input("competencia-dropdown", "value"),
    prevent_initial_call=True,
)
def cb_apply_filters(df_json, sec_v, ag_v, cam_v, comp_v):
    empty_fig = px.scatter()
    empty_fig.update_layout(height=GRAPH_HEIGHT, margin=dict(l=30, r=10, t=30, b=30))

    if not df_json:
        return None, "R$ 0,00", "0", "0", empty_fig, empty_fig, empty_fig, empty_fig, []

    df = pd.read_json(df_json, orient="records")
    # Helper p/ listas
    def as_list(v):
        if v is None or v == "":
            return []
        return v if isinstance(v, list) else [v]

    if sec_v:
        df = df[df["SECRETARIA"].isin(as_list(sec_v))]
    if ag_v:
        df = df[df["AGÊNCIA"].isin(as_list(ag_v))]
    if cam_v:
        df = df[df["CAMPANHA"].isin(as_list(cam_v))]
    if comp_v:
        df = df[df["COMPETÊNCIA"].isin(as_list(comp_v))]

    total = float(df["VALOR DO ESPELHO"].sum()) if len(df) else 0.0
    registros = int(len(df))
    campanhas = int(df["CAMPANHA"].nunique()) if len(df) else 0

    # Evolução mensal (área/linha) por COMPETÊNCIA
    ev = (
        df.groupby("COMPETÊNCIA", as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("COMPETÊNCIA")
    )
    fig_evo = px.area(ev, x="COMPETÊNCIA", y="VALOR DO ESPELHO")
    fig_evo.update_layout(height=GRAPH_HEIGHT, margin=dict(l=30, r=10, t=30, b=30))

    # Top 10 Secretarias (barra horizontal)
    top_sec = (
        df.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("VALOR DO ESPELHO", ascending=False)
        .head(10)
    )
    fig_sec = px.bar(top_sec, x="VALOR DO ESPELHO", y="SECRETARIA", orientation="h")
    fig_sec.update_layout(height=GRAPH_HEIGHT, margin=dict(l=110, r=10, t=30, b=30))

    # Top 10 Agências (barra horizontal)
    top_ag = (
        df.groupby("AGÊNCIA", as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("VALOR DO ESPELHO", ascending=False)
        .head(10)
    )
    fig_ag = px.bar(top_ag, x="VALOR DO ESPELHO", y="AGÊNCIA", orientation="h")
    fig_ag.update_layout(height=GRAPH_HEIGHT, margin=dict(l=110, r=10, t=30, b=30))

    # Treemap (Secretaria → Agência)
    if len(df):
        treemap = (
            df.groupby(["SECRETARIA", "AGÊNCIA"], as_index=False)["VALOR DO ESPELHO"].sum()
        )
        fig_tree = px.treemap(treemap, path=["SECRETARIA", "AGÊNCIA"], values="VALOR DO ESPELHO")
    else:
        fig_tree = px.treemap(pd.DataFrame(columns=["SECRETARIA", "AGÊNCIA", "VALOR DO ESPELHO"]),
                              path=["SECRETARIA", "AGÊNCIA"], values="VALOR DO ESPELHO")
    fig_tree.update_layout(height=GRAPH_HEIGHT, margin=dict(l=10, r=10, t=30, b=10))

    # Tabela detalhada
    show_cols = [
        "CAMPANHA", "SECRETARIA", "AGÊNCIA", "VALOR DO ESPELHO",
        "PROCESSO", "EMPENHO", "DATA DO EMPENHO", "COMPETÊNCIA",
        "OBSERVAÇÃO", "ESPELHO DIANA", "ESPELHO", "PDF"
    ]
    df_show = df.copy()
    # formato BRL
    df_show["VALOR DO ESPELHO"] = df_show["VALOR DO ESPELHO"].apply(brl)
    # datas como texto amigável
    if "DATA DO EMPENHO" in df_show.columns:
        df_show["DATA DO EMPENHO"] = df_show["DATA DO EMPENHO"].apply(
            lambda x: pd.to_datetime(x).strftime("%Y-%m-%d") if pd.notna(x) else ""
        )
    table_data = df_show[show_cols].to_dict("records")

    return (
        df.to_json(orient="records", date_format="iso"),
        brl(total),
        str(registros),
        str(campanhas),
        fig_evo, fig_sec, fig_ag, fig_tree,
        table_data
    )


# ---------------------- Main -------------------------------

if __name__ == "__main__":
    # Run local (Render usará gunicorn)
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=False)
