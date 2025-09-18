
import os
import io
import re
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

from dash import Dash, dcc, html, Input, Output, State, dash_table, ctx

# --------------------------------------------------------------------------------------
# Configurações
# --------------------------------------------------------------------------------------

DEFAULT_SHEETS_URL = (
    os.environ.get("EXCEL_URL")
    or "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)

REQUEST_TIMEOUT = 25  # segundos

# Map de nomes de colunas esperadas -> aliases possíveis no arquivo
COLMAP = {
    "CAMPANHA": ["CAMPANHA", "NOME DA CAMPANHA", "CAMPANHA_NM"],
    "SECRETARIA": ["SECRETARIA", "ÓRGÃO", "ORGAO"],
    "AGÊNCIA": ["AGÊNCIA", "AGENCIA", "AGÊNCIA/AGENCIA"],
    "VALOR DO ESPELHO": ["VALOR DO ESPELHO", "VALOR", "VALOR_ESPELHO"],
    "PROCESSO": ["PROCESSO", "URL_PROCESSO", "LINK PROCESSO"],
    "EMPENHO": ["EMPENHO", "URL_EMPENHO", "LINK EMPENHO"],
    "DATA DO EMPENHO": ["DATA DO EMPENHO", "DT_EMPENHO", "DATA EMPENHO"],
    "COMPETÊNCIA_DT": ["COMPETÊNCIA_DT", "COMPETENCIA_DT", "DT_COMPETENCIA"],
    "COMPETÊNCIA_TXT": ["COMPETÊNCIA_TXT", "COMPETENCIA_TXT", "COMPETÊNCIA"],
    "OBSERVAÇÃO": ["OBSERVAÇÃO", "OBS", "OBSERVACAO"],
    "ESPELHO DIANA": ["ESPELHO DIANA", "URL_DIANA", "DIANA"],
    "ESPELHO": ["ESPELHO", "URL_ESPELHO"],
    "PDF": ["PDF", "URL_PDF"],
}

# --------------------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------------------

def _fetch_excel_bytes(url: str) -> bytes:
    """Baixa o XLSX do Google Sheets (ou outra URL)."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.content
    except Exception as e:
        raise RuntimeError(f"Falha ao baixar a planilha: {e}")

def _sheet_names_from_url(url: str) -> list[str]:
    """Lista os nomes das abas do arquivo remoto."""
    raw = _fetch_excel_bytes(url)
    with pd.ExcelFile(io.BytesIO(raw)) as xl:
        return list(xl.sheet_names)

def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Colunas em maiúsculas e sem espaços extras."""
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df

def _first_present(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Converte para numérico aceitando formatos PT-BR (vírgula decimal)."""
    s = series.astype(str).str.replace(r"[^\d,.\-]", "", regex=True)
    # Se tem vírgula e não tem ponto, trocamos vírgula por ponto
    s = np.where(
        s.astype(str).str.contains(",") & ~s.astype(str).str.contains(r"\.\d"),
        s.astype(str).str.replace(",", ".", regex=False),
        s,
    )
    return pd.to_numeric(s, errors="coerce")

def _parse_competencia(df: pd.DataFrame) -> pd.DataFrame:
    """Gera COMPETENCIA_DT (primeiro dia do mês) e COMPETENCIA_MES (YYYY-MM)."""
    df = df.copy()
    cdt = _first_present(df, COLMAP["COMPETÊNCIA_DT"]) or ""
    ctxt = _first_present(df, COLMAP["COMPETÊNCIA_TXT"]) or ""

    comp = None
    if cdt and cdt in df.columns:
        comp = pd.to_datetime(df[cdt], errors="coerce", dayfirst=True)
    if comp is None or comp.isna().all():
        if ctxt and ctxt in df.columns:
            comp = pd.to_datetime(df[ctxt], errors="coerce", dayfirst=True)
        else:
            comp = pd.Series([pd.NaT] * len(df))

    # Normaliza pro primeiro dia do mês
    comp = comp.dt.to_period("M").dt.to_timestamp()
    df["COMPETENCIA_DT"] = comp
    df["COMPETENCIA_MES"] = df["COMPETENCIA_DT"].dt.strftime("%Y-%m")

    return df

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza nomes de colunas, cria colunas auxiliares e garante tipos."""
    df = _standardize_columns(df)

    # Renomear colunas padrão se estiverem com outro rótulo
    rename_map = {}
    for dst, cands in COLMAP.items():
        got = _first_present(df, cands)
        if got and got != dst:
            rename_map[got] = dst
    if rename_map:
        df = df.rename(columns=rename_map)

    # Converte valor
    if "VALOR DO ESPELHO" in df.columns:
        df["VALOR DO ESPELHO"] = _coerce_numeric(df["VALOR DO ESPELHO"]).fillna(0.0)
    else:
        df["VALOR DO ESPELHO"] = 0.0

    # Datas
    df = _parse_competencia(df)
    if "DATA DO EMPENHO" in df.columns:
        df["DATA DO EMPENHO"] = pd.to_datetime(df["DATA DO EMPENHO"], errors="coerce", dayfirst=True)

    # Garante existência das demais colunas como string
    for col in ["CAMPANHA","SECRETARIA","AGÊNCIA","PROCESSO","EMPENHO","OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("")

    # Valor BR formatado
    def fmt_brl(v):
        try:
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return ""
    df["VALOR (BRL)"] = df["VALOR DO ESPELHO"].apply(fmt_brl)

    return df

def _read_sheet(url: str, sheet: str) -> pd.DataFrame:
    """Carrega uma aba específica como DataFrame normalizado."""
    raw = _fetch_excel_bytes(url)
    df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet, dtype=object)
    return _normalize_df(df)

def _safe_sorted_unique(series: pd.Series) -> list[str]:
    vals = series.fillna("").astype(str).unique().tolist()
    # Evita erro de comparação int/str ao ordenar
    try:
        return sorted([v for v in vals if v])
    except Exception:
        return [v for v in vals if v]

# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

def make_figure_template(theme: str) -> str:
    return "plotly_dark" if (theme == "dark") else "plotly_white"

def build_layout(sheet_names: list[str]):
    theme_switch = dcc.RadioItems(
        id="theme",
        options=[{"label":"Claro","value":"light"},{"label":"Escuro","value":"dark"}],
        value="light",
        inline=True,
        style={"display":"inline-block","marginLeft":"8px"}
    )

    return html.Div(
        id="root",
        style={"backgroundColor":"#0b0c0e", "minHeight":"100vh"},
        children=[
            # Barra superior
            html.Div(
                style={
                    "display":"flex","justifyContent":"space-between","alignItems":"center",
                    "padding":"16px 20px","backgroundColor":"#111318","borderBottom":"1px solid #1f2430"
                },
                children=[
                    html.Div([
                        html.H2("SECOM • Dashboard de Processos", style={"margin":"0","color":"#e2e8f0"}),
                        html.Div("Dados dinâmicos via Google Sheets", style={"color":"#9aa4b2","fontSize":"12px"})
                    ]),
                    html.Div([
                        html.Span("Tema:", style={"color":"#9aa4b2","marginRight":"6px"}),
                        theme_switch,
                        html.Button("Atualizar dados", id="btn_refresh", n_clicks=0, style={
                            "marginLeft":"16px","padding":"8px 12px","border":"1px solid #334155",
                            "background":"#1f2937","color":"#e5e7eb","borderRadius":"10px","cursor":"pointer"
                        }),
                    ])
                ]
            ),

            # Filtros
            html.Div(
                style={
                    "padding":"16px 20px","backgroundColor":"#0b0c0e","borderBottom":"1px solid #1f2430"
                },
                children=[
                    html.Div(style={"display":"grid","gridTemplateColumns":"repeat(6, minmax(0,1fr))","gap":"12px"}, children=[
                        # ABA (sheet)
                        html.Div(children=[
                            html.Label("Aba da planilha", style={"color":"#cbd5e1","fontWeight":600}),
                            dcc.Dropdown(
                                id="f_sheet",
                                options=[{"label": s, "value": s} for s in sheet_names],
                                value=sheet_names[0] if sheet_names else None,
                                placeholder="Escolha a aba…",
                                clearable=False
                            )
                        ]),
                        html.Div(children=[
                            html.Label("Secretaria", style={"color":"#cbd5e1","fontWeight":600}),
                            dcc.Dropdown(id="f_secretaria", options=[], multi=True, placeholder="Selecione…")
                        ]),
                        html.Div(children=[
                            html.Label("Agência", style={"color":"#cbd5e1","fontWeight":600}),
                            dcc.Dropdown(id="f_agencia", options=[], multi=True, placeholder="Selecione…")
                        ]),
                        html.Div(children=[
                            html.Label("Campanha", style={"color":"#cbd5e1","fontWeight":600}),
                            dcc.Dropdown(id="f_campanha", options=[], multi=True, placeholder="Selecione…")
                        ]),
                        html.Div(children=[
                            html.Label("Período (Competência)", style={"color":"#cbd5e1","fontWeight":600}),
                            dcc.Dropdown(id="f_comp", options=[], multi=True, placeholder="Selecione…")
                        ]),
                        html.Div(children=[
                            html.Label(" ", style={"color":"#cbd5e1","fontWeight":600, "visibility":"hidden"}),
                            dcc.Input(id="excel_url", type="text", value=DEFAULT_SHEETS_URL, debounce=True,
                                      placeholder="URL export?format=xlsx…",
                                      style={"width":"100%","background":"#0f172a","border":"1px solid #1f2430","color":"#e2e8f0","borderRadius":"10px","padding":"8px"}),
                        ]),
                    ])
                ]
            ),

            # KPIs
            html.Div(style={"padding":"16px 20px","backgroundColor":"#0b0c0e"}, children=[
                html.Div(style={"display":"grid","gridTemplateColumns":"repeat(4, minmax(0,1fr))","gap":"12px"}, children=[
                    html.Div(id="kpi_total", style=_card_style()),
                    html.Div(id="kpi_qtd", style=_card_style()),
                    html.Div(id="kpi_mediana", style=_card_style()),
                    html.Div(id="kpi_distintas", style=_card_style()),
                ])
            ]),

            # Gráficos
            html.Div(style={"padding":"0px 20px 20px 20px","backgroundColor":"#0b0c0e"}, children=[
                html.Div(style={"display":"grid","gridTemplateColumns":"repeat(2, minmax(0,1fr))","gap":"12px"}, children=[
                    html.Div(_graph_card("Evolução mensal", "g_evolucao")),
                    html.Div(_graph_card("Top 10 Secretarias", "g_sec")),
                ]),
                html.Div(style={"height":"12px"}),
                html.Div(style={"display":"grid","gridTemplateColumns":"repeat(2, minmax(0,1fr))","gap":"12px"}, children=[
                    html.Div(_graph_card("Top 10 Agências", "g_age")),
                    html.Div(_graph_card("Treemap Secretaria → Agência", "g_treemap")),
                ]),
                html.Div(style={"height":"12px"}),
                html.Div(_graph_card("Campanhas por valor", "g_camp")),
            ]),

            # Tabela
            html.Div(style={"padding":"0px 20px 30px 20px","backgroundColor":"#0b0c0e"}, children=[
                html.Div(style=_card_style(), children=[
                    html.Div("Tabela detalhada", style={"color":"#e2e8f0","fontWeight":700,"padding":"12px 12px 0 12px"}),
                    dash_table.DataTable(
                        id="tbl",
                        columns=[
                            {"name": "CAMPANHA", "id": "CAMPANHA"},
                            {"name": "SECRETARIA", "id": "SECRETARIA"},
                            {"name": "AGÊNCIA", "id": "AGÊNCIA"},
                            {"name": "VALOR DO ESPELHO", "id": "VALOR (BRL)"},
                            {"name": "PROCESSO", "id": "PROCESSO_MD", "presentation": "markdown"},
                            {"name": "EMPENHO", "id": "EMPENHO_MD", "presentation": "markdown"},
                            {"name": "DATA DO EMPENHO", "id": "DATA DO EMPENHO"},
                            {"name": "COMPETÊNCIA", "id": "COMPETENCIA_MES"},
                            {"name": "OBSERVAÇÃO", "id": "OBSERVAÇÃO"},
                            {"name": "ESPELHO DIANA", "id": "ESPELHO DIANA_MD", "presentation": "markdown"},
                            {"name": "ESPELHO", "id": "ESPELHO_MD", "presentation": "markdown"},
                            {"name": "PDF", "id": "PDF_MD", "presentation": "markdown"},
                        ],
                        data=[],
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        export_format="xlsx",
                        style_table={"overflowX":"auto"},
                        style_as_list_view=True,
                        style_header={
                            "backgroundColor":"#0b0c0e","color":"#93a4b8","fontWeight":"bold","borderBottom":"1px solid #1f2430"
                        },
                        style_cell={
                            "backgroundColor":"#111318","color":"#e2e8f0","border":"0px solid transparent",
                            "padding":"8px","fontSize":"13px"
                        },
                        markdown_options={"link_target":"_blank"},
                    )
                ])
            ])
        ]
    )

def _card_style():
    return {
        "background":"#111318",
        "border":"1px solid #1f2430",
        "borderRadius":"14px",
        "boxShadow":"0 3px 12px rgba(3,7,18,0.35)",
        "padding":"12px"
    }

def _graph_card(title, graph_id):
    return html.Div(style=_card_style(), children=[
        html.Div(title, style={"color":"#e2e8f0","fontWeight":700,"padding":"0 0 8px 0"}),
        dcc.Graph(id=graph_id, config={"displaylogo":False})
    ])

# --------------------------------------------------------------------------------------
# Inicializa layout com nomes de abas
# --------------------------------------------------------------------------------------
try:
    START_SHEETS = _sheet_names_from_url(DEFAULT_SHEETS_URL)
except Exception:
    START_SHEETS = []

app.layout = build_layout(START_SHEETS)

# --------------------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------------------

def _apply_filters(df: pd.DataFrame,
                   secs: list[str] | None,
                   ages: list[str] | None,
                   camps: list[str] | None,
                   comps: list[str] | None) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if secs:
        mask &= df["SECRETARIA"].astype(str).isin(secs)
    if ages:
        mask &= df["AGÊNCIA"].astype(str).isin(ages)
    if camps:
        mask &= df["CAMPANHA"].astype(str).isin(camps)
    if comps:
        mask &= df["COMPETENCIA_MES"].astype(str).isin(comps)
    return df.loc[mask].copy()

def _mk_link_md(url: str, label: str) -> str:
    u = str(url).strip()
    if u and re.match(r"^https?://", u, flags=re.I):
        return f"[{label}]({u})"
    return ""

def _kpi_card(title: str, value: str) -> html.Div:
    return html.Div(style=_card_style(), children=[
        html.Div(title, style={"color":"#9aa4b2","fontSize":"12px","paddingBottom":"4px"}),
        html.Div(value, style={"color":"#e2e8f0","fontSize":"24px","fontWeight":800})
    ])

@app.callback(
    Output("f_secretaria","options"),
    Output("f_agencia","options"),
    Output("f_campanha","options"),
    Output("f_comp","options"),
    Input("f_sheet","value"),
    Input("btn_refresh","n_clicks"),
    State("excel_url","value"),
    prevent_initial_call=False
)
def update_filter_options(sheet, n_clicks, url):
    if not url:
        url = DEFAULT_SHEETS_URL
    if not sheet:
        # tenta pegar primeira aba
        try:
            sheet_names = _sheet_names_from_url(url)
            sheet = sheet_names[0] if sheet_names else None
        except Exception:
            sheet = None

    if not sheet:
        return [], [], [], []

    try:
        df = _read_sheet(url, sheet)
    except Exception:
        return [], [], [], []

    opt_se = [{"label": v, "value": v} for v in _safe_sorted_unique(df["SECRETARIA"])]
    opt_ag = [{"label": v, "value": v} for v in _safe_sorted_unique(df["AGÊNCIA"])]
    opt_ca = [{"label": v, "value": v} for v in _safe_sorted_unique(df["CAMPANHA"])]
    opt_co = [{"label": v, "value": v} for v in _safe_sorted_unique(df["COMPETENCIA_MES"])]
    return opt_se, opt_ag, opt_ca, opt_co

@app.callback(
    Output("kpi_total","children"),
    Output("kpi_qtd","children"),
    Output("kpi_mediana","children"),
    Output("kpi_distintas","children"),
    Output("g_evolucao","figure"),
    Output("g_sec","figure"),
    Output("g_age","figure"),
    Output("g_treemap","figure"),
    Output("g_camp","figure"),
    Output("tbl","data"),
    Input("f_sheet","value"),
    Input("f_secretaria","value"),
    Input("f_agencia","value"),
    Input("f_campanha","value"),
    Input("f_comp","value"),
    Input("theme","value"),
    Input("btn_refresh","n_clicks"),
    State("excel_url","value"),
)
def update_content(sheet, v_se, v_ag, v_ca, v_co, theme, n_clicks, url):
    if not url:
        url = DEFAULT_SHEETS_URL

    # Carrega a aba selecionada
    try:
        df = _read_sheet(url, sheet) if sheet else pd.DataFrame()
    except Exception as e:
        empty_fig = go.Figure()
        msg = html.Div([
            html.Div("Falha ao carregar dados", style={"color":"#e11d48","fontWeight":700}),
            html.Div(str(e), style={"color":"#94a3b8","fontSize":"12px"})
        ])
        return msg, msg, msg, msg, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, []

    # Aplica filtros
    df_f = _apply_filters(
        df,
        secs=v_se if isinstance(v_se, list) else (v_se and [v_se]) or None,
        ages=v_ag if isinstance(v_ag, list) else (v_ag and [v_ag]) or None,
        camps=v_ca if isinstance(v_ca, list) else (v_ca and [v_ca]) or None,
        comps=v_co if isinstance(v_co, list) else (v_co and [v_co]) or None,
    )

    # KPIs
    total = df_f["VALOR DO ESPELHO"].sum() if not df_f.empty else 0.0
    qtd = len(df_f)
    med = float(df_f["VALOR DO ESPELHO"].median()) if not df_f.empty else 0.0
    dist = df_f["PROCESSO"].nunique() if "PROCESSO" in df_f.columns else qtd

    def brl(v):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    k1 = _kpi_card("Total (Valor do Espelho)", brl(total))
    k2 = _kpi_card("Qtd. de linhas", f"{qtd:,}".replace(",", "."))
    k3 = _kpi_card("Mediana por linha", brl(med))
    k4 = _kpi_card("Processos distintos", f"{dist:,}".replace(",", "."))

    template = make_figure_template(theme)

    # 1) Evolução mensal
    if not df_f.empty:
        evo = df_f.groupby("COMPETENCIA_DT", as_index=False)["VALOR DO ESPELHO"].sum().sort_values("COMPETENCIA_DT")
        fig_evo = px.area(evo, x="COMPETENCIA_DT", y="VALOR DO ESPELHO", template=template)
        fig_evo.update_layout(margin=dict(l=12,r=12,t=10,b=12), yaxis_title=None, xaxis_title=None)
    else:
        fig_evo = go.Figure()

    # 2) Top 10 Secretarias
    if not df_f.empty:
        top_se = (
            df_f.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"].sum()
            .sort_values("VALOR DO ESPELHO", ascending=False).head(10)
        )
        fig_se = px.bar(top_se, x="VALOR DO ESPELHO", y="SECRETARIA", orientation="h", template=template)
        fig_se.update_layout(margin=dict(l=12,r=12,t=10,b=12), xaxis_title=None, yaxis_title=None)
    else:
        fig_se = go.Figure()

    # 3) Top 10 Agências
    if not df_f.empty:
        top_ag = (
            df_f.groupby("AGÊNCIA", as_index=False)["VALOR DO ESPELHO"].sum()
            .sort_values("VALOR DO ESPELHO", ascending=False).head(10)
        )
        fig_ag = px.bar(top_ag, x="VALOR DO ESPELHO", y="AGÊNCIA", orientation="h", template=template)
        fig_ag.update_layout(margin=dict(l=12,r=12,t=10,b=12), xaxis_title=None, yaxis_title=None)
    else:
        fig_ag = go.Figure()

    # 4) Treemap
    if not df_f.empty:
        tre = (
            df_f.groupby(["SECRETARIA","AGÊNCIA"], as_index=False)["VALOR DO ESPELHO"].sum()
        )
        fig_tre = px.treemap(tre, path=["SECRETARIA","AGÊNCIA"], values="VALOR DO ESPELHO", template=template)
        fig_tre.update_layout(margin=dict(l=12,r=12,t=10,b=12))
    else:
        fig_tre = go.Figure()

    # 5) Campanhas por valor (Top 20)
    if not df_f.empty:
        camp = (
            df_f.groupby("CAMPANHA", as_index=False)["VALOR DO ESPELHO"].sum()
            .sort_values("VALOR DO ESPELHO", ascending=False).head(20)
        )
        fig_ca = px.bar(camp, x="VALOR DO ESPELHO", y="CAMPANHA", orientation="h", template=template)
        fig_ca.update_layout(margin=dict(l=12,r=12,t=10,b=12), xaxis_title=None, yaxis_title=None)
    else:
        fig_ca = go.Figure()

    # Tabela
    if not df_f.empty:
        df_tbl = df_f.copy()
        # colunas markdown de links
        df_tbl["PROCESSO_MD"] = df_tbl["PROCESSO"].apply(lambda u: _mk_link_md(u, "Processo"))
        df_tbl["EMPENHO_MD"] = df_tbl["EMPENHO"].apply(lambda u: _mk_link_md(u, "Empenho"))
        df_tbl["ESPELHO DIANA_MD"] = df_tbl["ESPELHO DIANA"].apply(lambda u: _mk_link_md(u, "Diana"))
        df_tbl["ESPELHO_MD"] = df_tbl["ESPELHO"].apply(lambda u: _mk_link_md(u, "Espelho"))
        df_tbl["PDF_MD"] = df_tbl["PDF"].apply(lambda u: _mk_link_md(u, "PDF"))

        # Seleção final de colunas exibidas
        cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR (BRL)","PROCESSO_MD","EMPENHO_MD","DATA DO EMPENHO",
                "COMPETENCIA_MES","OBSERVAÇÃO","ESPELHO DIANA_MD","ESPELHO_MD","PDF_MD"]
        cols = [c for c in cols if c in df_tbl.columns]
        data_tbl = df_tbl[cols].fillna("").to_dict("records")
    else:
        data_tbl = []

    return k1, k2, k3, k4, fig_evo, fig_se, fig_ag, fig_tre, fig_ca, data_tbl


# Atualiza opções da Dropdown de abas quando clicar em "Atualizar" ou quando a URL muda
@app.callback(
    Output("f_sheet","options"),
    Input("btn_refresh","n_clicks"),
    Input("excel_url","value"),
    prevent_initial_call=False
)
def refresh_sheet_list(n_clicks, url):
    url = url or DEFAULT_SHEETS_URL
    try:
        names = _sheet_names_from_url(url)
        return [{"label": s, "value": s} for s in names]
    except Exception:
        # mantém opções atuais caso dê erro
        raise dash.exceptions.PreventUpdate


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
