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
  CheckCircle2,
  Download,
  Trash2,
  Sparkles,
  RefreshCw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { toast } from 'sonner'

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
  cleanupPercentage: number
  codeAnalyses: CodeAnalysis[]
}

export default function CleanupPage() {
  const router = useRouter()
  const params = useParams()
  const scanId = params.id as string
  
  const [isLoading, setIsLoading] = useState(true)
  const [scan, setScan] = useState<Scan | null>(null)
  const [user, setUser] = useState<{ username: string } | null>(null)
  const [selectedAnalyses, setSelectedAnalyses] = useState<Set<string>>(new Set())
  const [isCleaning, setIsCleaning] = useState(false)

  const fetchData = async () => {
    try {
      const response = await fetch(`/api/scans/${scanId}`)
      if (!response.ok) {
        throw new Error('Failed to fetch analysis')
      }
      const data = await response.json()
      setScan(data.scan)
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
  }, [scanId])

  const handleSelectAll = () => {
    if (selectedAnalyses.size === scan?.codeAnalyses.length) {
      setSelectedAnalyses(new Set())
    } else {
      setSelectedAnalyses(new Set(scan?.codeAnalyses.map(a => a.id) || []))
    }
  }

  const handleSelectAnalysis = (analysisId: string) => {
    const newSelected = new Set(selectedAnalyses)
    if (newSelected.has(analysisId)) {
      newSelected.delete(analysisId)
    } else {
      newSelected.add(analysisId)
    }
    setSelectedAnalyses(newSelected)
  }

  const handleCleanup = async () => {
    if (selectedAnalyses.size === 0) {
      toast.error('Please select at least one file to clean up')
      return
    }

    setIsCleaning(true)
    try {
      // Rectify all selected analyses
      for (const analysisId of selectedAnalyses) {
        const response = await fetch('/api/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scanId, analysisId }),
        })

        if (!response.ok) {
          const data = await response.json()
          throw new Error(data.error || 'Rectification failed')
        }
      }

      toast.success(`Successfully cleaned up ${selectedAnalyses.size} file(s)!`)
      setSelectedAnalyses(new Set())
      fetchData()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Cleanup failed')
    } finally {
      setIsCleaning(false)
    }
  }

  const handleDownloadAll = async () => {
    if (!scan) return

    // Download all rectified code
    const rectifiedAnalyses = scan.codeAnalyses.filter(a => a.rectifiedCode)
    
    if (rectifiedAnalyses.length === 0) {
      toast.error('No rectified files available for download')
      return
    }

    // Create a simple text file with all code
    const allCode = rectifiedAnalyses.map(a => 
      `// === ${a.fileName} ===\n\n${a.rectifiedCode}\n\n`
    ).join('\n')

    const blob = new Blob([allCode], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${scan.projectName}_cleaned.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success('All cleaned files downloaded successfully')
  }

  const handleDownloadSingle = async (analysis: CodeAnalysis) => {
    const code = analysis.rectifiedCode || analysis.originalCode
    const blob = new Blob([code], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${analysis.fileName}.cleaned${analysis.fileName.includes('.') ? '' : '.txt'}`
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
          <p className="text-slate-400">Loading analysis...</p>
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

  const allFixed = scan.codeAnalyses.every(a => a.isFixed)

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
            <p className="text-xs text-slate-500">AI-Powered Cleanup</p>
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
        <div className="max-w-6xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <Link href={`/analysis/${scanId}`} className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Analysis
            </Link>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-white mb-2">Code Cleanup</h1>
                <p className="text-slate-400">
                  {scan.projectName} • {scan.totalFiles} files analyzed
                </p>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={handleDownloadAll}
                  disabled={!allFixed}
                >
                  <Download className="w-4 h-4 mr-2" />
                  Download All
                </Button>
                <Button
                  onClick={handleCleanup}
                  disabled={selectedAnalyses.size === 0 || isCleaning}
                  className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white"
                >
                  {isCleaning ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Cleaning...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4 mr-2" />
                      Clean Up Selected
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>

          {/* Cleanup Stats */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Total Issues</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold text-white">
                  {scan.errorCount + scan.warningCount}
                </div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Selected for Cleanup</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold text-emerald-400">{selectedAnalyses.size}</div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Potential Reduction</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold text-emerald-400">
                  {scan.cleanupPercentage.toFixed(1)}%
                </div>
              </CardContent>
            </Card>
          </div>

          {/* File List */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-white">Files with Issues</CardTitle>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <Checkbox
                      checked={selectedAnalyses.size === scan.codeAnalyses.length}
                      onCheckedChange={handleSelectAll}
                    />
                    Select All
                  </label>
                  <span className="text-sm text-slate-400">
                    {selectedAnalyses.size} of {scan.codeAnalyses.length} selected
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[600px]">
                <div className="space-y-3">
                  {scan.codeAnalyses.map((analysis) => (
                    <div
                      key={analysis.id}
                      className={`p-4 rounded-lg border transition-all ${
                        selectedAnalyses.has(analysis.id)
                          ? 'bg-emerald-500/10 border-emerald-500/30'
                          : 'bg-slate-800/50 border-slate-700'
                      }`}
                    >
                      <div className="flex items-start gap-4">
                        <Checkbox
                          checked={selectedAnalyses.has(analysis.id)}
                          onCheckedChange={() => handleSelectAnalysis(analysis.id)}
                          className="mt-1"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-2">
                            <FileCode className="w-5 h-5 text-slate-400 flex-shrink-0" />
                            <h3 className="text-lg font-semibold text-white truncate">
                              {analysis.fileName}
                            </h3>
                            {analysis.isFixed && (
                              <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                                <CheckCircle2 className="w-3 h-3 mr-1" />
                                Fixed
                              </Badge>
                            )}
                          </div>
                          <p className="text-sm text-slate-400 mb-3 truncate">
                            {analysis.filePath}
                          </p>
                          <div className="flex items-center gap-4">
                            <div className="flex items-center gap-2">
                              <Badge variant="destructive" className="text-xs">
                                {analysis.errorCount} Errors
                              </Badge>
                              <Badge className="bg-yellow-500/10 text-yellow-400 border-yellow-500/20 text-xs">
                                {analysis.warningCount} Warnings
                              </Badge>
                            </div>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDownloadSingle(analysis)}
                            >
                              <Download className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Summary */}
          <Card className="mt-6 bg-gradient-to-br from-emerald-500/5 to-teal-500/5 border-emerald-500/20">
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className="flex-shrink-0 w-12 h-12 bg-emerald-500/20 rounded-xl flex items-center justify-center">
                  <Sparkles className="w-6 h-6 text-emerald-400" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-white mb-1">
                    Ready to Clean Up Your Code
                  </h3>
                  <p className="text-slate-400">
                    {selectedAnalyses.size > 0
                      ? `Click "Clean Up Selected" to apply AI-powered fixes to ${selectedAnalyses.size} file(s)`
                      : 'Select files above to clean them up with AI-powered fixes'
                    }
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}
