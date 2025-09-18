
import os
import io
import re
from datetime import datetime
import unicodedata
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update

# -----------------------------------------------------------------------------
# Configuração: URL da planilha (pode vir por ENV no Render)
# -----------------------------------------------------------------------------
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx&id=1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc"
)
EXCEL_URL = os.environ.get("EXCEL_URL", DEFAULT_SHEET_URL).strip()

# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    if not isinstance(s, str):
        s = "" if pd.isna(s) else str(s)
    return ''.join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def _normalize_col(col: str) -> str:
    """Normaliza nome de coluna para comparar/match mais fácil."""
    col = _strip_accents(col).upper().strip()
    col = re.sub(r"\s+", " ", col)
    return col

def _normalize_excel_url(url: str) -> str:
    """
    Aceita link de edição ou de export e retorna URL no formato export XLSX.
    Ex.: https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0  -> export?format=xlsx&id=<ID>
    """
    url = url.strip()
    # já está em export? Só garante format=xlsx
    if "/export" in url:
        # força format=xlsx
        url = re.sub(r"format=[a-zA-Z0-9_]+", "format=xlsx", url)
        # garante que tem id
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
        if m and "id=" not in url:
            url += ("&" if "?" in url else "?") + f"id={m.group(1)}"
        return url

    # tenta extrair o file_id de uma URL /spreadsheets/d/<ID>/...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if m:
        file_id = m.group(1)
        return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx&id={file_id}"

    # Se cair aqui, retorna como veio (pode ser uma URL direta já válida)
    return url

def _download_excel_bytes(url: str) -> bytes:
    """Baixa a planilha como XLSX e retorna os bytes. Levanta erro com mensagem clara se falhar."""
    norm = _normalize_excel_url(url)
    try:
        r = requests.get(norm, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"Falha ao baixar planilha (HTTP {r.status_code}). Verifique o compartilhamento público 'Qualquer pessoa com o link' e o formato de export.")
        # Google às vezes retorna HTML (login) se permissão não estiver pública
        content_type = r.headers.get("Content-Type", "")
        if "text/html" in content_type.lower() and not norm.lower().endswith(".xlsx"):
            raise RuntimeError("Recebi HTML em vez de XLSX. Ajuste o link para 'Exportar' e habilite 'Qualquer pessoa com o link'.")
        return r.content
    except Exception as e:
        raise RuntimeError(f"Erro ao acessar a planilha: {e}")

# -----------------------------------------------------------------------------
# Carregamento & padronização de dados
# -----------------------------------------------------------------------------
COL_ALIASES = {
    "CAMPANHA": ["CAMPANHA", "NOME DA CAMPANHA", "CAMPANHAS"],
    "SECRETARIA": ["SECRETARIA", "ÓRGÃO", "ORGAO", "SED"],
    "AGÊNCIA": ["AGENCIA", "AGÊNCIA", "AGENCIA/AGENCIA", "AGENCIA / AGENCIA", "AGENCIA / AGÊNCIA"],
    "VALOR DO ESPELHO": ["VALOR DO ESPELHO", "VALOR", "VALOR TOTAL", "VALOR_ESPELHO"],
    "PROCESSO": ["PROCESSO", "Nº PROCESSO", "NUMERO DO PROCESSO", "Nº DO PROCESSO"],
    "EMPENHO": ["EMPENHO", "Nº EMPENHO", "NUMERO DO EMPENHO"],
    "DATA DO EMPENHO": ["DATA DO EMPENHO", "DT EMPENHO", "DATA EMPENHO"],
    "COMPETÊNCIA_DT": ["COMPETENCIA_DT", "COMPETÊNCIA_DT", "COMPETENCIA DATA", "COMPETENCIA DATA (DT)"],
    "COMPETÊNCIA_TXT": ["COMPETENCIA", "COMPETÊNCIA", "COMPETENCIA_TXT", "MES/ANO", "MÊS/ANO"],
    "OBSERVAÇÃO": ["OBSERVACAO", "OBSERVAÇÃO", "OBS", "JUSTIFICATIVA"],
    "ESPELHO DIANA": ["ESPELHO DIANA", "DIANA", "LINK DIANA"],
    "ESPELHO": ["ESPELHO", "LINK ESPELHO", "LINK RELATORIO"],
    "PDF": ["PDF", "LINK PDF", "RELATORIO PDF"],
    # Colunas extras úteis
    "COMPETÊNCIA_MES": [],
}

