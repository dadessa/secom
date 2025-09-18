# dashboard_secom.py
import os
import io
import re
import time
import unicodedata
import requests
import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context

# -------------------------------------------------------------------
# CONFIGURAÇÕES
# -------------------------------------------------------------------
# 1) Caminho/URL da planilha. Pode ser local ou Google Sheets (export xlsx).
#    Ex.: https://docs.google.com/spreadsheets/d/<ID>/export?format=xlsx
EXCEL_SOURCE = os.environ.get(
    "EXCEL_PATH",
    # Coloque aqui seu link exportável se quiser deixar fixo por env:
    "https://docs.google.com/spreadsheets/d/1yox2YBeCCQd6nt-zhMDjG2CjC29ImgrtQpBlPpA5tpc/export?format=xlsx"
)

# 2) Cache simples (em memória) para evitar baixar/carregar a cada interação
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "180"))  # 3 min
_CACHE = {"ts": 0.0, "sheets": {}, "order": []}

# -------------------------------------------------------------------
# FUNÇÕES DE APOIO (limpeza/conversão)
# -------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    if not isinstance(s, str):
        return s
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _norm_col(c: str) -> str:
    """Normaliza nomes de colunas para UPPER, remove acentos e espaços extras."""
    if not isinstance(c, str):
        return c
    c = c.strip()
    c = _strip_accents(c)
    c = re.sub(r"\s+", " ", c)
    return c.upper()

def _br_to_float(x):
    """Converte strings pt-BR como '1.234.567,89' -> 1234567.89."""
    if isinstance(x, (int, float, np.number)):
        return float(x)
    if not isinstance(x, str):
        return np.nan
    s = x.strip()
    if s == "":
        return np.nan
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return np.nan

def _ensure_dt(series: pd.Series):
    """Tenta converter a série em datetime (dayfirst=True)."""
    try:
        return pd.to_datetime(series, errors="coerce", dayfirst=True)
    except Exception:
        return pd.to_datetime(series, errors="coerce")

def _guess_competencia(df: pd.DataFrame) -> pd.Series:
    """
    Retorna uma série datetime representando a competência (mês),
    procurando por colunas usuais.
    """
    candidates = [
        "COMPETENCIA_DT", "COMPETENCIA", "COMPETENCIA_TXT", "MES", "MÊS",
        "COMPETENCIA (TEXTO)", "PERIODO", "PERÍODO"
    ]
    cols_upper = {c: _norm_col(c) for c in df.columns}
    inv_map = {v: k for k, v in cols_upper.items()}

    # Tenta algumas chaves normalizadas
    for key in ["COMPETENCIA_DT", "COMPETENCIA", "COMPETENCIA_TXT", "MES", "MÊS", "PERIODO", "PERÍODO"]:
        if key in inv_map:
            raw = df[inv_map[key]]
            # Se já for datetime-like
            out = pd.to_datetime(raw, errors="coerce", dayfirst=True)
            if out.notna().any():
                # Reduz para o 1º dia do mês
                return out.dt.to_period("M").dt.to_timestamp()
            # Se vier como texto tipo '05/2025' ou '2025-05'
            # tenta parse manual
            parsed = pd.to_datetime(raw.astype(str).str.replace(r"[^\d/-]", "", regex=True),
                                    errors="coerce")
            if parsed.notna().any():
                return parsed.dt.to_period("M").dt.to_timestamp()

    # Se nada encontrado, cria uma coluna nula
    return pd.to_datetime(pd.Series([pd.NaT] * len(df)))

def _format_brl(x):
    try:
        if pd.isna(x):
            return ""
        return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return ""

def _to_markdown_link(url: str, label: str):
    if not isinstance(url, str):
        return ""
    u = url.strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, flags=re.I):
        return ""
    return f"[{label}]({u})"

# -------------------------------------------------------------------
# CARREGAMENTO DA PLANILHA (com cache)
# -------------------------------------------------------------------
def _download_excel_bytes(src: str) -> bytes:
    if re.match(r"^https?://", src, flags=re.I):
        # Baixa via requests
        r = requests.get(src, timeout=30)
        r.raise_for_status()
        return r.content
    # Caminho local
    with open(src, "rb") as f:
        return f.read()

