'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Upload,
  Settings,
  LogOut,
  FolderOpen,
  CheckCircle,
  Clock,
  TrendingUp,
  Plus,
  FileText,
  Trash2,
  Loader2,
  Code2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from 'sonner'

interface Scan {
  id: string
  projectName: string
  filename: string | null
  status: string
  date: string
  totalFiles: number
  unusedFunctions: number
  cleanupPercentage: number
}

interface DashboardData {
  scans: Scan[]
  totalScans: number
  completedScans: number
}

export default function DashboardPage() {
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(true)
  const [data, setData] = useState<DashboardData | null>(null)
  const [user, setUser] = useState<{ username: string; id: string } | null>(null)

  useEffect(() => {
    fetchData()
    fetchUser()
  }, [])

  const fetchData = async () => {
    try {
      const response = await fetch('/api/scans')
      if (!response.ok) {
        throw new Error('Failed to fetch data')
      }
      const result = await response.json()
      setData(result)
    } catch (error) {
      toast.error('Failed to load dashboard data')
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

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
      router.push('/')
    } catch (error) {
      toast.error('Logout failed')
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Completed':
        return (
          <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
            <CheckCircle className="w-3 h-3 mr-1" />
            Completed
          </Badge>
        )
      case 'Processing':
        return (
          <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">
            <Clock className="w-3 h-3 mr-1" />
            Processing
          </Badge>
        )
      default:
        return (
          <Badge className="bg-slate-500/10 text-slate-400 border-slate-500/20">
            {status}
          </Badge>
        )
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-400" />
      </div>
    )
  }

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
          <Button
            variant="ghost"
            className="w-full justify-start text-emerald-400 bg-emerald-500/10"
          >
            <LayoutDashboard className="w-4 h-4 mr-3" />
            Dashboard
          </Button>
          
          <Link href="/upload">
            <Button variant="ghost" className="w-full justify-start text-slate-400 hover:text-white">
              <Upload className="w-4 h-4 mr-3" />
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
          <Link href="/upload" className="w-full">
            <Button className="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white">
              <Plus className="w-4 h-4 mr-2" />
              New Scan
            </Button>
          </Link>

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
          <div className="flex justify-between items-center mb-8">
            <div>
              <h1 className="text-3xl font-bold text-white mb-1">Dashboard</h1>
              <p className="text-slate-400">
                Welcome back, <span className="text-emerald-400 font-semibold">{user?.username}</span>
              </p>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-full">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm text-emerald-400 font-medium">AI Engine Active</span>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Total Scans</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <span className="text-3xl font-bold text-white">{data?.totalScans || 0}</span>
                  <FolderOpen className="w-8 h-8 text-slate-600" />
                </div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Completed</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <span className="text-3xl font-bold text-white">{data?.completedScans || 0}</span>
                  <CheckCircle className="w-8 h-8 text-emerald-600" />
                </div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Issues Found</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <span className="text-3xl font-bold text-white">
                    {data?.scans[0]?.status === 'Completed' ? data.scans[0].unusedFunctions : 0}
                  </span>
                  <Trash2 className="w-8 h-8 text-red-600" />
                </div>
              </CardContent>
            </Card>

            <Card className="bg-slate-900/50 border-slate-800 border-l-4 border-l-emerald-500">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-slate-400">Cleanup %</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <span className="text-3xl font-bold text-emerald-400">
                    {data?.scans[0]?.status === 'Completed' ? `${data.scans[0].cleanupPercentage}%` : '–'}
                  </span>
                  <TrendingUp className="w-8 h-8 text-emerald-600" />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Recent Scans */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardHeader className="flex flex-row items-center justify-between pb-4">
              <CardTitle className="text-white">Recent Analyses</CardTitle>
              <Link href="/upload">
                <Button variant="outline" size="sm" className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10">
                  <Plus className="w-4 h-4 mr-2" />
                  New Scan
                </Button>
              </Link>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    <TableHead className="text-slate-400">Project Name</TableHead>
                    <TableHead className="text-slate-400">Source</TableHead>
                    <TableHead className="text-slate-400">Files</TableHead>
                    <TableHead className="text-slate-400">Date</TableHead>
                    <TableHead className="text-slate-400">Status</TableHead>
                    <TableHead className="text-slate-400">Results</TableHead>
                    <TableHead className="text-slate-400">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.scans && data.scans.length > 0 ? (
                    data.scans.map((scan) => (
                      <TableRow key={scan.id} className="border-slate-800 hover:bg-slate-800/30">
                        <TableCell className="text-white font-medium">{scan.projectName}</TableCell>
                        <TableCell className="text-slate-400 text-sm capitalize">{scan.source}</TableCell>
                        <TableCell className="text-slate-400 text-sm">{scan.totalFiles}</TableCell>
                        <TableCell className="text-slate-400">{formatDate(scan.date)}</TableCell>
                        <TableCell>{getStatusBadge(scan.status)}</TableCell>
                        <TableCell className={scan.status === 'Completed' ? 'text-emerald-400' : 'text-slate-600'}>
                          {scan.status === 'Completed' ? `${scan.unusedFunctions} issues` : '–'}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            {scan.status === 'Completed' && (
                              <>
                                <Link href={`/analysis/${scan.id}`}>
                                  <Button variant="ghost" size="sm" className="text-blue-400 hover:text-blue-300 p-2">
                                    <FileText className="w-4 h-4" />
                                  </Button>
                                </Link>
                                <Link href={`/cleanup/${scan.id}`}>
                                  <Button variant="ghost" size="sm" className="text-emerald-400 hover:text-emerald-300 p-2">
                                    <Trash2 className="w-4 h-4" />
                                  </Button>
                                </Link>
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-12 text-slate-500">
                        <FolderOpen className="w-12 h-12 mx-auto mb-4 text-slate-700" />
                        <p className="mb-2">No analyses yet</p>
                        <Link href="/upload" className="text-emerald-400 hover:text-emerald-300">
                          Upload your first project →
                        </Link>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}
