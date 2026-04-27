'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Upload,
  LogOut,
  Code2,
  ArrowLeft,
  Loader2,
  Settings,
  Database,
  Download,
  Trash2,
  ShieldCheck,
  Bell,
  Moon,
  Sun,
  Save,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'

interface UserSettings {
  autoCleanup: boolean
  notifyOnError: boolean
  backupFrequency: string
  maxScansPerMonth: number
  preferredLanguage: string
  theme: string
}

export default function SettingsPage() {
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [user, setUser] = useState<{ username: string; id: string; email: string } | null>(null)
  const [settings, setSettings] = useState<UserSettings>({
    autoCleanup: false,
    notifyOnError: true,
    backupFrequency: 'weekly',
    maxScansPerMonth: 10,
    preferredLanguage: 'javascript',
    theme: 'dark',
  })

  const fetchUser = async () => {
    try {
      const response = await fetch('/api/user')
      if (!response.ok) {
        router.push('/login')
        return
      }
      const userData = await response.json()
      setUser(userData.user)
      
      // Fetch settings
      const settingsResponse = await fetch('/api/settings')
      if (settingsResponse.ok) {
        const settingsData = await settingsResponse.json()
        setSettings(settingsData.settings)
      }
    } catch (error) {
      router.push('/login')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchUser()
  }, [])

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })

      if (!response.ok) {
        throw new Error('Failed to save settings')
      }

      toast.success('Settings saved successfully!')
    } catch (error) {
      toast.error('Failed to save settings')
    } finally {
      setIsSaving(false)
    }
  }

  const handleBackup = async () => {
    try {
      const response = await fetch('/api/backup', {
        method: 'POST',
      })

      if (!response.ok) {
        throw new Error('Backup failed')
      }

      toast.success('Backup created successfully!')
    } catch (error) {
      toast.error('Failed to create backup')
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
            <p className="text-xs text-slate-500">Settings</p>
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
              <Upload className="w-4 h-4 mr-3" />
              Upload
            </Button>
          </Link>

          <Button
            variant="ghost"
            className="w-full justify-start text-emerald-400 bg-emerald-500/10"
          >
            <Settings className="w-4 h-4 mr-3" />
            Settings
          </Button>
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
        <div className="max-w-4xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <Link href="/dashboard" className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Dashboard
            </Link>
            <h1 className="text-3xl font-bold text-white mb-2">Settings</h1>
            <p className="text-slate-400">
              Manage your account preferences and settings
            </p>
          </div>

          {/* Profile Section */}
          <Card className="bg-slate-900/50 border-slate-800 mb-6">
            <CardHeader>
              <CardTitle className="text-white">Profile</CardTitle>
              <CardDescription className="text-slate-400">
                Your account information
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="username" className="text-slate-300">Username</Label>
                  <Input
                    id="username"
                    value={user?.username || ''}
                    disabled
                    className="bg-slate-950/50 border-slate-700 text-white"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-slate-300">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={user?.email || ''}
                    disabled
                    className="bg-slate-950/50 border-slate-700 text-white"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Preferences Section */}
          <Card className="bg-slate-900/50 border-slate-800 mb-6">
            <CardHeader>
              <CardTitle className="text-white">Preferences</CardTitle>
              <CardDescription className="text-slate-400">
                Customize your experience
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="auto-cleanup" className="text-slate-300">Auto Cleanup</Label>
                  <p className="text-sm text-slate-500">
                    Automatically apply fixes when errors are detected
                  </p>
                </div>
                <Switch
                  id="auto-cleanup"
                  checked={settings.autoCleanup}
                  onCheckedChange={(checked) => setSettings({ ...settings, autoCleanup: checked })}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="notify-error" className="text-slate-300">Error Notifications</Label>
                  <p className="text-sm text-slate-500">
                    Get notified when errors are found in your code
                  </p>
                </div>
                <Switch
                  id="notify-error"
                  checked={settings.notifyOnError}
                  onCheckedChange={(checked) => setSettings({ ...settings, notifyOnError: checked })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="backup-frequency" className="text-slate-300">Backup Frequency</Label>
                <Select
                  value={settings.backupFrequency}
                  onValueChange={(value) => setSettings({ ...settings, backupFrequency: value })}
                >
                  <SelectTrigger id="backup-frequency" className="bg-slate-950/50 border-slate-700 text-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-900 border-slate-700">
                    <SelectItem value="daily" className="text-white">Daily</SelectItem>
                    <SelectItem value="weekly" className="text-white">Weekly</SelectItem>
                    <SelectItem value="monthly" className="text-white">Monthly</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="language" className="text-slate-300">Preferred Language</Label>
                <Select
                  value={settings.preferredLanguage}
                  onValueChange={(value) => setSettings({ ...settings, preferredLanguage: value })}
                >
                  <SelectTrigger id="language" className="bg-slate-950/50 border-slate-700 text-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-900 border-slate-700">
                    <SelectItem value="javascript" className="text-white">JavaScript</SelectItem>
                    <SelectItem value="typescript" className="text-white">TypeScript</SelectItem>
                    <SelectItem value="python" className="text-white">Python</SelectItem>
                    <SelectItem value="java" className="text-white">Java</SelectItem>
                    <SelectItem value="go" className="text-white">Go</SelectItem>
                    <SelectItem value="rust" className="text-white">Rust</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="theme" className="text-slate-300">Theme</Label>
                <Select
                  value={settings.theme}
                  onValueChange={(value) => setSettings({ ...settings, theme: value })}
                >
                  <SelectTrigger id="theme" className="bg-slate-950/50 border-slate-700 text-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-900 border-slate-700">
                    <SelectItem value="dark" className="text-white">Dark</SelectItem>
                    <SelectItem value="light" className="text-white">Light</SelectItem>
                    <SelectItem value="system" className="text-white">System</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          {/* Data Management Section */}
          <Card className="bg-slate-900/50 border-slate-800 mb-6">
            <CardHeader>
              <CardTitle className="text-white">Data Management</CardTitle>
              <CardDescription className="text-slate-400">
                Backup and restore your data
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between p-4 rounded-lg bg-slate-800/50">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-500/10 rounded-lg">
                    <Database className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-white">Create Backup</h3>
                    <p className="text-xs text-slate-400">Download all your analysis data</p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleBackup}
                  className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Backup
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Save Button */}
          <div className="flex justify-end">
            <Button
              onClick={handleSave}
              disabled={isSaving}
              className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white"
            >
              {isSaving ? (
                <>
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="mr-2 h-5 w-5" />
                  Save Changes
                </>
              )}
            </Button>
          </div>
        </div>
      </main>
    </div>
  )
}
