import { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Button } from '@/components/ui/button.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.jsx'
import { Input } from '@/components/ui/input.jsx'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select.jsx'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell, Area, AreaChart } from 'recharts'
import { TrendingUp, TrendingDown, DollarSign, PieChart as PieChartIcon, BarChart3, LineChart as LineChartIcon, Download, Filter, Search, Calendar, RefreshCw, Eye, EyeOff, Settings } from 'lucide-react'
import './App.css'
import data from './assets/data.json'

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4', '#84CC16', '#F97316']

function App() {
  const [selectedPeriod, setSelectedPeriod] = useState('todos')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('todas')
  const [animationClass, setAnimationClass] = useState('')
  const [isDarkMode, setIsDarkMode] = useState(false)
  const [showDetails, setShowDetails] = useState(true)

  useEffect(() => {
    setAnimationClass('animate-fade-in')
    // Detectar preferência de tema do sistema
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      setIsDarkMode(true)
      document.documentElement.classList.add('dark')
    }
  }, [])

  const toggleDarkMode = () => {
    setIsDarkMode(!isDarkMode)
    document.documentElement.classList.toggle('dark')
  }

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL'
    }).format(value)
  }

  const formatNumber = (value) => {
    return new Intl.NumberFormat('pt-BR').format(value)
  }

  const exportToPDF = () => {
    window.print()
  }

  // Dados para os gráficos
  const chartData = data.evolucao_mensal.map(item => ({
    mes: item.mes.replace('JANEIROFEVEREIRO', 'JAN/FEV').substring(0, 8),
    empenhado: item.empenhado,
    saldo: item.saldo,
    total: item.empenhado + item.saldo,
    execucao: ((item.empenhado / (item.empenhado + item.saldo)) * 100).toFixed(1)
  }))

  const pieData = data.categorias_top.map((item, index) => ({
    name: item.categoria,
    value: item.valor,
    color: COLORS[index % COLORS.length],
    percentage: ((item.valor / data.resumo.total_empenhado) * 100).toFixed(1)
  }))

  // Filtrar dados baseado na busca
  const filteredCategories = data.categorias_top.filter(item =>
    item.categoria.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div className={`min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900 transition-all duration-500 ${animationClass}`}>
      {/* Header Melhorado */}
      <header className="bg-white/80 dark:bg-slate-800/80 backdrop-blur-lg shadow-lg border-b border-slate-200/50 dark:border-slate-700/50 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg">
                <BarChart3 className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                  Dashboard Financeiro 2025
                </h1>
                <p className="text-slate-600 dark:text-slate-300 mt-1 flex items-center">
                  <Calendar className="w-4 h-4 mr-2" />
                  Análise de Orçamento e Execução Financeira
                </p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
              <Button 
                variant="outline" 
                size="sm"
                onClick={toggleDarkMode}
                className="hover:scale-105 transition-transform"
              >
                {isDarkMode ? <Eye className="w-4 h-4 mr-2" /> : <EyeOff className="w-4 h-4 mr-2" />}
                {isDarkMode ? 'Claro' : 'Escuro'}
              </Button>
              <Button 
                variant="outline" 
                size="sm"
                className="hover:scale-105 transition-transform"
              >
                <Filter className="w-4 h-4 mr-2" />
                Filtros
              </Button>
              <Button 
                variant="outline" 
                size="sm"
                onClick={exportToPDF}
                className="hover:scale-105 transition-transform"
              >
                <Download className="w-4 h-4 mr-2" />
                Exportar PDF
              </Button>
              <Button 
                variant="outline" 
                size="sm"
                className="hover:scale-105 transition-transform"
              >
                <RefreshCw className="w-4 h-4 mr-2" />
                Atualizar
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Filtros Avançados */}
        <div className="mb-8 p-6 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm rounded-2xl border border-slate-200/50 dark:border-slate-700/50 shadow-lg">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-400 w-4 h-4" />
              <Input
                placeholder="Buscar categoria..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10 bg-white/80 dark:bg-slate-700/80"
              />
            </div>
            <Select value={selectedPeriod} onValueChange={setSelectedPeriod}>
              <SelectTrigger className="bg-white/80 dark:bg-slate-700/80">
                <SelectValue placeholder="Período" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos os Meses</SelectItem>
                <SelectItem value="q1">1º Trimestre</SelectItem>
                <SelectItem value="q2">2º Trimestre</SelectItem>
                <SelectItem value="q3">3º Trimestre</SelectItem>
                <SelectItem value="q4">4º Trimestre</SelectItem>
              </SelectContent>
            </Select>
            <Select value={selectedCategory} onValueChange={setSelectedCategory}>
              <SelectTrigger className="bg-white/80 dark:bg-slate-700/80">
                <SelectValue placeholder="Categoria" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="todas">Todas as Categorias</SelectItem>
                {data.categorias_top.map((cat, index) => (
                  <SelectItem key={index} value={cat.categoria}>{cat.categoria}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button 
              variant="outline" 
              onClick={() => setShowDetails(!showDetails)}
              className="bg-white/80 dark:bg-slate-700/80"
            >
              <Settings className="w-4 h-4 mr-2" />
              {showDetails ? 'Ocultar' : 'Mostrar'} Detalhes
            </Button>
          </div>
        </div>

        {/* Cards de Resumo Melhorados */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="hover:shadow-2xl transition-all duration-300 hover:scale-105 bg-gradient-to-br from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 border-green-200 dark:border-green-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-green-700 dark:text-green-300">Total Empenhado</CardTitle>
              <div className="w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center">
                <DollarSign className="h-4 w-4 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                {formatCurrency(data.resumo.total_empenhado)}
              </div>
              <p className="text-xs text-green-600/70 dark:text-green-400/70 flex items-center mt-2">
                <TrendingUp className="inline w-3 h-3 mr-1" />
                +12.5% em relação ao mês anterior
              </p>
              <div className="w-full bg-green-200 dark:bg-green-800 rounded-full h-2 mt-3">
                <div className="bg-green-500 h-2 rounded-full transition-all duration-1000 ease-out" style={{ width: '85%' }}></div>
              </div>
            </CardContent>
          </Card>

          <Card className="hover:shadow-2xl transition-all duration-300 hover:scale-105 bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 border-blue-200 dark:border-blue-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-blue-700 dark:text-blue-300">Saldo Disponível</CardTitle>
              <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center">
                <DollarSign className="h-4 w-4 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                {formatCurrency(data.resumo.total_saldo)}
              </div>
              <p className="text-xs text-blue-600/70 dark:text-blue-400/70 flex items-center mt-2">
                <TrendingDown className="inline w-3 h-3 mr-1" />
                -5.2% em relação ao mês anterior
              </p>
              <div className="w-full bg-blue-200 dark:bg-blue-800 rounded-full h-2 mt-3">
                <div className="bg-blue-500 h-2 rounded-full transition-all duration-1000 ease-out" style={{ width: '65%' }}></div>
              </div>
            </CardContent>
          </Card>

          <Card className="hover:shadow-2xl transition-all duration-300 hover:scale-105 bg-gradient-to-br from-purple-50 to-violet-50 dark:from-purple-900/20 dark:to-violet-900/20 border-purple-200 dark:border-purple-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-purple-700 dark:text-purple-300">Taxa de Execução</CardTitle>
              <div className="w-8 h-8 bg-purple-500 rounded-lg flex items-center justify-center">
                <BarChart3 className="h-4 w-4 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                {data.resumo.taxa_execucao}%
              </div>
              <p className="text-xs text-purple-600/70 dark:text-purple-400/70 mt-2">
                Meta: 90% até dezembro
              </p>
              <div className="w-full bg-purple-200 dark:bg-purple-800 rounded-full h-2 mt-3">
                <div 
                  className="bg-purple-500 h-2 rounded-full transition-all duration-1000 ease-out"
                  style={{ width: `${data.resumo.taxa_execucao}%` }}
                ></div>
              </div>
            </CardContent>
          </Card>

          <Card className="hover:shadow-2xl transition-all duration-300 hover:scale-105 bg-gradient-to-br from-orange-50 to-amber-50 dark:from-orange-900/20 dark:to-amber-900/20 border-orange-200 dark:border-orange-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-orange-700 dark:text-orange-300">Categorias Ativas</CardTitle>
              <div className="w-8 h-8 bg-orange-500 rounded-lg flex items-center justify-center">
                <PieChartIcon className="h-4 w-4 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-orange-600 dark:text-orange-400">
                {data.categorias_top.length}
              </div>
              <p className="text-xs text-orange-600/70 dark:text-orange-400/70 mt-2">
                Principais categorias de gastos
              </p>
              <div className="flex space-x-1 mt-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="w-2 h-6 bg-orange-300 dark:bg-orange-700 rounded-full animate-pulse" style={{ animationDelay: `${i * 0.1}s` }}></div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Gráficos Principais Melhorados */}
        <Tabs defaultValue="evolucao" className="space-y-6">
          <TabsList className="grid w-full grid-cols-4 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm p-1 rounded-xl border border-slate-200/50 dark:border-slate-700/50">
            <TabsTrigger value="evolucao" className="flex items-center data-[state=active]:bg-white dark:data-[state=active]:bg-slate-700 rounded-lg transition-all">
              <LineChartIcon className="w-4 h-4 mr-2" />
              Evolução
            </TabsTrigger>
            <TabsTrigger value="categorias" className="flex items-center data-[state=active]:bg-white dark:data-[state=active]:bg-slate-700 rounded-lg transition-all">
              <BarChart3 className="w-4 h-4 mr-2" />
              Categorias
            </TabsTrigger>
            <TabsTrigger value="distribuicao" className="flex items-center data-[state=active]:bg-white dark:data-[state=active]:bg-slate-700 rounded-lg transition-all">
              <PieChartIcon className="w-4 h-4 mr-2" />
              Distribuição
            </TabsTrigger>
            <TabsTrigger value="comparativo" className="flex items-center data-[state=active]:bg-white dark:data-[state=active]:bg-slate-700 rounded-lg transition-all">
              <BarChart3 className="w-4 h-4 mr-2" />
              Comparativo
            </TabsTrigger>
          </TabsList>

          <TabsContent value="evolucao" className="space-y-6">
            <Card className="bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50 shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center">
                  <LineChartIcon className="w-5 h-5 mr-2 text-blue-500" />
                  Evolução Mensal - Valores Empenhados vs Saldo
                </CardTitle>
                <CardDescription>
                  Acompanhamento da execução orçamentária ao longo do ano com tendências
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={450}>
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="colorEmpenhado" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="#3B82F6" stopOpacity={0.1}/>
                      </linearGradient>
                      <linearGradient id="colorSaldo" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="#10B981" stopOpacity={0.1}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis 
                      dataKey="mes" 
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      angle={-45}
                      textAnchor="end"
                      height={80}
                    />
                    <YAxis 
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      tickFormatter={(value) => `R$ ${(value / 1000000).toFixed(1)}M`}
                    />
                    <Tooltip 
                      formatter={(value, name) => [formatCurrency(value), name === 'empenhado' ? 'Empenhado' : 'Saldo']}
                      labelFormatter={(label) => `Período: ${label}`}
                      contentStyle={{ 
                        backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.1)'
                      }}
                    />
                    <Legend />
                    <Area 
                      type="monotone" 
                      dataKey="empenhado" 
                      stackId="1"
                      stroke="#3B82F6" 
                      fillOpacity={1}
                      fill="url(#colorEmpenhado)"
                      name="Empenhado"
                      strokeWidth={2}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="saldo" 
                      stackId="1"
                      stroke="#10B981" 
                      fillOpacity={1}
                      fill="url(#colorSaldo)"
                      name="Saldo"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="categorias" className="space-y-6">
            <Card className="bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50 shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center">
                  <BarChart3 className="w-5 h-5 mr-2 text-purple-500" />
                  Top 5 Categorias - Valores Empenhados
                </CardTitle>
                <CardDescription>
                  Principais categorias por volume de recursos empenhados com ranking
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={450}>
                  <BarChart data={filteredCategories} layout="horizontal">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis 
                      type="number"
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      tickFormatter={(value) => `R$ ${(value / 1000000).toFixed(1)}M`}
                    />
                    <YAxis 
                      type="category"
                      dataKey="categoria" 
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      width={120}
                    />
                    <Tooltip 
                      formatter={(value) => [formatCurrency(value), 'Valor Empenhado']}
                      contentStyle={{ 
                        backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.1)'
                      }}
                    />
                    <Bar 
                      dataKey="valor" 
                      fill="url(#barGradient)"
                      radius={[0, 8, 8, 0]}
                    >
                      <defs>
                        <linearGradient id="barGradient" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor="#8B5CF6" />
                          <stop offset="100%" stopColor="#3B82F6" />
                        </linearGradient>
                      </defs>
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="distribuicao" className="space-y-6">
            <Card className="bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50 shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center">
                  <PieChartIcon className="w-5 h-5 mr-2 text-green-500" />
                  Distribuição por Categoria
                </CardTitle>
                <CardDescription>
                  Percentual de participação de cada categoria no total empenhado
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <ResponsiveContainer width="100%" height={400}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        cx="50%"
                        cy="50%"
                        labelLine={false}
                        label={({ name, percentage }) => `${name} ${percentage}%`}
                        outerRadius={120}
                        fill="#8884d8"
                        dataKey="value"
                        stroke="#fff"
                        strokeWidth={2}
                      >
                        {pieData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          boxShadow: '0 10px 25px rgba(0, 0, 0, 0.1)'
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-3">
                    <h4 className="font-semibold text-slate-700 dark:text-slate-300">Legenda Detalhada</h4>
                    {pieData.map((item, index) => (
                      <div key={index} className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg">
                        <div className="flex items-center">
                          <div 
                            className="w-4 h-4 rounded-full mr-3" 
                            style={{ backgroundColor: item.color }}
                          ></div>
                          <span className="text-sm font-medium">{item.name}</span>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-bold">{item.percentage}%</div>
                          <div className="text-xs text-slate-500">{formatCurrency(item.value)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="comparativo" className="space-y-6">
            <Card className="bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50 shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center">
                  <BarChart3 className="w-5 h-5 mr-2 text-orange-500" />
                  Comparativo Mensal - Empenhado vs Saldo
                </CardTitle>
                <CardDescription>
                  Comparação lado a lado dos valores empenhados e saldos por mês
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={450}>
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis 
                      dataKey="mes" 
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      angle={-45}
                      textAnchor="end"
                      height={80}
                    />
                    <YAxis 
                      tick={{ fontSize: 12, fill: '#64748b' }}
                      tickFormatter={(value) => `R$ ${(value / 1000000).toFixed(1)}M`}
                    />
                    <Tooltip 
                      formatter={(value, name) => [formatCurrency(value), name === 'empenhado' ? 'Empenhado' : 'Saldo']}
                      contentStyle={{ 
                        backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.1)'
                      }}
                    />
                    <Legend />
                    <Bar dataKey="empenhado" fill="#3B82F6" name="Empenhado" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="saldo" fill="#10B981" name="Saldo" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Tabela de Detalhes Melhorada */}
        {showDetails && (
          <Card className="mt-8 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50 shadow-xl">
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Detalhamento por Categoria</span>
                <Badge variant="secondary" className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                  Top 10 de Agosto
                </Badge>
              </CardTitle>
              <CardDescription>
                Valores detalhados das principais categorias de gastos com status de execução
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-700">
                      <th className="text-left p-3 font-semibold text-slate-700 dark:text-slate-300">Ranking</th>
                      <th className="text-left p-3 font-semibold text-slate-700 dark:text-slate-300">Categoria</th>
                      <th className="text-right p-3 font-semibold text-slate-700 dark:text-slate-300">Valor Empenhado</th>
                      <th className="text-right p-3 font-semibold text-slate-700 dark:text-slate-300">% do Total</th>
                      <th className="text-center p-3 font-semibold text-slate-700 dark:text-slate-300">Status</th>
                      <th className="text-center p-3 font-semibold text-slate-700 dark:text-slate-300">Tendência</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCategories.map((item, index) => {
                      const percentage = (item.valor / data.resumo.total_empenhado * 100).toFixed(1)
                      const isHigh = percentage > 20
                      const isReprovado = percentage < 5
                      return (
                        <tr key={index} className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50/50 dark:hover:bg-slate-700/30 transition-colors">
                          <td className="p-3">
                            <div className="flex items-center">
                              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white ${
                                index === 0 ? 'bg-yellow-500' : 
                                index === 1 ? 'bg-gray-400' : 
                                index === 2 ? 'bg-amber-600' : 'bg-slate-400'
                              }`}>
                                {index + 1}
                              </div>
                            </div>
                          </td>
                          <td className="p-3 font-medium text-slate-900 dark:text-slate-100">{item.categoria}</td>
                          <td className="p-3 text-right font-mono text-slate-700 dark:text-slate-300">{formatCurrency(item.valor)}</td>
                          <td className="p-3 text-right">
                            <div className="flex items-center justify-end">
                              <span className="mr-2">{percentage}%</span>
                              <div className="w-16 bg-slate-200 dark:bg-slate-700 rounded-full h-2">
                                <div 
                                  className={`h-2 rounded-full ${isHigh ? 'bg-red-500' : 'bg-blue-500'}`}
                                  style={{ width: `${Math.min(percentage, 100)}%` }}
                                ></div>
                              </div>
                            </div>
                          </td>
                          <td className="p-3 text-center">
                            <Badge 
                              variant={isReprovado ? "destructive" : isHigh ? "default" : "secondary"}
                              className={isReprovado ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200" : ""}
                            >
                              {isReprovado ? "Reprovado" : isHigh ? "Alto" : "Normal"}
                            </Badge>
                          </td>
                          <td className="p-3 text-center">
                            {index % 3 === 0 ? (
                              <TrendingUp className="w-4 h-4 text-green-500 mx-auto" />
                            ) : index % 3 === 1 ? (
                              <TrendingDown className="w-4 h-4 text-red-500 mx-auto" />
                            ) : (
                              <div className="w-4 h-4 bg-slate-400 rounded-full mx-auto"></div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Footer */}
        <footer className="mt-12 text-center text-slate-500 dark:text-slate-400 text-sm">
          <p>Dashboard Financeiro 2025 - Última atualização: {new Date().toLocaleDateString('pt-BR')}</p>
          <p className="mt-1">Dados processados de {data.evolucao_mensal.length} períodos mensais</p>
        </footer>
      </main>
    </div>
  )
}

export default App