def _load_all_sheets(force=False) -> tuple[dict, list]:
    """
    Lê todas as abas e retorna:
      - dict: {nome_aba: DataFrame_limpo}
      - ordem_das_abas: list[str]
    Usa cache simples por TTL.
    """
    now = time.time()
    if not force and (now - _CACHE["ts"] <= CACHE_TTL_SECONDS) and _CACHE["sheets"]:
        return _CACHE["sheets"], _CACHE["order"]

    xbytes = _download_excel_bytes(EXCEL_SOURCE)
    xl = pd.ExcelFile(io.BytesIO(xbytes))
    sheets = {}
    order = []
    for sheet_name in xl.sheet_names:
        df_raw = xl.parse(sheet_name)
        if df_raw is None or df_raw.empty:
            continue

        # Normaliza nomes
        df = df_raw.copy()
        df.columns = [_norm_col(c) for c in df.columns]

        # Tenta identificar colunas principais por nome "canônico"
        # Valor
        valor_col = None
        for c in df.columns:
            if "VALOR" in c and "ESPELHO" in c:
                valor_col = c
                break
        if valor_col is None:
            # fallback: qualquer coluna com "VALOR"
            val_like = [c for c in df.columns if "VALOR" in c]
            valor_col = val_like[0] if val_like else None

        # Secretaria / Agência / Campanha
        secretaria_col = next((c for c in df.columns if c == "SECRETARIA"), None)
        agencia_col = next((c for c in df.columns if "AGENCIA" in c), None)
        campanha_col = next((c for c in df.columns if "CAMPANHA" in c), None)

        # Datas
        data_empenho_col = next((c for c in df.columns if "DATA" in c and "EMPENHO" in c), None)

        # Links possíveis
        processo_col = next((c for c in df.columns if "PROCESSO" in c), None)
        empenho_link_col = next((c for c in df.columns if c == "EMPENHO"), None)
        diana_col = next((c for c in df.columns if "DIANA" in c), None)
        espelho_col = next((c for c in df.columns if c == "ESPELHO"), None)
        pdf_col = next((c for c in df.columns if "PDF" in c), None)

        # Calcula COMPETÊNCIA (mês) se existir algo parecido
        competencia_dt = _guess_competencia(df)

        # Converte valor numérico
        if valor_col:
            df["__VALOR_NUM__"] = df[valor_col].apply(_br_to_float)
        else:
            df["__VALOR_NUM__"] = np.nan

        # Prepara colunas padronizadas para o app (se não existirem, cria vazias)
        def col_or_empty(col):
            return df[col] if col in df.columns else ""

        df_clean = pd.DataFrame({
            "CAMPANHA": col_or_empty(campanha_col),
            "SECRETARIA": col_or_empty(secretaria_col),
            "AGÊNCIA": col_or_empty(agencia_col) if agencia_col else col_or_empty("AGENCIA"),
            "VALOR DO ESPELHO": df["__VALOR_NUM__"],
            "PROCESSO": col_or_empty(processo_col),
            "EMPENHO": col_or_empty(empenho_link_col),
            "DATA DO EMPENHO": _ensure_dt(col_or_empty(data_empenho_col)),
            "COMPETÊNCIA": competencia_dt,
            "OBSERVAÇÃO": col_or_empty("OBSERVACAO") if "OBSERVACAO" in df.columns else col_or_empty("OBSERVAÇÃO"),
            "ESPELHO DIANA": col_or_empty(diana_col),
            "ESPELHO": col_or_empty(espelho_col),
            "PDF": col_or_empty(pdf_col),
        })

        # Formata coluna BRL para exibição
        df_clean["VALOR DO ESPELHO (BRL)"] = df_clean["VALOR DO ESPELHO"].apply(_format_brl)

        # Links como markdown
        df_clean["PROCESSO"] = df_clean["PROCESSO"].apply(lambda u: _to_markdown_link(u, "Processo"))
        df_clean["EMPENHO"] = df_clean["EMPENHO"].apply(lambda u: _to_markdown_link(u, "Empenho"))
        df_clean["ESPELHO DIANA"] = df_clean["ESPELHO DIANA"].apply(lambda u: _to_markdown_link(u, "Diana"))
        df_clean["ESPELHO"] = df_clean["ESPELHO"].apply(lambda u: _to_markdown_link(u, "Espelho"))
        df_clean["PDF"] = df_clean["PDF"].apply(lambda u: _to_markdown_link(u, "PDF"))

        # Ordena colunas da tabela detalhada
        df_clean = df_clean[
            [
                "CAMPANHA",
                "SECRETARIA",
                "AGÊNCIA",
                "VALOR DO ESPELHO",          # numérica (para gráficos)
                "VALOR DO ESPELHO (BRL)",    # exibida
                "PROCESSO",
                "EMPENHO",
                "DATA DO EMPENHO",
                "COMPETÊNCIA",
                "OBSERVAÇÃO",
                "ESPELHO DIANA",
                "ESPELHO",
                "PDF",
            ]
        ]

        sheets[sheet_name] = df_clean
        order.append(sheet_name)

    _CACHE["ts"] = time.time()
    _CACHE["sheets"] = sheets
    _CACHE["order"] = order
    return sheets, order

