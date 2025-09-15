
# -*- coding: utf-8 -*-
"""
Dashboard SECOM — Controle de Processos (v1.0)
- Leitura do Excel local (CONTROLE DE PROCESSOS SECOM.xlsx) ou por variável EXCEL_PATH
- Filtros: Secretaria, Agência, Campanha, Competência (mês/ano), Período do Empenho, Busca por Processo/Observação
- KPIs: Total de Registros, Soma do Valor do Espelho, Secretarias únicas, Agências únicas
- Gráficos: Valor por Secretaria, Valor por Agência, Evolução Mensal, Top Campanhas por Valor
- Tabela com links clicáveis (Espelho Diana / Espelho / PDF / Processo / Empenho), exportação para Excel e PDF
- Tema claro/escuro, atualização de dados
"""
import os
import math
from io import BytesIO
import pandas as pd
from dash import Dash, dcc, html, dash_table
from dash import Input, Output, State
from dash.dash_table.Format import Format, Group, Scheme
import plotly.express as px

EXCEL_PATH = os.environ.get("EXCEL_PATH", "CONTROLE DE PROCESSOS SECOM.xlsx")
SHEET_NAME = os.environ.get("SHEET_NAME", "CONTROLE DE PROCESSOS - GERAL")

# ========= HELPERS =========
def _try_parse_date(series: pd.Series):
    s = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return s

def _is_link(val: str) -> bool:
    if not isinstance(val, str): return False
    return val.startswith("http://") or val.startswith("https://")

def _linkify(val: str) -> str:
    if _is_link(val):
        return f"[abrir]({val})"
    return str(val) if (val is not None) else ""

