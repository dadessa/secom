/* Layout base */
:root {
  --bg: #ffffff;
  --fg: #111827;
  --muted: #6b7280;
  --card: #f8fafc;
  --accent: #2563eb;
  --border: #e5e7eb;
  --card-border: #e5e7eb;
}

.theme-dark {
  --bg: #0f172a;
  --fg: #e5e7eb;
  --muted: #9ca3af;
  --card: #111827;
  --accent: #60a5fa;
  --border: #1f2937;
  --card-border: #1f2937;
}

html, body, #_dash-app-content, #_dash-global-error-container, #theme-wrapper {
  height: 100%;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
}

/* Topbar */
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}

.brand .app-title {
  margin: 0;
  font-weight: 700;
}

.controls {
  display: flex;
  gap: 16px;
  align-items: center;
}
.control label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.btn {
  cursor: pointer;
  padding: 8px 12px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 10px;
}

/* Erros */
.error-banner {
  margin: 8px 20px;
  padding: 8px 12px;
  border: 1px solid #ef4444;
  color: #991b1b;
  background: #fee2e2;
  border-radius: 8px;
}

/* Body com Sidebar */
.layout-body {
  display: flex;
  gap: 20px;
  padding: 20px;
}

.sidebar {
  flex: 0 0 320px;
  max-width: 320px;
  min-width: 260px;
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 16px;
  position: sticky;
  top: 64px; /* abaixo da topbar */
  max-height: calc(100vh - 84px);
  overflow: auto;
}
.sidebar h4 { margin: 0 0 12px 0; }
.sidebar label { font-size: 12px; color: var(--muted); margin-top: 10px; display: block; }
.sidebar .Select-control, .sidebar .DateInput_input, .sidebar .DateRangePickerInput__withBorder {
  background: transparent;
}

/* Main */
.main {
  flex: 1 1 auto;
  min-width: 0;
}

/* Cards */
.cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 12px 14px;
}
.card > div { font-size: 12px; color: var(--muted); }
.card > h3 { margin: 6px 0 0 0; font-size: 22px; }

/* Grid de gráficos */
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 16px;
}
.graph-card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 8px;
}
.graph-card .dash-graph, .graph-card .js-plotly-plot, .graph-card svg {
  width: 100% !important;
}

/* Tabela */
.table-wrap {
  margin-top: 16px;
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 8px;
}