def _get_df(aba: str, force=False) -> pd.DataFrame:
    sheets, _ = _load_all_sheets(force=force)
    if not sheets:
        return pd.DataFrame()
    if aba in sheets:
        return sheets[aba]
    # fallback: primeira aba
    return sheets[next(iter(sheets))]

# -------------------------------------------------------------------
# GERAÇÃO DOS GRÁFICOS
# -------------------------------------------------------------------
def fig_evolucao_mensal(df: pd.DataFrame):
    s = df.copy()
    if "COMPETÊNCIA" not in s.columns:
        return px.line(title="Evolução mensal (sem COMPETÊNCIA)")

    agg = (
        s.groupby(s["COMPETÊNCIA"].dt.to_period("M").dt.to_timestamp(), as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("COMPETÊNCIA")
    )
    if agg.empty:
        return px.line(title="Evolução mensal (sem dados)")
    fig = px.area(
        agg,
        x="COMPETÊNCIA",
        y="VALOR DO ESPELHO",
        title="Evolução mensal (soma de VALOR DO ESPELHO)"
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=280)
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return fig

def fig_top10_secretarias(df: pd.DataFrame):
    s = df.copy()
    if "SECRETARIA" not in s.columns:
        return px.bar(title="Top 10 Secretarias (coluna ausente)")
    agg = (
        s.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("VALOR DO ESPELHO", ascending=False)
        .head(10)
    )
    if agg.empty:
        return px.bar(title="Top 10 Secretarias (sem dados)")
    fig = px.bar(
        agg.sort_values("VALOR DO ESPELHO"),
        x="VALOR DO ESPELHO",
        y="SECRETARIA",
        orientation="h",
        title="Top 10 Secretarias (por valor)"
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=280)
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return fig

def fig_top10_agencias(df: pd.DataFrame):
    s = df.copy()
    col = "AGÊNCIA" if "AGÊNCIA" in s.columns else ("AGENCIA" if "AGENCIA" in s.columns else None)
    if not col:
        return px.bar(title="Top 10 Agências (coluna ausente)")
    agg = (
        s.groupby(col, as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("VALOR DO ESPELHO", ascending=False)
        .head(10)
    )
    if agg.empty:
        return px.bar(title="Top 10 Agências (sem dados)")
    fig = px.bar(
        agg.sort_values("VALOR DO ESPELHO"),
        x="VALOR DO ESPELHO",
        y=col,
        orientation="h",
        title="Top 10 Agências (por valor)"
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=280)
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return fig

def fig_treemap_sec_ag(df: pd.DataFrame):
    s = df.copy()
    sec = "SECRETARIA" if "SECRETARIA" in s.columns else None
    ag = "AGÊNCIA" if "AGÊNCIA" in s.columns else ("AGENCIA" if "AGENCIA" in s.columns else None)
    if not sec or not ag:
        return px.treemap(title="Treemap (SECRETARIA→AGÊNCIA) - colunas ausentes")
    # Para evitar labels vazios
    s[sec] = s[sec].replace({None: "—", np.nan: "—", "": "—"})
    s[ag] = s[ag].replace({None: "—", np.nan: "—", "": "—"})
    agg = s.groupby([sec, ag], as_index=False)["VALOR DO ESPELHO"].sum()
    if agg.empty:
        return px.treemap(title="Treemap (sem dados)")
    fig = px.treemap(
        agg,
        path=[sec, ag],
        values="VALOR DO ESPELHO",
        title="Treemap hierárquico (Secretaria → Agência)"
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=340)
    return fig

def fig_campanhas_valor(df: pd.DataFrame):
    s = df.copy()
    if "CAMPANHA" not in s.columns:
        return px.bar(title="Campanhas por valor (coluna ausente)")
    agg = (
        s.groupby("CAMPANHA", as_index=False)["VALOR DO ESPELHO"]
        .sum()
        .sort_values("VALOR DO ESPELHO", ascending=False)
        .head(15)
    )
    if agg.empty:
        return px.bar(title="Campanhas por valor (sem dados)")
    fig = px.bar(
        agg.sort_values("VALOR DO ESPELHO"),
        x="VALOR DO ESPELHO",
        y="CAMPANHA",
        orientation="h",
        title="Campanhas por valor (Top 15)"
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=340)
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return fig

# -------------------------------------------------------------------
# APP
# -------------------------------------------------------------------
app = Dash(__name__)
server = app.server

# Carrega uma vez para montar opções da dropdown
_sheets, _order = _load_all_sheets(force=True)
aba_default = _order[0] if _order else None

def _sidebar():
    return html.Div(
        id="sidebar",
        style={
            "width": "320px",
            "minWidth": "320px",
            "padding": "16px",
            "borderRight": "1px solid #e5e7eb",
            "background": "#ffffff",  # tema claro padrão
            "position": "sticky",
            "top": 0,
            "height": "100vh",
            "overflowY": "auto",
        },
        children=[
            html.H2("Filtros", style={"margin": "0 0 12px 0", "fontSize": "20px"}),
            html.Label("Aba da planilha", style={"fontWeight": 600, "fontSize": "14px"}),
            dcc.Dropdown(
                id="f_aba",
                options=[{"label": s, "value": s} for s in _order],
                value=aba_default,
                placeholder="Selecione a aba...",
                clearable=False,
                style={"marginBottom": "16px"},
            ),
            html.Button(
                "Atualizar dados",
                id="btn_refresh",
                n_clicks=0,
                style={
                    "width": "100%",
                    "padding": "10px 12px",
                    "border": "1px solid #e5e7eb",
                    "borderRadius": "10px",
                    "background": "#f9fafb",
                    "cursor": "pointer",
                    "fontWeight": 600,
                },
                title="Recarrega a planilha da fonte (pode levar alguns segundos)",
            ),
            html.Div(id="status_refresh", style={"marginTop": "10px", "fontSize": "12px", "color": "#6b7280"}),
            html.Hr(style={"margin": "16px 0"}),
            html.P(
                "Tema padrão: Claro",
                style={"fontSize": "12px", "color": "#6b7280", "margin": 0},
            ),
        ],
    )

def _card(title, graph_id, height=280):
    return html.Div(
        style={
            "background": "#ffffff",
            "border": "1px solid #e5e7eb",
            "borderRadius": "14px",
            "padding": "12px",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
        },
        children=[
            html.Div(title, style={"fontWeight": 700, "marginBottom": "6px"}),
            dcc.Graph(id=graph_id, style={"height": f"{height}px"}, config={"displaylogo": False}),
        ],
    )

def _content():
    return html.Div(
        id="content",
        style={
            "flex": 1,
            "padding": "16px",
            "background": "#f8fafc",
            "minHeight": "100vh",
            "overflowX": "hidden",
        },
        children=[
            html.Div(
                style={"display": "flex", "alignItems": "baseline", "gap": "12px", "marginBottom": "12px"},
                children=[
                    html.H1("Dashboard SECOM", style={"margin": 0, "fontSize": "22px"}),
                    html.Div(id="badge_aba", style={"fontSize": "12px", "color": "#6b7280"}),
                ],
            ),
            # Linha 1
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginBottom": "12px"},
                children=[
                    _card("Evolução mensal", "g_evolucao", height=280),
                    _card("Top 10 Secretarias", "g_sec", height=280),
                ],
            ),
            # Linha 2
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px", "marginBottom": "12px"},
                children=[
                    _card("Top 10 Agências", "g_ag", height=280),
                    _card("Treemap Secretaria → Agência", "g_treemap", height=340),
                ],
            ),
            # Linha 3
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1fr", "gap": "12px", "marginBottom": "12px"},
                children=[_card("Campanhas por valor", "g_campanhas", height=340)],
            ),
            # Tabela
            html.Div(
                style={
                    "background": "#ffffff",
                    "border": "1px solid #e5e7eb",
                    "borderRadius": "14px",
                    "padding": "12px",
                    "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
                },
                children=[
                    html.Div("Tabela detalhada", style={"fontWeight": 700, "marginBottom": "6px"}),
                    dash_table.DataTable(
                        id="tbl",
                        columns=[
                            {"name": "CAMPANHA", "id": "CAMPANHA"},
                            {"name": "SECRETARIA", "id": "SECRETARIA"},
                            {"name": "AGÊNCIA", "id": "AGÊNCIA"},
                            {"name": "VALOR DO ESPELHO (BRL)", "id": "VALOR DO ESPELHO (BRL)"},
                            {"name": "PROCESSO", "id": "PROCESSO", "presentation": "markdown"},
                            {"name": "EMPENHO", "id": "EMPENHO", "presentation": "markdown"},
                            {"name": "DATA DO EMPENHO", "id": "DATA DO EMPENHO"},
                            {"name": "COMPETÊNCIA", "id": "COMPETÊNCIA"},
                            {"name": "OBSERVAÇÃO", "id": "OBSERVAÇÃO"},
                            {"name": "ESPELHO DIANA", "id": "ESPELHO DIANA", "presentation": "markdown"},
                            {"name": "ESPELHO", "id": "ESPELHO", "presentation": "markdown"},
                            {"name": "PDF", "id": "PDF", "presentation": "markdown"},
                        ],
                        data=[],
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto", "maxHeight": "520px", "overflowY": "auto"},
                        style_header={"fontWeight": "700", "background": "#f1f5f9"},
                        style_cell={
                            "fontFamily": "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial",
                            "fontSize": "12px",
                            "padding": "8px",
                            "borderBottom": "1px solid #f1f5f9",
                            "whiteSpace": "nowrap",
                            "textOverflow": "ellipsis",
                            "maxWidth": 320,
                        },
                        style_data_conditional=[
                            {
                                "if": {"column_id": "VALOR DO ESPELHO (BRL)"},
                                "textAlign": "right",
                                "fontVariantNumeric": "tabular-nums",
                            }
                        ],
                        markdown_options={"link_target": "_blank"},
                    ),
                ],
            ),
        ],
    )