TARGET_ORDER = [
    "CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO",
    "PROCESSO","EMPENHO","DATA DO EMPENHO","COMPETÊNCIA",
    "OBSERVAÇÃO","ESPELHO DIANA","ESPELHO","PDF"
]

def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia colunas para o alvo padrão considerando aliases."""
    current = {c: _normalize_col(c) for c in df.columns}
    rename = {}

    for target, aliases in COL_ALIASES.items():
        found = None
        for col, norm in current.items():
            if norm == target or norm in [_normalize_col(a) for a in aliases]:
                found = col
                break
        if found:
            rename[found] = target

    df = df.rename(columns=rename)

    # COMPETÊNCIA (escolher melhor entre *_DT e *_TXT)
    if "COMPETÊNCIA_DT" in df.columns and "COMPETÊNCIA" not in df.columns:
        df["COMPETÊNCIA"] = df["COMPETÊNCIA_DT"]
    elif "COMPETÊNCIA_TXT" in df.columns and "COMPETÊNCIA" not in df.columns:
        df["COMPETÊNCIA"] = df["COMPETÊNCIA_TXT"]

    # Garante colunas obrigatórias (se não existir, cria vazia)
    for col in TARGET_ORDER:
        if col not in df.columns:
            df[col] = ""

    return df

def _parse_currency(val):
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = s.replace("R$", "").replace("\u00a0", " ").replace(" ", "")
    # Converte formato pt-BR: 1.234.567,89 -> 1234567.89
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def _to_month_start(dt: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=dt.year, month=dt.month, day=1)

def _load_data(url: str) -> pd.DataFrame:
    """Carrega todas as abas da planilha XLSX e concatena; normaliza colunas/valores."""
    raw = _download_excel_bytes(url)
    xl = pd.ExcelFile(io.BytesIO(raw))
    frames = []
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet, dtype=object)
            if df is None or df.empty:
                continue
            frames.append(df)
        except Exception:
            continue
    if not frames:
        raise RuntimeError("A planilha foi baixada, mas não encontrei dados nas abas. Verifique o conteúdo.")

    df = pd.concat(frames, ignore_index=True).copy()

    # Normaliza colunas
    df = _map_columns(df)

    # Tipagens e campos derivados
    df["VALOR DO ESPELHO_NUM"] = df["VALOR DO ESPELHO"].map(_parse_currency)

    # Datas
    for col in ["DATA DO EMPENHO", "COMPETÊNCIA_DT"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    # COMPETÊNCIA via TXT se necessário (ex.: mm/aaaa)
    if "COMPETÊNCIA" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["COMPETÊNCIA"]):
        comp = df["COMPETÊNCIA"].astype(str).str.strip()
        # tenta mm/aaaa
        comp_dt = pd.to_datetime(comp, errors="coerce", format="%m/%Y")
        # fallback: tenta dd/mm/aaaa
        comp_dt2 = pd.to_datetime(comp, errors="coerce", dayfirst=True)
        df["COMPETÊNCIA_DT"] = comp_dt.fillna(comp_dt2)

    # mês de competência (1º dia do mês)
    if "COMPETÊNCIA_DT" in df.columns:
        df["COMPETÊNCIA_MES"] = df["COMPETÊNCIA_DT"].dropna().map(_to_month_start)
    else:
        df["COMPETÊNCIA_MES"] = pd.NaT

    # Exibição BRL formatada
    def fmt_brl(x):
        try:
            return "R$ {:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".")
        except:
            return "R$ 0,00"
    df["VALOR_BR"] = df["VALOR DO ESPELHO_NUM"].map(fmt_brl)

    # Links -> markdown
    def link_md(url, label):
        if not isinstance(url, str):
            url = "" if pd.isna(url) else str(url)
        u = url.strip()
        if u and (u.startswith("http://") or u.startswith("https://")):
            return f"[{label}]({u})"
        return ""

    df["PROCESSO_MD"] = df["PROCESSO"].apply(lambda u: link_md(u, "Processo"))
    df["EMPENHO_MD"] = df["EMPENHO"].apply(lambda u: link_md(u, "Empenho"))
    df["ESPELHO_DIANA_MD"] = df["ESPELHO DIANA"].apply(lambda u: link_md(u, "Diana"))
    df["ESPELHO_MD"] = df["ESPELHO"].apply(lambda u: link_md(u, "Espelho"))
    df["PDF_MD"] = df["PDF"].apply(lambda u: link_md(u, "PDF"))

    # Cast de filtros para string (evita erro de sort entre int/str)
    for c in ["SECRETARIA", "AGÊNCIA", "CAMPANHA"]:
        if c in df.columns:
            df[c] = df[c].astype(str).fillna("").replace("nan","")

    return df

# -----------------------------------------------------------------------------
# Carregar dados iniciais (fallback seguro)
# -----------------------------------------------------------------------------
try:
    DF_BASE = _load_data(EXCEL_URL)
    LOAD_ERROR = ""
except Exception as e:
    DF_BASE = pd.DataFrame(columns=TARGET_ORDER + ["VALOR DO ESPELHO_NUM","COMPETÊNCIA_MES",
                                                   "VALOR_BR","PROCESSO_MD","EMPENHO_MD","ESPELHO_DIANA_MD","ESPELHO_MD","PDF_MD"])
    LOAD_ERROR = str(e)

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

# Tema (claro/escuro) aplicado nos gráficos via layout template
def _plot_theme(theme_value: str) -> dict:
    is_dark = (theme_value == "dark")
    bg = "#0f172a" if is_dark else "#ffffff"
    paper = "#0b1220" if is_dark else "#ffffff"
    grid = "#334155" if is_dark else "#e2e8f0"
    font = "#e2e8f0" if is_dark else "#0f172a"
    return dict(
        plot_bgcolor=bg,
        paper_bgcolor=paper,
        font=dict(color=font),
        xaxis=dict(showgrid=True, gridcolor=grid, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=grid, zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=60, b=40)
    )

def _options_from(df: pd.DataFrame, col: str):
    if col not in df.columns:
        return []
    vals = df[col].fillna("").astype(str).unique().tolist()
    vals = [v for v in vals if v]
    vals.sort(key=lambda x: x.lower())
    return [{"label": v, "value": v} for v in vals]

def _filter_df(df: pd.DataFrame,
               secretarias, agencias, campanhas,
               dt_ini, dt_fim) -> pd.DataFrame:
    out = df.copy()
    if secretarias:
        out = out[out["SECRETARIA"].isin(secretarias)]
    if agencias:
        out = out[out["AGÊNCIA"].isin(agencias)]
    if campanhas:
        out = out[out["CAMPANHA"].isin(campanhas)]
    # período por COMPETÊNCIA_MES
    if "COMPETÊNCIA_MES" in out.columns:
        if dt_ini:
            out = out[out["COMPETÊNCIA_MES"].fillna(pd.NaT) >= pd.to_datetime(dt_ini)]
        if dt_fim:
            out = out[out["COMPETÊNCIA_MES"].fillna(pd.NaT) <= pd.to_datetime(dt_fim)]
    return out

# Layout
app.layout = html.Div(
    [
        # Tema
        dcc.Store(id="store_data"),
        html.Div(
            [
                html.H2("Dashboard SECOM", style={"margin":"0"}),
                html.Div(
                    [
                        html.Label("Tema:"),
                        dcc.RadioItems(
                            id="theme",
                            options=[{"label":"Claro","value":"light"},{"label":"Escuro","value":"dark"}],
                            value="light",
                            inline=True,
                        ),
                        html.Button("Atualizar dados", id="btn_refresh", n_clicks=0, style={"marginLeft":"16px"}),
                        html.Span(id="status_msg", style={"marginLeft":"12px", "fontStyle":"italic"}),
                    ],
                    style={"display":"flex","alignItems":"center","gap":"12px"}
                ),
                html.Div(
                    LOAD_ERROR and f"Aviso: {LOAD_ERROR}" or "",
                    id="load_warn",
                    style={"color":"#ef4444","marginTop":"6px"}
                ),
            ],
            style={"display":"flex","flexDirection":"column","gap":"8px","marginBottom":"12px"}
        ),

        # Filtros
        html.Div(
            [
                html.Div([
                    html.Label("Secretaria"),
                    dcc.Dropdown(id="f_secretaria", options=_options_from(DF_BASE, "SECRETARIA"), multi=True, placeholder="Todas"),
                ], style={"flex":1}),
                html.Div([
                    html.Label("Agência"),
                    dcc.Dropdown(id="f_agencia", options=_options_from(DF_BASE, "AGÊNCIA"), multi=True, placeholder="Todas"),
                ], style={"flex":1}),
                html.Div([
                    html.Label("Campanha"),
                    dcc.Dropdown(id="f_campanha", options=_options_from(DF_BASE, "CAMPANHA"), multi=True, placeholder="Todas"),
                ], style={"flex":1}),
                html.Div([
                    html.Label("Período (Competência)"),
                    dcc.DatePickerRange(
                        id="f_periodo",
                        min_date_allowed= (DF_BASE["COMPETÊNCIA_MES"].min().to_pydatetime() if "COMPETÊNCIA_MES" in DF_BASE and DF_BASE["COMPETÊNCIA_MES"].notna().any() else None),
                        max_date_allowed= (DF_BASE["COMPETÊNCIA_MES"].max().to_pydatetime() if "COMPETÊNCIA_MES" in DF_BASE and DF_BASE["COMPETÊNCIA_MES"].notna().any() else None),
                        start_date= (DF_BASE["COMPETÊNCIA_MES"].min().to_pydatetime() if "COMPETÊNCIA_MES" in DF_BASE and DF_BASE["COMPETÊNCIA_MES"].notna().any() else None),
                        end_date= (DF_BASE["COMPETÊNCIA_MES"].max().to_pydatetime() if "COMPETÊNCIA_MES" in DF_BASE and DF_BASE["COMPETÊNCIA_MES"].notna().any() else None),
                    ),
                ], style={"flex":1, "minWidth":"280px"}),
            ],
            style={"display":"grid","gridTemplateColumns":"repeat(4, 1fr)","gap":"12px","marginBottom":"16px"}
        ),

        # KPIs
        html.Div(
            [
                html.Div([html.Div("Valor total"), html.H3(id="kpi_total")], className="card"),
                html.Div([html.Div("Registros"), html.H3(id="kpi_regs")], className="card"),
                html.Div([html.Div("Secretarias"), html.H3(id="kpi_secs")], className="card"),
                html.Div([html.Div("Agências"), html.H3(id="kpi_agcs")], className="card"),
            ],
            style={"display":"grid","gridTemplateColumns":"repeat(4, 1fr)","gap":"12px","marginBottom":"12px"}
        ),

        # Gráficos
        html.Div(
            [
                dcc.Graph(id="g_evolucao"),
                dcc.Graph(id="g_secretarias"),
                dcc.Graph(id="g_agencias"),
                dcc.Graph(id="g_treemap"),
                dcc.Graph(id="g_pareto"),
            ],
            style={"display":"grid","gridTemplateColumns":"1fr","gap":"12px","marginBottom":"16px"}
        ),

        # Tabela detalhada
        html.Div(
            [
                html.H3("Dados detalhados"),
                dash_table.DataTable(
                    id="tbl",
                    columns=[
                        {"name":"CAMPANHA","id":"CAMPANHA"},
                        {"name":"SECRETARIA","id":"SECRETARIA"},
                        {"name":"AGÊNCIA","id":"AGÊNCIA"},
                        {"name":"VALOR DO ESPELHO","id":"VALOR_BR"},
                        {"name":"PROCESSO","id":"PROCESSO_MD","presentation":"markdown"},
                        {"name":"EMPENHO","id":"EMPENHO_MD","presentation":"markdown"},
                        {"name":"DATA DO EMPENHO","id":"DATA DO EMPENHO"},
                        {"name":"COMPETÊNCIA","id":"COMPETÊNCIA"},
                        {"name":"OBSERVAÇÃO","id":"OBSERVAÇÃO"},
                        {"name":"ESPELHO DIANA","id":"ESPELHO_DIANA_MD","presentation":"markdown"},
                        {"name":"ESPELHO","id":"ESPELHO_MD","presentation":"markdown"},
                        {"name":"PDF","id":"PDF_MD","presentation":"markdown"},
                    ],
                    data=[],
                    page_size=12,
                    sort_action="native",
                    filter_action="native",
                    style_table={"overflowX":"auto"},
                    style_header={"fontWeight":"600"},
                    style_cell={"fontSize":"14px", "padding":"6px"},
                    markdown_options={"link_target":"_blank"},
                ),
            ]
        ),

        html.Div(id="_dummy")  # âncora para callbacks sem output visual adicional
    ],
    style={"padding":"16px", "maxWidth":"1400px", "margin":"0 auto", "fontFamily":"system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"}
)

# -----------------------------------------------------------------------------
# Callbacks
# -----------------------------------------------------------------------------
@app.callback(
    Output("store_data","data"),
    Output("status_msg","children"),
    Output("load_warn","children"),
    Input("btn_refresh","n_clicks"),
    prevent_initial_call=False
)
def refresh_data(n_clicks):
    """Faz o download mais recente da planilha ao abrir e ao clicar no botão."""
    try:
        df = _load_data(EXCEL_URL)
        warn = ""
        msg = f"Dados atualizados em {datetime.now().strftime('%d/%m/%Y %H:%M')}."
        return df.to_json(date_format="iso", orient="split"), msg, warn
    except Exception as e:
        warn = f"Não foi possível atualizar os dados: {e}"
        # devolve DF_BASE inicial para não quebrar
        return DF_BASE.to_json(date_format="iso", orient="split"), "", warn

@app.callback(
    Output("kpi_total","children"),
    Output("kpi_regs","children"),
    Output("kpi_secs","children"),
    Output("kpi_agcs","children"),
    Output("g_evolucao","figure"),
    Output("g_secretarias","figure"),
    Output("g_agencias","figure"),
    Output("g_treemap","figure"),
    Output("g_pareto","figure"),
    Output("tbl","data"),
    Input("store_data","data"),
    Input("f_secretaria","value"),
    Input("f_agencia","value"),
    Input("f_campanha","value"),
    Input("f_periodo","start_date"),
    Input("f_periodo","end_date"),
    Input("theme","value"),
)
def update_views(store_json, sec_v, agc_v, camp_v, d_ini, d_fim, theme):
    theme_layout = _plot_theme(theme)

    if store_json:
        df = pd.read_json(store_json, orient="split")
    else:
        df = DF_BASE.copy()

    # Filtra
    df_f = _filter_df(df, sec_v, agc_v, camp_v, d_ini, d_fim)

    # KPIs
    total_val = float(df_f["VALOR DO ESPELHO_NUM"].sum()) if "VALOR DO ESPELHO_NUM" in df_f else 0.0
    def fmt_brl(x):
        return "R$ {:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".")
    k_total = fmt_brl(total_val)
    k_regs = f"{len(df_f):,}".replace(",", ".")
    k_secs = f"{df_f['SECRETARIA'].nunique() if 'SECRETARIA' in df_f.columns else 0:,}".replace(",", ".")
    k_agcs = f"{df_f['AGÊNCIA'].nunique() if 'AGÊNCIA' in df_f.columns else 0:,}".replace(",", ".")

    # Gráfico 1: Evolução mensal
    if "COMPETÊNCIA_MES" in df_f.columns and df_f["COMPETÊNCIA_MES"].notna().any():
        evol = (df_f.dropna(subset=["COMPETÊNCIA_MES"])
                    .groupby("COMPETÊNCIA_MES", as_index=False)["VALOR DO ESPELHO_NUM"].sum()
                    .sort_values("COMPETÊNCIA_MES"))
        fig_evo = px.area(evol, x="COMPETÊNCIA_MES", y="VALOR DO ESPELHO_NUM", title="Evolução mensal do valor")
        fig_evo.update_layout(**theme_layout, yaxis_title="Valor (R$)", xaxis_title="Competência")
    else:
        fig_evo = go.Figure().update_layout(title="Evolução mensal do valor (sem dados)", **theme_layout)

    # Gráfico 2: Top 10 Secretarias
    if "SECRETARIA" in df_f.columns:
        sec = (df_f.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO_NUM"].sum()
                    .sort_values("VALOR DO ESPELHO_NUM", ascending=False).head(10))
        fig_sec = px.bar(sec, x="VALOR DO ESPELHO_NUM", y="SECRETARIA", orientation="h", title="Top 10 Secretarias por valor")
        fig_sec.update_layout(**theme_layout, xaxis_title="Valor (R$)", yaxis_title="")
    else:
        fig_sec = go.Figure().update_layout(title="Top 10 Secretarias (sem dados)", **theme_layout)

    # Gráfico 3: Top 10 Agências
    if "AGÊNCIA" in df_f.columns:
        agc = (df_f.groupby("AGÊNCIA", as_index=False)["VALOR DO ESPELHO_NUM"].sum()
                    .sort_values("VALOR DO ESPELHO_NUM", ascending=False).head(10))
        fig_agc = px.bar(agc, x="VALOR DO ESPELHO_NUM", y="AGÊNCIA", orientation="h", title="Top 10 Agências por valor")
        fig_agc.update_layout(**theme_layout, xaxis_title="Valor (R$)", yaxis_title="")
    else:
        fig_agc = go.Figure().update_layout(title="Top 10 Agências (sem dados)", **theme_layout)

    # Gráfico 4: Treemap Secretaria -> Agência
    if "SECRETARIA" in df_f.columns and "AGÊNCIA" in df_f.columns:
        tree = df_f.groupby(["SECRETARIA","AGÊNCIA"], as_index=False)["VALOR DO ESPELHO_NUM"].sum()
        fig_tree = px.treemap(tree, path=["SECRETARIA","AGÊNCIA"], values="VALOR DO ESPELHO_NUM", title="Proporção por Secretaria → Agência")
        fig_tree.update_layout(**theme_layout, margin=dict(l=0,r=0,t=60,b=0))
    else:
        fig_tree = go.Figure().update_layout(title="Treemap (sem dados)", **theme_layout)

    # Gráfico 5: Campanhas por valor (pareto / barras ordenadas)
    if "CAMPANHA" in df_f.columns:
        camp = (df_f.groupby("CAMPANHA", as_index=False)["VALOR DO ESPELHO_NUM"].sum()
                    .sort_values("VALOR DO ESPELHO_NUM", ascending=False).head(20))
        fig_par = px.bar(camp, x="CAMPANHA", y="VALOR DO ESPELHO_NUM", title="Campanhas por valor (Top 20)")
        fig_par.update_layout(**theme_layout, yaxis_title="Valor (R$)", xaxis_title="", xaxis={'tickangle': -30})
    else:
        fig_par = go.Figure().update_layout(title="Campanhas por valor (sem dados)", **theme_layout)

    # Tabela detalhada
    tbl_cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR_BR","PROCESSO_MD","EMPENHO_MD","DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO","ESPELHO_DIANA_MD","ESPELHO_MD","PDF_MD"]
    view = df_f.copy()
    # formata datas para exibição
    for c in ["DATA DO EMPENHO","COMPETÊNCIA"]:
        if c in view.columns:
            view[c] = pd.to_datetime(view[c], errors="coerce", dayfirst=True).dt.strftime("%d/%m/%Y")
    data_tbl = view[tbl_cols].fillna("").to_dict("records")

    return k_total, k_regs, k_secs, k_agcs, fig_evo, fig_sec, fig_agc, fig_tree, fig_par, data_tbl

# -----------------------------------------------------------------------------
# Estilos básicos
# -----------------------------------------------------------------------------
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Dashboard SECOM</title>
        {%css%}
        <style>
            body { background: #ffffff; color: #0f172a; }
            .card {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 12px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            }
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td, 
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
                border-color: #e2e8f0;
            }
            label { font-weight: 600; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
        </footer>
    </body>
</html>
"""

if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "8050")))
