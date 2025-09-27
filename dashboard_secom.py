import { useState, useMemo, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { TrendingUp, TrendingDown, DollarSign, FileText, AlertCircle, CheckCircle } from 'lucide-react';
import { MonthlySheet, DashboardFilter } from '@/types';

interface DashboardViewProps {
  sheets: MonthlySheet[];
  externalFilters?: { sheet?: string; tab?: string; category?: string };
  onFiltersChange?: (filters: { sheet?: string; tab?: string; category?: string }) => void;
}

export const DashboardView = ({ sheets, externalFilters, onFiltersChange }: DashboardViewProps) => {
  const [filters, setFilters] = useState<DashboardFilter>({});

  // Sync with external filters when they change
  useEffect(() => {
    if (externalFilters) {
      setFilters(prev => ({ ...prev, ...externalFilters }));
    }
  }, [externalFilters]);

  // Definir a planilha mais recente como padrão
  useEffect(() => {
    if (sheets.length > 0 && !filters.sheet && !externalFilters?.sheet) {
      const latestSheet = sheets[sheets.length - 1];
      const newFilters = { ...filters, sheet: latestSheet.id };
      setFilters(newFilters);
      onFiltersChange?.(newFilters);
    }
  }, [sheets, filters.sheet, externalFilters?.sheet, onFiltersChange]);

  const dashboardData = useMemo(() => {
    const selectedSheet = filters.sheet 
      ? sheets.find(s => s.id === filters.sheet)
      : sheets[sheets.length - 1]; // Usa a última planilha se nenhuma estiver selecionada

    if (!selectedSheet) return null;

    // Se uma aba específica foi selecionada, usar dados dessa aba
    let categoriesToUse = selectedSheet.categories;
    if (filters.tab && selectedSheet.tabs) {
      const selectedTab = selectedSheet.tabs.find(t => t.id === filters.tab);
      if (selectedTab) {
        categoriesToUse = selectedTab.categories;
      }
    }

    const filteredCategories = categoriesToUse.filter(cat => {
      if (filters.category && cat.id !== filters.category) return false;
      return true;
    });

    // Orçamento Total = valor da célula C16 (soma dos valores globais da planilha)
    // Sempre usar o total da planilha completa, não apenas das categorias filtradas
    const totalBudget = (() => {
      // Procurar por uma categoria especial que contenha o total (linha TOTAL)
      const totalCategory = selectedSheet.categories.find(cat => 
        cat.name.toLowerCase().includes('total') || 
        cat.id === 'total' || 
        cat.name === 'TOTAL' ||
        cat.name.toUpperCase() === 'TOTAL'
      );
      
      if (totalCategory && totalCategory.globalValue > 0) {
        return totalCategory.globalValue;
      }
      
      // Fallback: somar todas as categorias da planilha (exceto TOTAL para evitar duplicação)
      return selectedSheet.categories
        .filter(cat => !cat.name.toLowerCase().includes('total'))
        .reduce((sum, cat) => sum + cat.globalValue, 0);
    })();
    // Total Empenhado = soma da coluna "empenhado" de todas as categorias
    const totalCommitted = filteredCategories.reduce((sum, cat) => sum + cat.committed, 0);
    // Saldo Disponível = soma da coluna "saldo" de todas as categorias
    const totalBalance = filteredCategories.reduce((sum, cat) => sum + cat.balance, 0);

    // Dados para gráficos
    const categoryData = filteredCategories.map(cat => ({
      name: cat.name,
      orcamento: cat.globalValue,
      empenhado: cat.committed,
      saldo: cat.balance,
      percentual: (cat.committed / cat.globalValue) * 100
    }));

    const statusData = filteredCategories.flatMap(cat =>
      cat.vehicles.flatMap(vehicle =>
        Object.entries(vehicle.campaigns).map(([campaign, value]) => ({
          category: cat.name,
          vehicle: vehicle.name,
          campaign,
          value,
          status: Math.random() > 0.3 ? 'empenhado' : 'pendente' // Simulação
        }))
      )
    );

    const pendingPayments = statusData.filter(item => item.status === 'pendente').length;
    const completedCampaigns = statusData.filter(item => item.status === 'empenhado').length;

    return {
      totalBudget,
      totalCommitted,
      totalBalance,
      pendingPayments,
      completedCampaigns,
      categoryData,
      statusData
    };
  }, [sheets, filters]);

  const formatCurrency = (value: number) => {
    return value.toLocaleString('pt-BR', {
      style: 'currency',
      currency: 'BRL'
    });
  };

  if (!dashboardData) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Nenhuma planilha disponível</p>
      </div>
    );
  }

  const COLORS = ['hsl(var(--primary))', 'hsl(var(--success))', 'hsl(var(--warning))', 'hsl(var(--danger))'];

  return (
    <div className="space-y-6">
      {/* Filtros */}
      <Card>
        <CardHeader>
          <CardTitle>Filtros do Dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="text-sm font-medium mb-2 block">Planilha</label>
              <Select value={filters.sheet || ''} onValueChange={(value) => { 
                const newFilters = { ...filters, sheet: value, tab: '', category: '' };
                setFilters(newFilters);
                onFiltersChange?.(newFilters);
              }}>
                <SelectTrigger className="bg-background w-full">
                  <SelectValue placeholder="Selecione uma planilha" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50 max-w-[90vw]">
                  {sheets.map((sheet) => (
                    <SelectItem key={sheet.id} value={sheet.id} className="text-sm">
                      <span className="truncate max-w-[250px] block">{sheet.name}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            {/* Filtro de Aba */}
            <div>
              <label className="text-sm font-medium mb-2 block flex items-center gap-2">
                <span>📋</span> Aba da Planilha
              </label>
              <Select value={filters.tab || 'main'} onValueChange={(value) => {
                const newFilters = { ...filters, tab: value === 'main' ? '' : value, category: '' };
                setFilters(newFilters);
                onFiltersChange?.(newFilters);
              }}>
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="Selecione uma aba" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50">
                  <SelectItem value="main">Todas as Abas</SelectItem>
                  {sheets.find(s => s.id === filters.sheet)?.tabs?.map((tab) => (
                    <SelectItem key={tab.id} value={tab.id}>
                      {tab.name}
                    </SelectItem>
                  )) || []}
                </SelectContent>
              </Select>
            </div>
            
            
            <div>
              <label className="text-sm font-medium mb-2 block">Categoria</label>
              <Select value={filters.category || 'all'} onValueChange={(value) => {
                const newFilters = { ...filters, category: value === 'all' ? '' : value };
                setFilters(newFilters);
                onFiltersChange?.(newFilters);
              }}>
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="Todas as categorias" />
                </SelectTrigger>
                <SelectContent className="bg-background border-border z-50">
                  <SelectItem value="all">Todas as categorias</SelectItem>
                  {(() => {
                    const selectedSheet = sheets.find(s => s.id === filters.sheet);
                    if (!selectedSheet) return [];
                    
                    let categoriesToShow = selectedSheet.categories;
                    if (filters.tab && selectedSheet.tabs) {
                      const selectedTab = selectedSheet.tabs.find(t => t.id === filters.tab);
                      if (selectedTab) {
                        categoriesToShow = selectedTab.categories;
                      }
                    }
                    
                    return categoriesToShow.map((cat) => (
                      <SelectItem key={cat.id} value={cat.id}>
                        {cat.name}
                      </SelectItem>
                    ));
                  })()}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Cards de Resumo */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Orçamento Total</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCurrency(dashboardData.totalBudget)}</div>
            <p className="text-xs text-muted-foreground">
              Base para todos os empenhos
            </p>
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
              <Progress 
                value={(dashboardData.totalCommitted / dashboardData.totalBudget) * 100} 
                className="flex-1 h-2"
              />
              <Badge variant="secondary">
                {((dashboardData.totalCommitted / dashboardData.totalBudget) * 100).toFixed(1)}%
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
            <p className="text-xs text-muted-foreground">
              Valor ainda não empenhado
            </p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pendências</CardTitle>
            <AlertCircle className="h-4 w-4 text-danger" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-danger">{dashboardData.pendingPayments}</div>
            <p className="text-xs text-muted-foreground">
              Campanhas aguardando empenho
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Totalizadores por Valor Global - Categorias Específicas */}
      <Card>
        <CardHeader>
          <CardTitle>Totalizadores por Valor Global</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {(() => {
              const categoryNames = [
                'OAM', 'TVs', 'Site', 'Rádio', 'Jornais/Revistas', 
                'Criação', 'Produtora', 'Redes Sociais', 'Material Gráfico', 
                'Outdoors/Busdoor/ Mídia Exterior', 'Mídia Nacional', 'Eventos Especiais'
              ];
              
              let totalSum = 0;
              
              const results = categoryNames.map((categoryName, index) => {
                // Busca na planilha atual por nome similar
                const category = dashboardData.categoryData.find(cat => {
                  const catLower = cat.name.toLowerCase();
                  const searchLower = categoryName.toLowerCase();
                  return catLower.includes(searchLower) || 
                         searchLower.includes(catLower) ||
                         catLower === searchLower;
                });
                
                const value = category ? category.orcamento : 0;
                totalSum += value;
                
                return (
                  <div key={categoryName} className="p-4 bg-muted/30 rounded-lg border-l-4" style={{borderLeftColor: COLORS[index % COLORS.length]}}>
                    <h4 className="font-semibold text-sm mb-2">{categoryName}</h4>
                    <div className="text-xl font-bold text-primary">{formatCurrency(value)}</div>
                    <p className="text-xs text-muted-foreground mt-1">Valor Global</p>
                    {category && (
                      <p className="text-xs text-success mt-1">✓ Encontrado: {category.name}</p>
                    )}
                  </div>
                );
              });
              
              return results;
            })()}
          </div>
          <div className="mt-4 p-4 bg-primary/10 rounded-lg">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-lg">TOTAL:</span>
              <span className="font-bold text-2xl text-primary">
                {formatCurrency(
                  ['OAM', 'TVs', 'Site', 'Rádio', 'Jornais/Revistas', 
                   'Criação', 'Produtora', 'Redes Sociais', 'Material Gráfico', 
                   'Outdoors/Busdoor/ Mídia Exterior', 'Mídia Nacional', 'Eventos Especiais']
                  .reduce((sum, categoryName) => {
                    const category = dashboardData.categoryData.find(cat => {
                      const catLower = cat.name.toLowerCase();
                      const searchLower = categoryName.toLowerCase();
                      return catLower.includes(searchLower) || 
                             searchLower.includes(catLower) ||
                             catLower === searchLower;
                    });
                    return sum + (category ? category.orcamento : 0);
                  }, 0)
                )}
              </span>
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
                <XAxis 
                  dataKey="name" 
                  angle={-45}
                  textAnchor="end"
                  height={80}
                />
                <YAxis 
                  tickFormatter={(value) => `R$ ${(value / 1000000).toFixed(1)}M`}
                />
                <Tooltip 
                  formatter={(value: number) => formatCurrency(value)}
                />
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
                  label={({name, percent}) => `${name}: ${(percent * 100).toFixed(0)}%`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="orcamento"
                >
                  {dashboardData.categoryData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => formatCurrency(value)} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Lista da Categoria Selecionada */}
      {filters.category && (() => {
        const selectedSheet = sheets.find(s => s.id === filters.sheet);
        if (!selectedSheet) return null;
        
        let categoriesToUse = selectedSheet.categories;
        if (filters.tab && selectedSheet.tabs) {
          const selectedTab = selectedSheet.tabs.find(t => t.id === filters.tab);
          if (selectedTab) {
            categoriesToUse = selectedTab.categories;
          }
        }
        
        const selectedCategory = categoriesToUse.find(cat => cat.id === filters.category);
        if (!selectedCategory) return null;

        return (
          <Card>
            <CardHeader>
              <CardTitle>Detalhes da Categoria: {selectedCategory.name}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-primary">{formatCurrency(selectedCategory.globalValue)}</div>
                    <p className="text-sm text-muted-foreground">Orçamento Global</p>
                  </div>
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-success">{formatCurrency(selectedCategory.committed)}</div>
                    <p className="text-sm text-muted-foreground">Valor Empenhado</p>
                  </div>
                  <div className="text-center p-4 bg-muted/50 rounded-lg">
                    <div className="text-2xl font-bold text-warning">{formatCurrency(selectedCategory.balance)}</div>
                    <p className="text-sm text-muted-foreground">Saldo Disponível</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <h3 className="text-lg font-semibold">
                    {selectedCategory.name.toLowerCase().includes('site') ? 'Sites da Categoria' : 'Veículos da Categoria'}
                  </h3>
                  {selectedCategory.vehicles.map((vehicle, index) => (
                    <Card key={vehicle.id} className="border-l-4 border-l-primary">
                      <CardContent className="p-4">
                        <div className="flex justify-between items-start mb-3">
                          <h4 className="font-semibold text-lg">
                            {selectedCategory.name.toLowerCase().includes('site') ? `Site: ${vehicle.name}` : vehicle.name}
                          </h4>
                          <Badge variant={vehicle.balance > 0 ? "default" : "destructive"}>
                            Saldo: {formatCurrency(vehicle.balance)}
                          </Badge>
                        </div>
                        
                        <div className="grid gap-2 md:grid-cols-3 mb-4">
                          <div>
                            <span className="text-sm text-muted-foreground">
                              {selectedCategory.name.toLowerCase().includes('site') ? 'Orçamento do Site:' : 'Orçamento Total:'}
                            </span>
                            <div className="font-medium">{formatCurrency(vehicle.totalBudget)}</div>
                          </div>
                          <div>
                            <span className="text-sm text-muted-foreground">
                              {selectedCategory.name.toLowerCase().includes('site') ? 'Valor Investido:' : 'Total Usado:'}
                            </span>
                            <div className="font-medium">{formatCurrency(vehicle.totalUsed)}</div>
                          </div>
                          <div>
                            <span className="text-sm text-muted-foreground">% Utilizado:</span>
                            <div className="font-medium">
                              {((vehicle.totalUsed / vehicle.totalBudget) * 100).toFixed(1)}%
                            </div>
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
                            {selectedCategory.name.toLowerCase().includes('site') ? 'Investimentos por Período:' : 'Campanhas:'}
                          </h5>
                          <div className="space-y-2">
                            {Object.entries(vehicle.campaigns).map(([campaign, value]) => (
                              <div key={campaign} className="flex justify-between items-center p-3 bg-muted/20 rounded-lg">
                                <div className="flex flex-col">
                                  <span className="text-sm font-medium">{campaign}</span>
                                  {selectedCategory.name.toLowerCase().includes('site') && (
                                    <span className="text-xs text-muted-foreground">Período de investimento</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-lg">{formatCurrency(value)}</span>
                                  <Badge variant="secondary">
                                    {Math.random() > 0.3 ? 'Empenhado' : 'Pendente'}
                                  </Badge>
                                </div>
                              </div>
                            ))}
                          </div>
                          
                          {selectedCategory.name.toLowerCase().includes('site') && (
                            <div className="mt-4 p-3 bg-primary/10 rounded-lg">
                              <div className="flex justify-between items-center">
                                <span className="font-medium">Total investido neste site:</span>
                                <span className="font-bold text-xl text-primary">{formatCurrency(vehicle.totalUsed)}</span>
                              </div>
                            </div>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })()}
    </div>
  );
};