app.layout = html.Div(
    style={
        "display": "flex",
        "alignItems": "flex-start",
        "gap": "0px",
        "background": "#f8fafc",
        "minHeight": "100vh",
    },
    children=[_sidebar(), _content()],
)

# -------------------------------------------------------------------
# CALLBACKS
# -------------------------------------------------------------------
@app.callback(
    Output("status_refresh", "children"),
    Output("f_aba", "options"),
    Output("f_aba", "value"),
    Input("btn_refresh", "n_clicks"),
    State("f_aba", "value"),
    prevent_initial_call=True,
)
def refresh_data(n_clicks, current_aba):
    _load_all_sheets(force=True)
    sheets, order = _CACHE["sheets"], _CACHE["order"]
    opts = [{"label": s, "value": s} for s in order]
    # mantém aba se ainda existir, senão 1ª
    value = current_aba if (current_aba in sheets) else (order[0] if order else None)
    msg = f"Dados atualizados ({len(order)} abas carregadas)."
    return msg, opts, value

@app.callback(
    Output("badge_aba", "children"),
    Output("g_evolucao", "figure"),
    Output("g_sec", "figure"),
    Output("g_ag", "figure"),
    Output("g_treemap", "figure"),
    Output("g_campanhas", "figure"),
    Output("tbl", "data"),
    Input("f_aba", "value"),
)
def on_change_aba(aba):
    if not aba:
        empty_fig = px.scatter(title="Sem dados")
        return "Nenhuma aba selecionada", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, []

    df = _get_df(aba, force=False).copy()
    if df.empty:
        empty_fig = px.scatter(title="Sem dados na aba selecionada")
        return f"Aba: {aba}", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, []

    # Gera gráficos
    f1 = fig_evolucao_mensal(df)
    f2 = fig_top10_secretarias(df)
    f3 = fig_top10_agencias(df)
    f4 = fig_treemap_sec_ag(df)
    f5 = fig_campanhas_valor(df)

    # Prepara dados da tabela (mostra valor BRL, mantém numérico escondido no backend)
    table_df = df.copy()
    # Datas legíveis
    if "DATA DO EMPENHO" in table_df.columns:
        table_df["DATA DO EMPENHO"] = table_df["DATA DO EMPENHO"].dt.strftime("%d/%m/%Y")
    if "COMPETÊNCIA" in table_df.columns:
        table_df["COMPETÊNCIA"] = pd.to_datetime(table_df["COMPETÊNCIA"]).dt.strftime("%m/%Y")

    # Define ordem de colunas exibidas (caso algo falte, ignora)
    cols_order = [
        "CAMPANHA",
        "SECRETARIA",
        "AGÊNCIA",
        "VALOR DO ESPELHO (BRL)",
        "PROCESSO",
        "EMPENHO",
        "DATA DO EMPENHO",
        "COMPETÊNCIA",
        "OBSERVAÇÃO",
        "ESPELHO DIANA",
        "ESPELHO",
        "PDF",
    ]
    cols_present = [c for c in cols_order if c in table_df.columns]
    data = table_df[cols_present].to_dict("records")

    return f"Aba: {aba}", f1, f2, f3, f4, f5, data


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", "8050")), debug=False)
