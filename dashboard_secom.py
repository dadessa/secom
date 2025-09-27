import { useState, useMemo, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { TrendingUp, TrendingDown, DollarSign, AlertCircle } from 'lucide-react';
import type { MonthlySheet, DashboardFilter } from '@/types';

interface DashboardViewProps {
  sheets: MonthlySheet[];
  externalFilters?: { sheet?: string; tab?: string; category?: string };
  onFiltersChange?: (filters: { sheet?: string; tab?: string; category?: string }) => void;
}

/** Utilitário seguro para BRL */
const formatCurrency = (value: number) =>
  (isFinite(value) ? value : 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

/** Evita divisões por zero/NaN */
const pct = (num: number, den: number) => (den > 0 ? (num / den) * 100 : 0);

/** Paleta coerente com CSS vars */
const COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--success))',
  'hsl(var(--warning))',
  'hsl(var(--destructive, var(--danger)))',
  'hsl(var(--muted-foreground))',
  'hsl(var(--secondary))'
];

export const DashboardView = ({ sheets, externalFilters, onFiltersChange }: DashboardViewProps) => {
  const [filters, setFilters] = useState<DashboardFilter>({});

  // Sincroniza com filtros externos
  useEffect(() => {
    if (externalFilters) {
      setFilters(prev => ({ ...prev, ...externalFilters }));
    }
  }, [externalFilters]);

  // Define planilha mais recente como padrão (última da lista) quando não houver seleção
  useEffect(() => {
    if (sheets.length === 0) return;
    if (!filters.sheet && !externalFilters?.sheet) {
      const latest = sheets[sheets.length - 1];
      const nf = { ...filters, sheet: latest.id, tab: '', category: '' };
      setFilters(nf);
      onFiltersChange?.(nf);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheets]);

  /** Planilha selecionada */
  const selectedSheet = useMemo(() => {
    if (!sheets?.length) return undefined;
    if (filters.sheet) return sheets.find(s => s.id === filters.sheet) || sheets[sheets.length - 1];
    return sheets[sheets.length - 1];
  }, [sheets, filters.sheet]);

  /** Conjunto de categorias a usar (aba → categorias; se nenhuma aba, usa da planilha) */
  const categoriesToUse = useMemo(() => {
    if (!selectedSheet) return [];
    if (filters.tab && selectedSheet.tabs) {
      const t = selectedSheet.tabs.find(tb => tb.id === filters.tab);
      if (t?.categories) return t.categories;
    }
    return selectedSheet.categories || [];
  }, [selectedSheet, filters.tab]);

  /** Lista de categorias para o dropdown (respeita aba selecionada) */
  const categoryOptions = useMemo(() => {
    return categoriesToUse.map(cat => ({ id: cat.id, name: cat.name }));
  }, [categoriesToUse]);

  /** Dados do dashboard (kpis + datasets) */
  const dashboardData = useMemo(() => {
    if (!selectedSheet) return null;

    // Filtra categoria (se selecionada)
    const filtered = categoriesToUse.filter(cat => {
      if (filters.category && cat.id !== filters.category) return false;
      return true;
    });

    // Orçamento total: prioriza linha TOTAL; senão soma das categorias da planilha completa
    const totalBudget = (() => {
      const totalCat = selectedSheet.categories?.find(cat =>
        ['total', 'TOTAL'].includes(cat.id) ||
        cat.name?.trim().toUpperCase() === 'TOTAL' ||
        cat.name?.toLowerCase().includes('total')
      );
      const byTotalRow = totalCat?.globalValue ?? 0;
      if (byTotalRow > 0) return byTotalRow;

      const sumSheet = (selectedSheet.categories || [])
        .filter(c => !(c.name || '').toLowerCase().includes('total'))
        .reduce((acc, c) => acc + (c.globalValue || 0), 0);
      return sumSheet;
    })();

    const totalCommitted = filtered.reduce((acc, c) => acc + (c.committed || 0), 0);
    const totalBalance   = filtered.reduce((acc, c) => acc + (c.balance   || 0), 0);

    // Dataset por categoria (gráficos)
    const categoryData = filtered.map(cat => ({
      name: cat.name,
      orcamento: cat.globalValue || 0,
      empenhado: cat.committed   || 0,
      saldo: cat.balance         || 0,
      percentual: pct(cat.committed || 0, cat.globalValue || 0)
    }));

    // “Status” estimado sem aleatoriedade:
    // Para cada categoria, distribui proporcionalmente o valor empenhado entre as campanhas do veículo.
    // Campanha é considerada “empenhada” se a parcela estimada cobrir o valor daquela campanha.
    type StatusRow = { category: string; vehicle: string; campaign: string; value: number; status: 'empenhado' | 'pendente' };
    const statusRows: StatusRow[] = [];

    filtered.forEach(cat => {
      const catTotalCampaigns = cat.vehicles?.reduce((acc, v) => acc + Object.values(v.campaigns || {}).length, 0) || 0;
      const catBudget = cat.globalValue || 0;
      const catCommitted = Math.min(cat.committed || 0, catBudget);
      const committedRatio = pct(catCommitted, catBudget) / 100; // 0..1

      (cat.vehicles || []).forEach(vehicle => {
        const campaignEntries = Object.entries(vehicle.campaigns || {});
        const vehicleTotal = campaignEntries.reduce((acc, [, val]) => acc + (val as number), 0) || 0;

        // parcela empenhada estimada para o veículo
        const vehicleCommittedEst = vehicleTotal * committedRatio;

        // percorre campanhas acumulando
        let remaining = vehicleCommittedEst;
        campaignEntries.forEach(([campaign, value]) => {
          const v = Number(value) || 0;
          const isEmp = remaining >= v - 1e-6;
          statusRows.push({
            category: cat.name,
            vehicle: vehicle.name,
            campaign,
            value: v,
            status: isEmp ? 'empenhado' : 'pendente'
          });
          remaining = Math.max(0, remaining - v);
        });
      });
    });

    const pendingPayments     = statusRows.filter(s => s.status === 'pendente').length;
    const completedCampaigns  = statusRows.filter(s => s.status === 'empenhado').length;

    return {
      totalBudget,
      totalCommitted,
      totalBalance,
      pendingPayments,
      completedCampaigns,
      categoryData,
      statusData: statusRows
    };
  }, [selectedSheet, categoriesToUse, filters.category]);

  if (!dashboardData) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Nenhuma planilha disponível</p>
      </div>
    );
  }

  const onChangeSheet = (value: string) => {
    const nf = { sheet: value, tab: '', category: '' };
    setFilters(nf);
    onFiltersChange?.(nf);
  };

  const onChangeTab = (value: string) => {
    const tabVal = value === 'main' ? '' : value;
    const nf = { ...filters, tab: tabVal, category: '' };
    setFilters(nf);
    onFiltersChange?.(nf);
  };

  const onChangeCategory = (value: string) => {
    const catVal = value === 'all' ? '' : value;
    const nf = { ...filters, category: catVal };
    setFilters(nf);
    onFiltersChange?.(nf);
  };

  // Lista fixa de nomes para o bloco “Totalizadores por Valor Global”
  const TOTALIZER_NAMES = [
    'OAM', 'TVs', 'Site', 'Rádio', 'Jornais/Revistas',
    'Criação', 'Produtora', 'Redes Sociais', 'Material Gráfico',
    'Outdoors/Busdoor/ Mídia Exterior', 'Mídia Nacional', 'Eventos Especiais'
  ];

  const sumTotalizers = TOTALIZER_NAMES.reduce((sum, categoryName) => {
    const item = dashboardData.categoryData.find(cat => {
      const a = cat.name.toLowerCase();
      const b = categoryName.toLowerCase();
      return a.includes(b) || b.includes(a) || a === b;
    });
    return sum + (item?.orcamento || 0);
  }, 0);

  return (
    <div className="space-y-6">
      {/* Filtros */}
      <Card>
        <CardHeader>
          <CardTitle>Filtros do Dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {/* Planilha */}
            <div>
              <label className="text-sm font-medium mb-2 block">Planilha</label>
              <Select value={filters.sheet || ''} onValueChange={onChangeSheet}>
                <SelectTrigger className="bg-background w-full">
                  <SelectValue placeholder="Selecione uma planilha" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50 max-w-[90vw]">
                  {(sheets || []).map(sheet => (
                    <SelectItem key={sheet.id} value={sheet.id} className="text-sm">
                      <span className="truncate max-w-[250px] block">{sheet.name}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Aba */}
            <div>
              <label className="text-sm font-medium mb-2 block flex items-center gap-2">
                <span>📋</span> Aba da Planilha
              </label>
              <Select value={filters.tab || 'main'} onValueChange={onChangeTab}>
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="Selecione uma aba" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50">
                  <SelectItem value="main">Todas as Abas</SelectItem>
                  {(selectedSheet?.tabs || []).map(tab => (
                    <SelectItem key={tab.id} value={tab.id}>
                      {tab.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Categoria */}
            <div>
              <label className="text-sm font-medium mb-2 block">Categoria</label>
              <Select value={filters.category || 'all'} onValueChange={onChangeCategory}>
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="Todas as categorias" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50">
                  <SelectItem value="all">Todas as categorias</SelectItem>
                  {categoryOptions.map(cat => (
                    <SelectItem key={cat.id} value={cat.id}>
                      {cat.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* KPIs */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Orçamento Total</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCurrency(dashboardData.totalBudget)}</div>
            <p className="text-xs text-muted-foreground">Base para todos os empenhos</p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Empenhado</CardTitle>
            <TrendingUp className="h-4 w-4 text-success" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-success">{formatCurrency(dashboardData.totalCommitted)}</div>
            <div className="flex items-center gap-2 mt-1">
              <Progress value={pct(dashboardData.totalCommitted, dashboardData.totalBudget)} className="flex-1 h-2" />
              <Badge variant="secondary">
                {pct(dashboardData.totalCommitted, dashboardData.totalBudget).toFixed(1)}%
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Saldo Disponível</CardTitle>
            <TrendingDown className="h-4 w-4 text-warning" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-warning">{formatCurrency(dashboardData.totalBalance)}</div>
            <p className="text-xs text-muted-foreground">Valor ainda não empenhado</p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pendências</CardTitle>
            <AlertCircle className="h-4 w-4 text-destructive" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-destructive">{dashboardData.pendingPayments}</div>
            <p className="text-xs text-muted-foreground">Campanhas aguardando empenho</p>
          </CardContent>
        </Card>
      </div>

      {/* Totalizadores por Valor Global */}
      <Card>
        <CardHeader>
          <CardTitle>Totalizadores por Valor Global</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {TOTALIZER_NAMES.map((name, i) => {
              const item = dashboardData.categoryData.find(cat => {
                const a = cat.name.toLowerCase();
                const b = name.toLowerCase();
                return a.includes(b) || b.includes(a) || a === b;
              });
              const value = item?.orcamento || 0;
              return (
                <div
                  key={name}
                  className="p-4 bg-muted/30 rounded-lg border-l-4"
                  style={{ borderLeftColor: COLORS[i % COLORS.length] }}
                >
                  <h4 className="font-semibold text-sm mb-2">{name}</h4>
                  <div className="text-xl font-bold text-primary">{formatCurrency(value)}</div>
                  <p className="text-xs text-muted-foreground mt-1">Valor Global</p>
                  {item && <p className="text-xs text-success mt-1">✓ Encontrado: {item.name}</p>}
                </div>
              );
            })}
          </div>

          <div className="mt-4 p-4 bg-primary/10 rounded-lg">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-lg">TOTAL:</span>
              <span className="font-bold text-2xl text-primary">{formatCurrency(sumTotalizers)}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Gráficos */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Orçamento vs Empenhado por Categoria</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dashboardData.categoryData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} />
                <YAxis tickFormatter={(v) => `R$ ${(Number(v || 0) / 1_000_000).toFixed(1)}M`} />
                <Tooltip formatter={(v: number) => formatCurrency(Number(v || 0))} />
                <Bar dataKey="orcamento" fill="hsl(var(--primary))" name="Orçamento" />
                <Bar dataKey="empenhado" fill="hsl(var(--success))" name="Empenhado" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Distribuição do Orçamento</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={dashboardData.categoryData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name}: ${((percent || 0) * 100).toFixed(0)}%`}
                  outerRadius={80}
                  dataKey="orcamento"
                >
                  {dashboardData.categoryData.map((_, idx) => (
                    <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatCurrency(Number(v || 0))} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Detalhes da Categoria Selecionada */}
      {filters.category && (() => {
        const selectedCat = categoriesToUse.find(c => c.id === filters.category);
        if (!selectedCat) return null;

        return (
          <Card>
            <CardHeader>
              <CardTitle>Detalhes da Categoria: {selectedCat.name}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-primary">{formatCurrency(selectedCat.globalValue || 0)}</div>
                    <p className="text-sm text-muted-foreground">Orçamento Global</p>
                  </div>
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-success">{formatCurrency(selectedCat.committed || 0)}</div>
                    <p className="text-sm text-muted-foreground">Valor Empenhado</p>
                  </div>
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-warning">{formatCurrency(selectedCat.balance || 0)}</div>
                    <p className="text-sm text-muted-foreground">Saldo Disponível</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <h3 className="text-lg font-semibold">
                    {selectedCat.name.toLowerCase().includes('site') ? 'Sites da Categoria' : 'Veículos da Categoria'}
                  </h3>

                  {(selectedCat.vehicles || []).map((vehicle) => {
                    const totalBudget = Number(vehicle.totalBudget || 0);
                    const totalUsed   = Number(vehicle.totalUsed || 0);
                    const balance     = Number(vehicle.balance || Math.max(0, totalBudget - totalUsed));
                    const usedPct     = pct(totalUsed, totalBudget);

                    return (
                      <Card key={vehicle.id} className="border-l-4 border-l-primary">
                        <CardContent className="p-4">
                          <div className="flex justify-between items-start mb-3">
                            <h4 className="font-semibold text-lg">
                              {selectedCat.name.toLowerCase().includes('site') ? `Site: ${vehicle.name}` : vehicle.name}
                            </h4>
                            <Badge variant={balance > 0 ? 'default' : 'destructive'}>
                              Saldo: {formatCurrency(balance)}
                            </Badge>
                          </div>

                          <div className="grid gap-2 md:grid-cols-3 mb-4">
                            <div>
                              <span className="text-sm text-muted-foreground">
                                {selectedCat.name.toLowerCase().includes('site') ? 'Orçamento do Site:' : 'Orçamento Total:'}
                              </span>
                              <div className="font-medium">{formatCurrency(totalBudget)}</div>
                            </div>
                            <div>
                              <span className="text-sm text-muted-foreground">
                                {selectedCat.name.toLowerCase().includes('site') ? 'Valor Investido:' : 'Total Usado:'}
                              </span>
                              <div className="font-medium">{formatCurrency(totalUsed)}</div>
                            </div>
                            <div>
                              <span className="text-sm text-muted-foreground">% Utilizado:</span>
                              <div className="font-medium">{usedPct.toFixed(1)}%</div>
                            </div>
                          </div>

                          {vehicle.observations && (
                            <div className="mb-4 p-3 bg-muted/30 rounded-lg">
                              <span className="text-sm text-muted-foreground">Observações:</span>
                              <p className="text-sm mt-1">{vehicle.observations}</p>
                            </div>
                          )}

                          <div>
                            <h5 className="font-medium mb-2">
                              {selectedCat.name.toLowerCase().includes('site') ? 'Investimentos por Período:' : 'Campanhas:'}
                            </h5>
                            <div className="space-y-2">
                              {Object.entries(vehicle.campaigns || {}).map(([campaign, value]) => (
                                <div key={campaign} className="flex justify-between items-center p-3 bg-muted/20 rounded-lg">
                                  <div className="flex flex-col">
                                    <span className="text-sm font-medium">{campaign}</span>
                                    {selectedCat.name.toLowerCase().includes('site') && (
                                      <span className="text-xs text-muted-foreground">Período de investimento</span>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className="font-bold text-lg">{formatCurrency(Number(value) || 0)}</span>
                                    {/* “Status” aproximado com base no comprometido da categoria */}
                                    <Badge variant="secondary">
                                      {pct((selectedCat.committed || 0), (selectedCat.globalValue || 0)) >= 50 ? 'Empenhado' : 'Pendente'}
                                    </Badge>
                                  </div>
                                </div>
                              ))}
                            </div>

                            {selectedCat.name.toLowerCase().includes('site') && (
                              <div className="mt-4 p-3 bg-primary/10 rounded-lg">
                                <div className="flex justify-between items-center">
                                  <span className="font-medium">Total investido neste site:</span>
                                  <span className="font-bold text-xl text-primary">{formatCurrency(totalUsed)}</span>
                                </div>
                              </div>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })()}
    </div>
  );
};

export default DashboardView;