def _fmt_currency(v) -> str:
    try:
        v = float(v)
        if math.isnan(v): return "R$ 0,00"
        return "R$ " + ("{:,.2f}".format(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def _load_data() -> pd.DataFrame:
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)
    # Normaliza nomes esperados conforme a planilha enviada
    expected = [
        "CAMPANHA","SECRETARIA","AGÊNCIA","ESPELHO DIANA","ESPELHO","PDF",
        "VALOR DO ESPELHO","PROCESSO","EMPENHO","DATA DO EMPENHO","COMPETÊNCIA","OBSERVAÇÃO"
    ]
    # Garante presença das colunas esperadas (se faltarem, cria vazias)
    for col in expected:
        if col not in df.columns:
            df[col] = None

    # Tipos
    if "VALOR DO ESPELHO" in df.columns:
        df["VALOR DO ESPELHO"] = pd.to_numeric(df["VALOR DO ESPELHO"], errors="coerce").fillna(0.0)

    if "DATA DO EMPENHO" in df.columns:
        df["DATA DO EMPENHO"] = _try_parse_date(df["DATA DO EMPENHO"])

    # Competência (tentar normalizar para período YYYY-MM)
    if "COMPETÊNCIA" in df.columns:
        comp = df["COMPETÊNCIA"].astype(str).str.strip()
        # Tenta converter 05/2025 ou Mai/2025 para período, caindo para texto
        comp_dt = pd.to_datetime(comp, errors="coerce", format="%m/%Y")
        # fallback: tenta dd/mm/aaaa
        comp_dt2 = pd.to_datetime(comp, errors="coerce", dayfirst=True)
        df["COMPETÊNCIA_DT"] = comp_dt.fillna(comp_dt2)
        df["COMPETÊNCIA_TXT"] = comp.where(df["COMPETÊNCIA_DT"].isna(), df["COMPETÊNCIA_DT"].dt.to_period("M").astype(str))
    else:
        df["COMPETÊNCIA_DT"] = pd.NaT
        df["COMPETÊNCIA_TXT"] = ""

    # Links
    for col in ["ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"]:
        if col in df.columns:
            df[col] = df[col].astype(str)

    # Linhas “vazias” (sem secretaria e sem agência e sem campanha e sem processo) não ajudam => dropa
    df = df[~(
        df["SECRETARIA"].isna() & df["AGÊNCIA"].isna() & df["CAMPANHA"].isna() & df["PROCESSO"].isna()
    )].copy()

    return df.fillna("")

DF_BASE = _load_data()

# ========= TEMA =========
THEME = {
    "light": {"template": "plotly_white", "font": "#0F172A", "grid": "#E9EDF5"},
    "dark":  {"template": "plotly_dark",  "font": "#E6ECFF", "grid": "#22304A"},
    "secom-light": {"template": "plotly_white", "font": "#0A1224", "grid": "#E4EAF5"},
    "secom-dark": {"template": "plotly_dark", "font": "#E7EDF8", "grid": "#24324E"}
}

def style_fig(fig, theme="light"):
    t = THEME.get(theme, THEME["light"])
    fig.update_layout(
        template=t["template"],
        font=dict(color=t["font"], size=13),
        margin=dict(l=12, r=12, t=48, b=12),
    )
    fig.update_xaxes(gridcolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"])
    return fig

# ========= APP =========
app = Dash(__name__)
server = app.server

def kpi_card(id_, label):
    return html.Div(className="card kpi", children=[
        html.P(label, className="kpi-title"), html.H2(id=id_, className="kpi-value")
    ])

app.layout = html.Div(className="light", id="root", children=[
    html.Div(className="container", children=[
        # Navbar
        html.Div(className="navbar", children=[
            html.Div(className="brand", children=[html.Div("📑", style={"fontSize":"20px"}), html.H1("Controle de Processos — SECOM"), html.Span("v1.0", className="badge")]),
            html.Div(className="actions", children=[
                dcc.RadioItems(
                    id="theme", value="secom-light", inline=True,
                    options=[
                        {"label": "Claro", "value": "light"},
                        {"label": "Escuro", "value": "dark"},
                        {"label": "SECOM (Claro)", "value": "secom-light"},
                        {"label": "SECOM (Escuro)", "value": "secom-dark"}
                    ],
                    inputStyle={"marginRight":"6px","marginLeft":"10px"},
                ),
                html.Button("Atualizar dados", id="btn-reload", n_clicks=0, className="btn ghost"),
                html.Button("Exportar Excel", id="btn-xlsx", n_clicks=0, className="btn"),
                html.Button("Exportar PDF", id="btn-pdf", n_clicks=0, className="btn"),
                dcc.Download(id="dl-xlsx"), dcc.Download(id="dl-pdf"),
            ])
        ]),

        # Filtros
        html.Div(className="panel", children=[
            html.Div(className="filters", children=[
                html.Div(children=[html.Div("Secretaria", className="label"),
                    dcc.Dropdown(id="f_secretaria", options=[{"label": s, "value": s} for s in sorted(DF_BASE["SECRETARIA"].unique()) if s], multi=True, placeholder="Selecione…")
                ]),
                html.Div(children=[html.Div("Agência", className="label"),
                    dcc.Dropdown(id="f_agencia", options=[{"label": s, "value": s} for s in sorted(DF_BASE["AGÊNCIA"].unique()) if s], multi=True, placeholder="Selecione…")
                ]),
                html.Div(children=[html.Div("Campanha", className="label"),
                    dcc.Dropdown(id="f_campanha", options=[{"label": s, "value": s} for s in sorted(DF_BASE["CAMPANHA"].unique()) if s], multi=True, placeholder="Selecione…")
                ]),
                html.Div(children=[html.Div("Competência (Mês)", className="label"),
                    dcc.Dropdown(id="f_comp", options=[{"label": s, "value": s} for s in sorted(DF_BASE["COMPETÊNCIA_TXT"].unique()) if s], multi=True, placeholder="Ex.: 2025-05…")
                ]),
                html.Div(children=[html.Div("Período — Data do Empenho", className="label"),
                    dcc.DatePickerRange(id="f_empenho_range",
                        min_date_allowed=DF_BASE["DATA DO EMPENHO"].min() if (DF_BASE["DATA DO EMPENHO"].dtype.kind=="M") else None,
                        max_date_allowed=DF_BASE["DATA DO EMPENHO"].max() if (DF_BASE["DATA DO EMPENHO"].dtype.kind=="M") else None,
                    )
                ]),
                html.Div(children=[html.Div("Buscar por Processo / Observação", className="label"),
                    dcc.Input(id="f_busca", type="text", placeholder="Digite para filtrar…", debounce=True)
                ]),
                html.Div(children=[html.Div("Ordenação", className="label"),
                    dcc.RadioItems(id="sort", value="desc", inline=True,
                        options=[{"label":"Decrescente","value":"desc"},{"label":"Crescente","value":"asc"}],
                        inputStyle={"marginRight":"6px","marginLeft":"10px"})
                ]),
            ])
        ]),

        # KPIs
        html.Div(className="kpis", children=[
            kpi_card("kpi_total", "Total de Registros"),
            kpi_card("kpi_valor", "Soma dos Valores"),
            kpi_card("kpi_secr", "Secretarias"),
            kpi_card("kpi_ag", "Agências"),
        ]),

        # Gráficos
        html.Div(className="grid-2", children=[
            html.Div(className="card", children=[dcc.Graph(id="g_valor_secretaria", config={"displayModeBar": False})]),
            html.Div(className="card", children=[dcc.Graph(id="g_valor_agencia", config={"displayModeBar": False})]),
        ]),
        html.Div(className="grid-2", children=[
            html.Div(className="card", children=[dcc.Graph(id="g_evolucao", config={"displayModeBar": False})]),
            html.Div(className="card", children=[dcc.Graph(id="g_top_campanha", config={"displayModeBar": False})]),
        ]),

        # Tabela
        html.Div(className="panel", children=[
            html.Div("Dados detalhados", className="label"),
            html.Div(className="card", children=[
                dash_table.DataTable(
                    id="tbl", page_size=12, sort_action="native", filter_action="native",
                    fixed_rows={"headers": True}, style_table={"overflowX": "auto", "minWidth":"100%"},
                    style_cell={"padding":"10px","textAlign":"left","border":"0","whiteSpace":"normal","height":"auto"},
                    style_header={"fontWeight":"700","border":"0"},
                    style_cell_conditional=[
                        {"if": {"column_id": "VALOR DO ESPELHO"}, "textAlign":"right"},
                    ],
                    markdown_options={"link_target": "_blank"},
                )
            ]),
        ]),
    ]),
])

# ========= CORE =========
def _filtrar(df: pd.DataFrame, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca):
    dff = df.copy()

    if f_sec:   dff = dff[dff["SECRETARIA"].isin(f_sec)]
    if f_ag:    dff = dff[dff["AGÊNCIA"].isin(f_ag)]
    if f_camp:  dff = dff[dff["CAMPANHA"].isin(f_camp)]
    if f_comp:  dff = dff[dff["COMPETÊNCIA_TXT"].isin(f_comp)]

    if pd.api.types.is_datetime64_any_dtype(dff["DATA DO EMPENHO"]):
        if dt_ini: dff = dff[dff["DATA DO EMPENHO"] >= pd.to_datetime(dt_ini)]
        if dt_fim: dff = dff[dff["DATA DO EMPENHO"] <= pd.to_datetime(dt_fim)]

    if busca and str(busca).strip():
        patt = str(busca).strip().lower()
        mask = (
            dff["PROCESSO"].astype(str).str.lower().str.contains(patt, na=False) |
            dff["OBSERVAÇÃO"].astype(str).str.lower().str.contains(patt, na=False)
        )
        dff = dff[mask]

    return dff

@app.callback(Output("root","className"), Input("theme","value"))
def set_theme(theme):
    return theme if theme in {"light","dark","secom-light","secom-dark"} else "light"

@app.callback(
    Output("kpi_total","children"),
    Output("kpi_valor","children"),
    Output("kpi_secr","children"),
    Output("kpi_ag","children"),
    Output("g_valor_secretaria","figure"),
    Output("g_valor_agencia","figure"),
    Output("g_evolucao","figure"),
    Output("g_top_campanha","figure"),
    Output("tbl","data"),
    Output("tbl","columns"),
    Input("f_secretaria","value"),
    Input("f_agencia","value"),
    Input("f_campanha","value"),
    Input("f_comp","value"),
    Input("f_empenho_range","start_date"),
    Input("f_empenho_range","end_date"),
    Input("f_busca","value"),
    Input("sort","value"),
    Input("btn-reload","n_clicks"),
    State("theme","value"),
)
def atualizar(f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca, sort, n_reload, theme):
    base = _load_data() if (n_reload and n_reload>0) else DF_BASE
    dff = _filtrar(base, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca)
    asc = (sort == "asc")

    total = len(dff)
    soma_valor = dff["VALOR DO ESPELHO"].sum()
    k_valor = _fmt_currency(soma_valor)
    k_secr = int(dff["SECRETARIA"].nunique())
    k_ag = int(dff["AGÊNCIA"].nunique())

    # Valor por Secretaria (Top 10)
    g1 = dff.groupby("SECRETARIA", as_index=False)["VALOR DO ESPELHO"].sum().rename(columns={"VALOR DO ESPELHO":"Valor"})
    g1 = g1.sort_values("Valor", ascending=False).head(10).sort_values("Valor", ascending=asc)
    fig1 = px.bar(g1, x="SECRETARIA", y="Valor", text="Valor", title="Valor por Secretaria (Top 10)")
    fig1.update_traces(texttemplate="%{text:.0f}")
    style_fig(fig1, theme)

    # Valor por Agência (Top 10)
    g2 = dff.groupby("AGÊNCIA", as_index=False)["VALOR DO ESPELHO"].sum().rename(columns={"VALOR DO ESPELHO":"Valor"})
    g2 = g2.sort_values("Valor", ascending=False).head(10).sort_values("Valor", ascending=asc)
    fig2 = px.bar(g2, x="AGÊNCIA", y="Valor", text="Valor", title="Valor por Agência (Top 10)")
    fig2.update_traces(texttemplate="%{text:.0f}")
    style_fig(fig2, theme)

    # Evolução mensal (DATA DO EMPENHO, fallback COMPETÊNCIA_TXT)
    if pd.api.types.is_datetime64_any_dtype(dff["DATA DO EMPENHO"]):
        g3 = dff.copy()
        g3["MES"] = g3["DATA DO EMPENHO"].dt.to_period("M").astype(str)
    else:
        g3 = dff.copy()
        g3["MES"] = g3["COMPETÊNCIA_TXT"].replace("", pd.NA)
    g3 = g3.dropna(subset=["MES"])
    evo = g3.groupby("MES", as_index=False)["VALOR DO ESPELHO"].sum().rename(columns={"VALOR DO ESPELHO":"Valor"})
    evo = evo.sort_values("MES", ascending=True)
    fig3 = px.bar(evo, x="MES", y="Valor", text="Valor", title="Evolução Mensal (Soma dos Valores)")
    fig3.update_traces(texttemplate="%{text:.0f}")
    style_fig(fig3, theme)

    # Top Campanhas
    g4 = dff.groupby("CAMPANHA", as_index=False)["VALOR DO ESPELHO"].sum().rename(columns={"VALOR DO ESPELHO":"Valor"})
    g4 = g4.sort_values("Valor", ascending=False).head(10).sort_values("Valor", ascending=asc)
    fig4 = px.bar(g4, x="CAMPANHA", y="Valor", text="Valor", title="Top Campanhas por Valor")
    fig4.update_traces(texttemplate="%{text:.0f}")
    style_fig(fig4, theme)

    # Tabela — com links clicáveis
    cols = [
        "CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","COMPETÊNCIA","DATA DO EMPENHO",
        "ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO","OBSERVAÇÃO"
    ]
    present = [c for c in cols if c in dff.columns]

    # Colunas para dash_table
    fmt_cur = Format(scheme=Scheme.fixed, precision=2, group=Group.yes, groups=3, group_delimiter=".", decimal_delimiter=",")
    columns = []
    for c in present:
        col = {"name": c, "id": c}
        if c in ["ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"]:
            col["presentation"] = "markdown"
        if c == "VALOR DO ESPELHO":
            col.update({"type":"numeric", "format": fmt_cur})
        columns.append(col)

    # Dados formatados
    data = []
    for _, row in dff[present].iterrows():
        item = {}
        for c in present:
            val = row[c]
            if c == "VALOR DO ESPELHO":
                item[c] = float(val) if pd.notna(val) else 0.0
            elif c in ["ESPELHO DIANA","ESPELHO","PDF","PROCESSO","EMPENHO"]:
                item[c] = _linkify(val)
            elif c == "DATA DO EMPENHO" and pd.notna(val):
                if hasattr(val, "strftime"): item[c] = val.strftime("%d/%m/%Y")
                else: item[c] = str(val)
            else:
                item[c] = "" if (val is None) else str(val)
        data.append(item)

    return str(total), k_valor, str(k_secr), str(k_ag), fig1, fig2, fig3, fig4, data, columns

# ========= EXPORTS =========
@app.callback(
    Output("dl-xlsx","data"),
    Input("btn-xlsx","n_clicks"),
    State("f_secretaria","value"), State("f_agencia","value"), State("f_campanha","value"),
    State("f_comp","value"), State("f_empenho_range","start_date"), State("f_empenho_range","end_date"),
    State("f_busca","value"),
    prevent_initial_call=True
)
def export_xlsx(n, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca):
    dff = _filtrar(DF_BASE, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca)
    try:
        return dcc.send_data_frame(dff.to_excel, "controle_processos_filtrado.xlsx", sheet_name="Dados", index=False)
    except Exception as e:
        return dcc.send_data_frame(dff.to_csv, "controle_processos_filtrado.csv", index=False)

@app.callback(
    Output("dl-pdf","data"),
    Input("btn-pdf","n_clicks"),
    State("f_secretaria","value"), State("f_agencia","value"), State("f_campanha","value"),
    State("f_comp","value"), State("f_empenho_range","start_date"), State("f_empenho_range","end_date"),
    State("f_busca","value"),
    prevent_initial_call=True
)
def export_pdf(n, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca):
    dff = _filtrar(DF_BASE, f_sec, f_ag, f_camp, f_comp, dt_ini, dt_fim, busca)
    def _to_pdf(buff):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import mm

        doc = SimpleDocTemplate(buff, pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
        styles = getSampleStyleSheet()
        title = ParagraphStyle("title", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#111827"))
        cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
        cell_wrap = ParagraphStyle("cell_wrap", parent=cell, wordWrap="CJK")

        elements = [Paragraph("Controle de Processos — Dados Filtrados", title), Spacer(1,6)]

        cols = ["CAMPANHA","SECRETARIA","AGÊNCIA","VALOR DO ESPELHO","COMPETÊNCIA","DATA DO EMPENHO","PROCESSO","EMPENHO","OBSERVAÇÃO"]
        cols = [c for c in cols if c in dff.columns]
        headers = cols

        data = [[Paragraph(h, styles["Normal"]) for h in headers]]

        def fmt_cur(v):
            try:
                return str(f"{float(v):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
            except: return str(v)

        for _, r in dff[cols].iterrows():
            row = []
            for c in cols:
                v = r[c]
                if c == "VALOR DO ESPELHO":
                    row.append(Paragraph(fmt_cur(v), cell))
                elif c in ["PROCESSO","EMPENHO"] and isinstance(v, str) and v:
                    row.append(Paragraph(v, cell_wrap))
                else:
                    row.append(Paragraph("" if (pd.isna(v) or v is None) else str(v), cell_wrap))
            data.append(row)

        col_widths_map = {
            "CAMPANHA": 50, "SECRETARIA": 50, "AGÊNCIA": 40, "VALOR DO ESPELHO": 32,
            "COMPETÊNCIA": 28, "DATA DO EMPENHO": 32, "PROCESSO": 60, "EMPENHO": 60, "OBSERVAÇÃO": 80
        }
        widths = [col_widths_map.get(c, 32)*mm for c in cols]
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("ALIGN",(0,0),(-1,0),"CENTER"),
            ("GRID",(0,0),(-1,-1), 0.25, colors.HexColor("#D1D5DB")),
            ("VALIGN",(0,0),(-1,-1), "TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.whitesmoke, colors.HexColor("#F8FAFC")]),
        ]))
        elements.append(table)
        doc.build(elements)

    return dcc.send_bytes(_to_pdf, "controle_processos_filtrado.pdf")

# ========= STYLES =========

app.index_string = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Controle de Processos — SECOM</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="root">Loading…</div>
  </body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    try:
        app.run(debug=True, host="0.0.0.0", port=port)
    except AttributeError:
        app.run_server(debug=True, host="0.0.0.0", port=port)
