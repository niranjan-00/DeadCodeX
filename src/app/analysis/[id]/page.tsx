'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Settings,
  LogOut,
  Code2,
  ArrowLeft,
  Loader2,
  FileCode,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle2,
  Download,
  ExternalLink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { toast } from 'sonner'

interface Error {
  line: number
  type: string
  message: string
  severity: string
}

interface Suggestion {
  type: string
  message: string
  severity: string
}

interface CodeAnalysis {
  id: string
  filePath: string
  fileName: string
  language: string
  errors: string
  warnings: string
  suggestions: string
  originalCode: string
  rectifiedCode: string | null
  errorCount: number
  warningCount: number
  fixedCount: number
  isFixed: boolean
}

interface Scan {
  id: string
  projectName: string
  filename: string | null
  source: string
  status: string
  date: string
  totalFiles: number
  totalLines: number
  errorCount: number
  warningCount: number
  unusedFunctions: number
  cleanupPercentage: number
  codeAnalyses: CodeAnalysis[]
}

export default function AnalysisPage() {
  const router = useRouter()
  const params = useParams()
  const scanId = params.id as string
  
  const [isLoading, setIsLoading] = useState(true)
  const [scan, setScan] = useState<Scan | null>(null)
  const [user, setUser] = useState<{ username: string } | null>(null)
  const [selectedAnalysis, setSelectedAnalysis] = useState<CodeAnalysis | null>(null)
  const [isRectifying, setIsRectifying] = useState(false)

  const fetchData = async () => {
    try {
      const response = await fetch(`/api/scans/${scanId}`)
      if (!response.ok) {
        throw new Error('Failed to fetch analysis')
      }
      const data = await response.json()
      setScan(data.scan)
      
      if (data.scan.codeAnalyses.length > 0) {
        setSelectedAnalysis(data.scan.codeAnalyses[0])
      }
    } catch (error) {
      toast.error('Failed to load analysis')
      console.error(error)
    } finally {
      setIsLoading(false)
    }
  }

  const fetchUser = async () => {
    try {
      const response = await fetch('/api/user')
      if (!response.ok) {
        router.push('/login')
        return
      }
      const userData = await response.json()
      setUser(userData.user)
    } catch (error) {
      router.push('/login')
    }
  }

  useEffect(() => {
    fetchUser()
    fetchData()
    
    // Poll for updates if still processing
    const interval = setInterval(() => {
      if (scan?.status === 'Processing') {
        fetchData()
      }
    }, 3000)
    
    return () => clearInterval(interval)
  }, [scanId])

  const handleRectify = async (analysisId: string) => {
    setIsRectifying(true)
    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scanId, analysisId }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Rectification failed')
      }

      toast.success('Code rectified successfully!')
      fetchData()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Rectification failed')
    } finally {
      setIsRectifying(false)
    }
  }

  const handleDownload = async (analysis: CodeAnalysis) => {
    const code = analysis.rectifiedCode || analysis.originalCode
    const blob = new Blob([code], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${analysis.fileName}.rectified${analysis.fileName.includes('.') ? '' : '.txt'}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success('File downloaded successfully')
  }

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
      router.push('/')
    } catch (error) {
      toast.error('Logout failed')
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin text-emerald-400 mx-auto mb-4" />
          <p className="text-slate-400">Analyzing your code...</p>
        </div>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
        <div className="text-center">
          <p className="text-slate-400 mb-4">Analysis not found</p>
          <Link href="/dashboard">
            <Button>Return to Dashboard</Button>
          </Link>
        </div>
      </div>
    )
  }

  const analysis = selectedAnalysis
  const errors: Error[] = analysis ? JSON.parse(analysis.errors || '[]') : []
  const warnings: any[] = analysis ? JSON.parse(analysis.warnings || '[]') : []
  const suggestions: Suggestion[] = analysis ? JSON.parse(analysis.suggestions || '[]') : []

  return (
    <div className="min-h-screen flex bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
      {/* Sidebar */}
      <aside className="w-64 fixed left-0 top-0 h-full bg-slate-900/50 border-r border-slate-800 p-6 flex flex-col">
        <div className="flex items-center space-x-3 mb-8">
          <div className="flex items-center justify-center w-10 h-10 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-xl">
            <Code2 className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">DeadCodeX</h1>
            <p className="text-xs text-slate-500">AI-Powered Analysis</p>
          </div>
        </div>

        <nav className="flex-1 space-y-2">
          <Link href="/dashboard">
            <Button variant="ghost" className="w-full justify-start text-slate-400 hover:text-white">
              <LayoutDashboard className="w-4 h-4 mr-3" />
              Dashboard
            </Button>
          </Link>
          
          <Link href="/upload">
            <Button variant="ghost" className="w-full justify-start text-slate-400 hover:text-white">
              <FileCode className="w-4 h-4 mr-3" />
              Upload
            </Button>
          </Link>

          <Link href="/settings">
            <Button variant="ghost" className="w-full justify-start text-slate-400 hover:text-white">
              <Settings className="w-4 h-4 mr-3" />
              Settings
            </Button>
          </Link>
        </nav>

        <div className="space-y-2 pt-4 border-t border-slate-800">
          <Button
            variant="ghost"
            onClick={handleLogout}
            className="w-full justify-start text-red-400 hover:text-red-300"
          >
            <LogOut className="w-4 h-4 mr-3" />
            Logout
          </Button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 ml-64 p-8">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <Link href="/dashboard" className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Dashboard
            </Link>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-white mb-2">{scan.projectName}</h1>
                <p className="text-slate-400">
                  {scan.status === 'Completed' ? (
                    <span className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      Analysis Complete
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                      Processing...
                    </span>
                  )}
                </p>
              </div>
              {scan.status === 'Completed' && (
                <Link href={`/cleanup/${scan.id}`}>
                  <Button className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white">
                    View Cleanup Options
                  </Button>
                </Link>
              )}
            </div>
          </div>

          {/* Stats */}
          {scan.status === 'Completed' && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
              <Card className="bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-slate-400">Total Files</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-white">{scan.totalFiles}</div>
                </CardContent>
              </Card>

              <Card className="bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-slate-400">Total Lines</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-white">{scan.totalLines.toLocaleString()}</div>
                </CardContent>
              </Card>

              <Card className="bg-slate-900/50 border-slate-800 border-l-4 border-l-red-500">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-slate-400">Errors Found</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-red-400">{scan.errorCount}</div>
                </CardContent>
              </Card>

              <Card className="bg-slate-900/50 border-slate-800 border-l-4 border-l-yellow-500">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-slate-400">Warnings</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-yellow-400">{scan.warningCount}</div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Main Content */}
          {scan.status === 'Completed' && analysis && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* File List */}
              <Card className="bg-slate-900/50 border-slate-800">
                <CardHeader>
                  <CardTitle className="text-white">Analyzed Files</CardTitle>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-96">
                    <div className="space-y-2">
                      {scan.codeAnalyses.map((a) => (
                        <button
                          key={a.id}
                          onClick={() => setSelectedAnalysis(a)}
                          className={`w-full text-left p-3 rounded-lg transition-all ${
                            selectedAnalysis?.id === a.id
                              ? 'bg-emerald-500/20 border border-emerald-500/30'
                              : 'bg-slate-800/50 hover:bg-slate-800 border border-transparent'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <FileCode className="w-4 h-4 text-slate-400 flex-shrink-0" />
                              <span className="text-sm text-slate-200 truncate">{a.fileName}</span>
                            </div>
                            <Badge variant={a.errorCount > 0 ? 'destructive' : 'default'} className="ml-2">
                              {a.errorCount}
                            </Badge>
                          </div>
                        </button>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>

              {/* Analysis Details */}
              <div className="lg:col-span-2 space-y-6">
                <Card className="bg-slate-900/50 border-slate-800">
                  <CardHeader className="flex flex-row items-center justify-between">
                    <CardTitle className="text-white">{analysis.fileName}</CardTitle>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleDownload(analysis)}
                        disabled={isRectifying}
                      >
                        <Download className="w-4 h-4 mr-2" />
                        Download
                      </Button>
                      {!analysis.isFixed && (
                        <Button
                          size="sm"
                          onClick={() => handleRectify(analysis.id)}
                          disabled={isRectifying}
                          className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white"
                        >
                          {isRectifying ? (
                            <>
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                              Rectifying...
                            </>
                          ) : (
                            'AI Rectify'
                          )}
                        </Button>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent>
                    <Tabs defaultValue="errors" className="w-full">
                      <TabsList className="grid w-full grid-cols-3">
                        <TabsTrigger value="errors">
                          Errors ({errors.length})
                        </TabsTrigger>
                        <TabsTrigger value="warnings">
                          Warnings ({warnings.length})
                        </TabsTrigger>
                        <TabsTrigger value="suggestions">
                          Suggestions ({suggestions.length})
                        </TabsTrigger>
                      </TabsList>

                      <TabsContent value="errors" className="mt-4">
                        <ScrollArea className="h-64">
                          {errors.length > 0 ? (
                            <div className="space-y-3">
                              {errors.map((error, index) => (
                                <div key={index} className="flex gap-3 p-3 rounded-lg bg-slate-800/50 border border-red-500/20">
                                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                                  <div className="flex-1">
                                    <div className="flex items-center gap-2 mb-1">
                                      <Badge variant="destructive" className="text-xs">
                                        {error.type}
                                      </Badge>
                                      <span className="text-xs text-slate-500">Line {error.line}</span>
                                    </div>
                                    <p className="text-sm text-slate-200">{error.message}</p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="text-center py-8 text-slate-500">
                              <CheckCircle2 className="w-12 h-12 mx-auto mb-2 text-emerald-400" />
                              <p>No errors found</p>
                            </div>
                          )}
                        </ScrollArea>
                      </TabsContent>

                      <TabsContent value="warnings" className="mt-4">
                        <ScrollArea className="h-64">
                          {warnings.length > 0 ? (
                            <div className="space-y-3">
                              {warnings.map((warning, index) => (
                                <div key={index} className="flex gap-3 p-3 rounded-lg bg-slate-800/50 border border-yellow-500/20">
                                  <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                                  <div className="flex-1">
                                    <div className="flex items-center gap-2 mb-1">
                                      <Badge className="bg-yellow-500/10 text-yellow-400 border-yellow-500/20 text-xs">
                                        {warning.type}
                                      </Badge>
                                      <span className="text-xs text-slate-500">Line {warning.line}</span>
                                    </div>
                                    <p className="text-sm text-slate-200">{warning.message}</p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="text-center py-8 text-slate-500">
                              <CheckCircle2 className="w-12 h-12 mx-auto mb-2 text-emerald-400" />
                              <p>No warnings found</p>
                            </div>
                          )}
                        </ScrollArea>
                      </TabsContent>

                      <TabsContent value="suggestions" className="mt-4">
                        <ScrollArea className="h-64">
                          {suggestions.length > 0 ? (
                            <div className="space-y-3">
                              {suggestions.map((suggestion, index) => (
                                <div key={index} className="flex gap-3 p-3 rounded-lg bg-slate-800/50 border border-blue-500/20">
                                  <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                                  <div className="flex-1">
                                    <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 text-xs mb-2">
                                      {suggestion.type}
                                    </Badge>
                                    <p className="text-sm text-slate-200">{suggestion.message}</p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="text-center py-8 text-slate-500">
                              <Info className="w-12 h-12 mx-auto mb-2 text-blue-400" />
                              <p>No suggestions available</p>
                            </div>
                          )}
                        </ScrollArea>
                      </TabsContent>
                    </Tabs>
                  </CardContent>
                </Card>

                {/* Code Preview */}
                <Card className="bg-slate-900/50 border-slate-800">
                  <CardHeader>
                    <CardTitle className="text-white">Code Preview</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-96">
                      <pre className="text-sm font-mono text-slate-300 whitespace-pre-wrap">
                        {analysis.rectifiedCode || analysis.originalCode}
                      </pre>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
