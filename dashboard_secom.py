import os
import io
import math
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime
from dash import Dash, html, dcc, dash_table, Input, Output, State, no_update

# ==========================
# Config & Constantes
# ==========================
DEFAULT_EXCEL_URL = (
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
    "/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)
EXCEL_URL = os.getenv("EXCEL_URL", DEFAULT_EXCEL_URL)

# Nomes de colunas esperadas (ajuste aqui se na sua planilha tiver variações)
COL_CAMPA = "CAMPANHA"
COL_SECR  = "SECRETARIA"
COL_AGEN  = "AGÊNCIA"
COL_VAL   = "VALOR DO ESPELHO"
COL_PROC  = "PROCESSO"
COL_EMP   = "EMPENHO"
COL_DATAE = "DATA DO EMPENHO"
COL_COMPD = "COMPETÊNCIA_DT"   # preferencial: datetime
COL_COMPT = "COMPETÊNCIA_TXT"  # fallback: texto
COL_OBS   = "OBSERVAÇÃO"
COL_DIANA = "ESPELHO DIANA"
COL_ESP   = "ESPELHO"
COL_PDF   = "PDF"

# ==========================
# Funções utilitárias
# ==========================
def _fetch_excel(url: str) -> dict:
    """
    Baixa o Excel (todas as abas) e devolve dict {nome_aba: DataFrame}.
    Trata bloqueios do Google e erros de rede.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Dash/1.0; +https://render.com)"
        }
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        content = io.BytesIO(r.content)
        # sheet_name=None lê todas as abas
        dfs = pd.read_excel(content, sheet_name=None, engine="openpyxl")
        # Normaliza colunas de todas as abas
        cleaned = {}
        for sheet, df in dfs.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                cleaned[sheet] = pd.DataFrame()
                continue
            # remove colunas totalmente vazias
            df = df.dropna(axis=1, how="all")
            # tira espaços dos nomes
            df.columns = [str(c).strip() for c in df.columns]
            # tenta converter datas
            if COL_COMPD in df.columns:
                df[COL_COMPD] = pd.to_datetime(df[COL_COMPD], errors="coerce")
            if COL_DATAE in df.columns:
                df[COL_DATAE] = pd.to_datetime(df[COL_DATAE], errors="coerce")
            # valor numérico
            if COL_VAL in df.columns:
                df[COL_VAL] = pd.to_numeric(df[COL_VAL], errors="coerce").fillna(0.0)
            cleaned[sheet] = df
        return cleaned
    except Exception as e:
        print(f"[ERRO] _fetch_excel: {e}")
        return {}

def _brl(x):
    try:
        if pd.isna(x):
            return ""
        return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(x)

def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            COL_CAMPA, COL_SECR, COL_AGEN, COL_VAL, COL_PROC, COL_EMP,
            COL_DATAE, COL_COMPD, COL_COMPT, COL_OBS, COL_DIANA, COL_ESP, COL_PDF
        ])
    for c in [COL_CAMPA, COL_SECR, COL_AGEN, COL_VAL, COL_PROC, COL_EMP, COL_DATAE,
              COL_COMPD, COL_COMPT, COL_OBS, COL_DIANA, COL_ESP, COL_PDF]:
        if c not in df.columns:
            df[c] = pd.NA
    return df

def _apply_filters(df: pd.DataFrame, secr_vals, ag_vals, camp_vals, date_range):
    if df.empty:
        return df
    out = df.copy()

    # filtros texto
    if secr_vals:
        out = out[out[COL_SECR].astype(str).isin(secr_vals)]
    if ag_vals:
        out = out[out[COL_AGEN].astype(str).isin(ag_vals)]
    if camp_vals:
        out = out[out[COL_CAMPA].astype(str).isin(camp_vals)]

    # filtro por intervalo de competência (usa COMPETÊNCIA_DT; cai para DATA DO EMPENHO)
    if date_range and isinstance(date_range, list) and len(date_range) == 2:
        start, end = date_range
        # tenta COMPETÊNCIA_DT
        if COL_COMPD in out.columns and pd.api.types.is_datetime64_any_dtype(out[COL_COMPD]):
            mask = pd.Series([True] * len(out))
            if start:
                mask &= (out[COL_COMPD] >= pd.to_datetime(start))
            if end:
                mask &= (out[COL_COMPD] <= pd.to_datetime(end))
            out = out[mask]
        elif COL_DATAE in out.columns and pd.api.types.is_datetime64_any_dtype(out[COL_DATAE]):
            mask = pd.Series([True] * len(out))
            if start:
                mask &= (out[COL_DATAE] >= pd.to_datetime(start))
            if end:
                mask &= (out[COL_DATAE] <= pd.to_datetime(end))
            out = out[mask]

    return out

def _fill_competencia_txt(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if (COL_COMPT not in df.columns) or df[COL_COMPT].isna().all():
        if COL_COMPD in df.columns and pd.api.types.is_datetime64_any_dtype(df[COL_COMPD]):
            df[COL_COMPT] = df[COL_COMPD].dt.strftime("%Y-%m")
        elif COL_DATAE in df.columns and pd.api.types.is_datetime64_any_dtype(df[COL_DATAE]):
            df[COL_COMPT] = df[COL_DATAE].dt.strftime("%Y-%m")
        else:
            # ultima queda: tenta extrair AAAA-MM de texto
            df[COL_COMPT] = df[COL_COMPT].astype(str)
    return df

# ==========================
# App
# ==========================
app = Dash(__name__, title="SECOM - Painel", suppress_callback_exceptions=True)
server = app.server

# Layout em Grid: sidebar fixa + conteúdo rolável
APP_STYLE = {
    "display": "grid",
    "gridTemplateColumns": "320px 1fr",
    "gridTemplateRows": "auto 1fr",
    "gridTemplateAreas": "'sidebar header' 'sidebar content'",
    "height": "100vh",
    "maxHeight": "100vh",
    "overflow": "hidden",
    "backgroundColor": "#f7f7f9",  # claro (padrão)
    "fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial"
}
SIDEBAR_STYLE = {
    "gridArea": "sidebar",
    "borderRight": "1px solid #e5e7eb",
    "padding": "16px",
    "overflowY": "auto",
    "backgroundColor": "#ffffff"
}
HEADER_STYLE = {
    "gridArea": "header",
    "padding": "12px 16px",
    "borderBottom": "1px solid #e5e7eb",
    "backgroundColor": "#ffffff",
    "display": "flex",
    "alignItems": "center",
    "gap": "12px"
}
CONTENT_STYLE = {
    "gridArea": "content",
    "overflow": "auto",
    "padding": "16px",
}

CARD_STYLE = {
    "backgroundColor": "#ffffff",
    "border": "1px solid #e5e7eb",
    "borderRadius": "12px",
    "padding": "12px",
    "boxShadow": "0 1px 2px rgba(0,0,0,0.04)"
}

def _blank_fig(msg="Sem dados"):
    fig = px.scatter()
    fig.update_layout(
        height=360, margin=dict(l=20,r=20,t=50,b=30),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                          showarrow=False, font=dict(size=14))]
    )
    return fig

# layout
app.layout = html.Div(
    APP_STYLE,
    children=[
        # Data em memória (todas as abas cruas)
        dcc.Store(id="raw-sheets"),
        # Data filtrada da aba selecionada
        dcc.Store(id="filtered-data"),
        # Botão/tempo de refresh opcional
        # dcc.Interval(id="auto-refresh", interval=10*60*1000, n_intervals=0),  # 10 min

        html.Aside(
            style=SIDEBAR_STYLE,
            children=[
                html.H3("SECOM", style={"margin":"0 0 12px 0"}),
                html.Div("Fonte: Planilha Google", style={"color":"#6b7280", "fontSize":"12px", "marginBottom":"12px"}),
                html.Button("Atualizar dados", id="btn-refresh", n_clicks=0,
                            style={"width":"100%", "padding":"10px", "borderRadius":"8px",
                                   "border":"1px solid #e5e7eb", "background":"#f3f4f6", "cursor":"pointer"}),
                html.Hr(),

                html.Label("Aba da Planilha", style={"fontWeight":"600"}),
                dcc.Dropdown(id="sel-sheet", placeholder="Selecione a aba…"),

                html.Br(),
                html.Label("Secretaria", style={"fontWeight":"600"}),
                dcc.Dropdown(id="f-secretaria", multi=True, placeholder="Filtrar Secretarias…"),
                html.Br(),
                html.Label("Agência", style={"fontWeight":"600"}),
                dcc.Dropdown(id="f-agencia", multi=True, placeholder="Filtrar Agências…"),
                html.Br(),
                html.Label("Campanha", style={"fontWeight":"600"}),
                dcc.Dropdown(id="f-campanha", multi=True, placeholder="Filtrar Campanhas…"),
                html.Br(),
                html.Label("Período (Competência ou Empenho)", style={"fontWeight":"600"}),
                dcc.DatePickerRange(id="f-periodo", minimum_nights=0, display_format="YYYY-MM-DD"),

                html.Div(id="sidebar-msg", style={"color":"#ef4444", "marginTop":"12px", "fontSize":"12px"})
            ]
        ),

        html.Header(
            style=HEADER_STYLE,
            children=[
                html.H2("Painel de Investimentos em Comunicação", style={"margin":"0", "fontSize":"18px"}),
                html.Div(id="header-info", style={"color":"#6b7280", "fontSize":"12px"})
            ]
        ),

        html.Main(
            style=CONTENT_STYLE,
            children=[
                # Grid de cards de gráficos
                html.Div(
                    style={
                        "display":"grid",
                        "gridTemplateColumns":"repeat(auto-fit, minmax(340px, 1fr))",
                        "gap":"12px"
                    },
                    children=[
                        html.Div(CARD_STYLE | {"minHeight":"380px"}, children=[
                            html.H4("Evolução mensal", style={"marginTop":"0"}),
                            dcc.Graph(id="g-evolucao", figure=_blank_fig(), config={"displayModeBar": False})
                        ]),
                        html.Div(CARD_STYLE | {"minHeight":"380px"}, children=[
                            html.H4("Top 10 Secretarias", style={"marginTop":"0"}),
                            dcc.Graph(id="g-top-secretarias", figure=_blank_fig(), config={"displayModeBar": False})
                        ]),
                        html.Div(CARD_STYLE | {"minHeight":"380px"}, children=[
                            html.H4("Top 10 Agências", style={"marginTop":"0"}),
                            dcc.Graph(id="g-top-agencias", figure=_blank_fig(), config={"displayModeBar": False})
                        ]),
                        html.Div(CARD_STYLE | {"minHeight":"420px"}, children=[
                            html.H4("Treemap Secretaria → Agência", style={"marginTop":"0"}),
                            dcc.Graph(id="g-treemap", figure=_blank_fig(), config={"displayModeBar": False})
                        ]),
                        html.Div(CARD_STYLE | {"minHeight":"380px"}, children=[
                            html.H4("Campanhas por valor (Top)", style={"marginTop":"0"}),
                            dcc.Graph(id="g-campanhas", figure=_blank_fig(), config={"displayModeBar": False})
                        ]),
                    ]
                ),
                html.Br(),
                html.Div(CARD_STYLE, children=[
                    html.H4("Tabela detalhada", style={"marginTop":"0"}),
                    dash_table.DataTable(
                        id="tbl-detalhes",
                        columns=[
                            {"name":"CAMPANHA", "id":COL_CAMPA, "presentation":"markdown"},
                            {"name":"SECRETARIA", "id":COL_SECR},
                            {"name":"AGÊNCIA", "id":COL_AGEN},
                            {"name":"VALOR DO ESPELHO", "id":COL_VAL},
                            {"name":"PROCESSO", "id":COL_PROC, "presentation":"markdown"},
                            {"name":"EMPENHO", "id":COL_EMP, "presentation":"markdown"},
                            {"name":"DATA DO EMPENHO", "id":COL_DATAE},
                            {"name":"COMPETÊNCIA", "id":COL_COMPT},
                            {"name":"OBSERVAÇÃO", "id":COL_OBS},
                            {"name":"DIANA", "id":COL_DIANA, "presentation":"markdown"},
                            {"name":"ESPELHO", "id":COL_ESP, "presentation":"markdown"},
                            {"name":"PDF", "id":COL_PDF, "presentation":"markdown"},
                        ],
                        page_size=12,
                        style_table={"overflowX":"auto"},
                        style_cell={"fontSize":"12px", "padding":"6px"},
                        style_header={"backgroundColor":"#f3f4f6", "fontWeight":"600"},
                        sort_action="native",
                        filter_action="native",
                    )
                ])
            ]
        )
    ]
)

# ==========================
# Callbacks
# ==========================

@app.callback(
    Output("raw-sheets", "data"),
    Output("header-info", "children"),
    Output("sidebar-msg", "children"),
    Input("btn-refresh", "n_clicks"),
    # Input("auto-refresh", "n_intervals"),  # se usar auto refresh
    prevent_initial_call=False
)
def refresh_data(n_clicks):
    dfs = _fetch_excel(EXCEL_URL)
    if not dfs:
        return {}, no_update, "Não foi possível carregar a planilha. Verifique o link e o compartilhamento."
    # montar info de header
    abas = list(dfs.keys())
    info = f"{len(abas)} abas carregadas • {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    return {k: v.to_dict("records") for k, v in dfs.items()}, info, ""

@app.callback(
    Output("sel-sheet", "options"),
    Output("sel-sheet", "value"),
    Input("raw-sheets", "data"),
    prevent_initial_call=False
)
def fill_sheets_options(raw):
    if not raw:
        return [], None
    sheets = list(raw.keys())
    opts = [{"label": s, "value": s} for s in sheets]
    default = sheets[0] if sheets else None
    return opts, default

@app.callback(
    Output("f-secretaria", "options"),
    Output("f-agencia", "options"),
    Output("f-campanha", "options"),
    Output("f-periodo", "min_date_allowed"),
    Output("f-periodo", "max_date_allowed"),
    Input("raw-sheets", "data"),
    Input("sel-sheet", "value"),
)
def fill_filters(raw, sheet):
    if not raw or not sheet or sheet not in raw:
        return [], [], [], None, None
    df = pd.DataFrame(raw[sheet])
    df = _ensure_columns(df)
    df = _fill_competencia_txt(df)

    # limites de datas
    min_d = max_d = None
    if COL_COMPD in df and pd.api.types.is_datetime64_any_dtype(df[COL_COMPD]):
        min_d = pd.to_datetime(df[COL_COMPD]).min()
        max_d = pd.to_datetime(df[COL_COMPD]).max()
    elif COL_DATAE in df and pd.api.types.is_datetime64_any_dtype(df[COL_DATAE]):
        min_d = pd.to_datetime(df[COL_DATAE]).min()
        max_d = pd.to_datetime(df[COL_DATAE]).max()

    opt_secr = [{"label": s, "value": s} for s in sorted(df[COL_SECR].dropna().astype(str).unique()) if s]
    opt_ag   = [{"label": s, "value": s} for s in sorted(df[COL_AGEN].dropna().astype(str).unique()) if s]
    opt_cam  = [{"label": s, "value": s} for s in sorted(df[COL_CAMPA].dropna().astype(str).unique()) if s]

    return opt_secr, opt_ag, opt_cam, (min_d.to_pydatetime() if pd.notna(min_d) else None), (max_d.to_pydatetime() if pd.notna(max_d) else None)

@app.callback(
    Output("filtered-data", "data"),
    Input("raw-sheets", "data"),
    Input("sel-sheet", "value"),
    Input("f-secretaria", "value"),
    Input("f-agencia", "value"),
    Input("f-campanha", "value"),
    Input("f-periodo", "start_date"),
    Input("f-periodo", "end_date"),
)
def compute_filtered(raw, sheet, v_secr, v_ag, v_camp, start, end):
    if not raw or not sheet or sheet not in raw:
        return {}
    df = pd.DataFrame(raw[sheet])
    df = _ensure_columns(df)
    df = _fill_competencia_txt(df)
    out = _apply_filters(df, v_secr, v_ag, v_camp, [start, end])
    # prepara campos de link/formatos para a tabela
    if not out.empty:
        # valores BRL
        out[COL_VAL] = out[COL_VAL].apply(_brl)
        # datas texto
        if COL_DATAE in out.columns and pd.api.types.is_datetime64_any_dtype(out[COL_DATAE]):
            out[COL_DATAE] = out[COL_DATAE].dt.strftime("%Y-%m-%d")
        # markdown links
        def mk(url, label):
            s = str(url).strip()
            if s and s.lower().startswith("http"):
                return f"[{label}]({s})"
            return ""
        out[COL_PROC] = out[COL_PROC].apply(lambda x: mk(x, "Processo"))
        out[COL_EMP]  = out[COL_EMP].apply(lambda x: mk(x, "Empenho"))
        out[COL_DIANA]= out[COL_DIANA].apply(lambda x: mk(x, "Diana"))
        out[COL_ESP]  = out[COL_ESP].apply(lambda x: mk(x, "Espelho"))
        out[COL_PDF]  = out[COL_PDF].apply(lambda x: mk(x, "PDF"))
    return out.to_dict("records")

# ===== Gráficos =====

@app.callback(
    Output("g-evolucao", "figure"),
    Output("g-top-secretarias", "figure"),
    Output("g-top-agencias", "figure"),
    Output("g-treemap", "figure"),
    Output("g-campanhas", "figure"),
    Output("tbl-detalhes", "data"),
    Input("filtered-data", "data"),
)
def update_viz(data):
    if not data:
        msg = "Sem dados (verifique a aba/filtros ou a planilha)."
        return (_blank_fig(msg), _blank_fig(msg), _blank_fig(msg), _blank_fig(msg), _blank_fig(msg), [])

    df = pd.DataFrame(data)
    if df.empty:
        msg = "Sem dados após filtros."
        return (_blank_fig(msg), _blank_fig(msg), _blank_fig(msg), _blank_fig(msg), _blank_fig(msg), [])

    # Para gráficos, precisamos do valor numérico: reconstroi a partir da formatação BRL
    def unbrl(s):
        if pd.isna(s) or not str(s):
            return 0.0
        txt = str(s).replace("R$","").replace(".","").replace(",",".").strip()
        try:
            return float(txt)
        except Exception:
            return 0.0

    df_num = df.copy()
    df_num["VAL_NUM"] = df_num[COL_VAL].apply(unbrl)

    # Evolução mensal
    if COL_COMPT in df_num.columns and df_num[COL_COMPT].notna().any():
        ev = (df_num.groupby(COL_COMPT, as_index=False)["VAL_NUM"].sum()
                    .sort_values(COL_COMPT))
        fig_ev = px.line(ev, x=COL_COMPT, y="VAL_NUM", markers=True)
        fig_ev.update_layout(yaxis_title="Valor (R$)", height=360, margin=dict(l=20,r=20,t=30,b=20))
    else:
        fig_ev = _blank_fig("Sem COMPETÊNCIA para evoluir")

    # Top 10 Secretarias
    top_sec = (df_num.groupby(COL_SECR, as_index=False)["VAL_NUM"].sum()
               .sort_values("VAL_NUM", ascending=False).head(10))
    fig_sec = px.bar(top_sec, x="VAL_NUM", y=COL_SECR, orientation="h")
    fig_sec.update_layout(xaxis_title="Valor (R$)", yaxis_title=None, height=360, margin=dict(l=20,r=20,t=30,b=20))

    # Top 10 Agências
    top_ag = (df_num.groupby(COL_AGEN, as_index=False)["VAL_NUM"].sum()
              .sort_values("VAL_NUM", ascending=False).head(10))
    fig_ag = px.bar(top_ag, x="VAL_NUM", y=COL_AGEN, orientation="h")
    fig_ag.update_layout(xaxis_title="Valor (R$)", yaxis_title=None, height=360, margin=dict(l=20,r=20,t=30,b=20))

    # Treemap Secretaria → Agência
    if not df_num[[COL_SECR, COL_AGEN]].dropna(how="all").empty:
        fig_tree = px.treemap(df_num, path=[COL_SECR, COL_AGEN], values="VAL_NUM")
        fig_tree.update_layout(height=420, margin=dict(l=10,r=10,t=30,b=10))
    else:
        fig_tree = _blank_fig("Sem hierarquia para treemap")

    # Campanhas por valor (Top)
    top_camp = (df_num.groupby(COL_CAMPA, as_index=False)["VAL_NUM"].sum()
                .sort_values("VAL_NUM", ascending=False).head(15))
    fig_camp = px.bar(top_camp, x="VAL_NUM", y=COL_CAMPA, orientation="h")
    fig_camp.update_layout(xaxis_title="Valor (R$)", yaxis_title=None, height=360, margin=dict(l=20,r=20,t=30,b=20))

    # Tabela já está formatada no compute_filtered
    return fig_ev, fig_sec, fig_ag, fig_tree, fig_camp, df.to_dict("records")

# ==========================
# WSGI
# ==========================
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=False)
