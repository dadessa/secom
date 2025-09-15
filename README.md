# Controle de Processos — SECOM (Dash)

Dashboard em Python/Dash para visualizar e filtrar a planilha **CONTROLE DE PROCESSOS SECOM.xlsx**.

## 📁 Estrutura
```
secom-dashboard/
├─ assets/
│  └─ style.css

secom-dashboard/
├─ dashboard_secom.py
├─ requirements.txt
├─ Procfile
├─ render.yaml
├─ runtime.txt (opcional, para Heroku)
├─ .gitignore
├─ README.md
└─ data/
   └─ .gitkeep   # coloque aqui o arquivo CONTROLE DE PROCESSOS SECOM.xlsx
```

## ⚙️ Requisitos
- Python 3.10+ (recomendado 3.11)
- Pip

## 🚀 Rodando localmente
1. Crie e ative um virtualenv (opcional, mas recomendado).
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Coloque sua planilha em `data/CONTROLE DE PROCESSOS SECOM.xlsx` **ou** defina a variável de ambiente `EXCEL_PATH` apontando para o arquivo.
4. Execute:
   ```bash
   python dashboard_secom.py
   ```
5. Acesse: http://localhost:8050

### Variáveis de ambiente
- `EXCEL_PATH` (opcional): caminho do Excel. Padrão: `./data/CONTROLE DE PROCESSOS SECOM.xlsx`.
- `SHEET_NAME` (opcional): aba a ser lida. Padrão: `CONTROLE DE PROCESSOS - GERAL`.

**Exemplos**
- Linux/Mac:
  ```bash
  export EXCEL_PATH="./data/CONTROLE DE PROCESSOS SECOM.xlsx"
  export SHEET_NAME="CONTROLE DE PROCESSOS - GERAL"
  python dashboard_secom.py
  ```
- Windows (PowerShell):
  ```powershell
  $env:EXCEL_PATH="./data/CONTROLE DE PROCESSOS SECOM.xlsx"
  $env:SHEET_NAME="CONTROLE DE PROCESSOS - GERAL"
  python dashboard_secom.py
  ```

## ☁️ Deploy na Render
1. Publique este repositório no GitHub.
2. Na Render: **New + → Web Service → Connect a repository**.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn dashboard_secom:server --workers 2 --threads 8 --timeout 120`
5. Configure as env vars (opcional):
   - `EXCEL_PATH=./data/CONTROLE DE PROCESSOS SECOM.xlsx`
   - `SHEET_NAME=CONTROLE DE PROCESSOS - GERAL`
6. Faça upload da planilha na pasta `data/` do serviço (via persistente/volume ou no próprio repo privado).

> Alternativa: Heroku (usa `runtime.txt` + `Procfile`).

## 📊 O que o dashboard entrega
- Filtros: **Secretaria, Agência, Campanha, Competência (mês/ano), Período de Empenho, Busca por Processo/Observação**.
- KPIs: **Total de registros, Soma dos valores, nº de Secretarias, nº de Agências**.
- Gráficos: **Valor por Secretaria**, **Valor por Agência**, **Evolução Mensal**, **Top Campanhas por Valor**.
- Tabela com **links clicáveis** e **Exportar Excel/PDF**.
- Tema **claro/escuro** + **Atualizar dados**.

## 🧭 Git — passo a passo
```bash
git init
git add .
git commit -m "Inicial: dashboard SECOM"
git branch -M main
# substitua pelo seu repositório:
git remote add origin git@github.com:SEU_USUARIO/secom-dashboard.git
git push -u origin main
```

---

Feito com ❤️ para acelerar sua análise de processos da SECOM.


## 🎨 Estilos (CSS)
Os estilos agora ficam em `assets/style.css`. O Dash carrega automaticamente qualquer arquivo dentro da pasta `assets/`.
