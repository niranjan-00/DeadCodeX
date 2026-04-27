'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useDropzone } from 'react-dropzone'
import {
  LayoutDashboard,
  Upload as UploadIcon,
  Settings,
  LogOut,
  Code2,
  CloudUpload,
  X,
  CheckCircle2,
  Loader2,
  ArrowLeft,
  Github,
  Cloud,
  Database,
  FileCode,
  FolderOpen,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from 'sonner'

interface UploadedFile {
  file: File
  preview: string
}

export default function UploadPage() {
  const router = useRouter()
  const [isUploading, setIsUploading] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [user, setUser] = useState<{ username: string } | null>(null)
  const [activeTab, setActiveTab] = useState('manual')
  
  // GitHub form state
  const [githubRepo, setGithubRepo] = useState('')
  const [githubBranch, setGithubBranch] = useState('main')
  
  // Google Drive form state
  const [driveUrl, setDriveUrl] = useState('')
  
  // AWS form state
  const [awsBucket, setAwsBucket] = useState('')
  const [awsKey, setAwsKey] = useState('')

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
  }, [router])

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map(file => ({
      file,
      preview: URL.createObjectURL(file)
    }))
    setUploadedFiles(prev => [...prev, ...newFiles])
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/zip': ['.zip'],
      'application/x-tar': ['.tar'],
      'application/gzip': ['.gz', '.tgz'],
      'application/x-rar-compressed': ['.rar'],
      'application/x-7z-compressed': ['.7z'],
      'text/plain': ['.txt', '.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.go', '.rs'],
      'application/json': ['.json'],
    },
    multiple: true,
  })

  const handleRemoveFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const handleUpload = async (source: string) => {
    setIsUploading(true)

    try {
      const formData = new FormData()
      
      if (projectName.trim()) {
        formData.append('project_name', projectName.trim())
      }
      
      formData.append('source', source)

      if (source === 'manual') {
        if (uploadedFiles.length === 0) {
          toast.error('Please select files to upload')
          setIsUploading(false)
          return
        }
        
        // Handle multiple files
        uploadedFiles.forEach(({ file }, index) => {
          formData.append(`file_${index}`, file)
        })
        formData.append('file_count', uploadedFiles.length.toString())
      } else if (source === 'github') {
        if (!githubRepo.trim()) {
          toast.error('Please enter a GitHub repository URL')
          setIsUploading(false)
          return
        }
        formData.append('repo_url', githubRepo.trim())
        formData.append('branch', githubBranch)
      } else if (source === 'drive') {
        if (!driveUrl.trim()) {
          toast.error('Please enter a Google Drive URL')
          setIsUploading(false)
          return
        }
        formData.append('drive_url', driveUrl.trim())
      } else if (source === 'aws') {
        if (!awsBucket.trim()) {
          toast.error('Please enter AWS bucket details')
          setIsUploading(false)
          return
        }
        formData.append('bucket', awsBucket.trim())
        formData.append('key', awsKey.trim())
      }

      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Upload failed')
      }

      toast.success('Project uploaded successfully!')
      router.push(`/analysis/${data.scanId}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Upload failed')
    } finally {
      setIsUploading(false)
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
          
          <Button
            variant="ghost"
            className="w-full justify-start text-emerald-400 bg-emerald-500/10"
          >
            <UploadIcon className="w-4 h-4 mr-3" />
            Upload
          </Button>

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
        <div className="max-w-4xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <Link href="/dashboard" className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Dashboard
            </Link>
            <h1 className="text-3xl font-bold text-white mb-2">Upload Code</h1>
            <p className="text-slate-400">
              Choose how you want to provide your code for analysis
            </p>
          </div>

          {/* Upload Form */}
          <Card className="bg-slate-900/50 border-slate-800">
            <CardContent className="pt-6">
              <div className="space-y-6">
                {/* Project Name */}
                <div className="space-y-2">
                  <Label htmlFor="project_name" className="text-slate-300">Project Name (Optional)</Label>
                  <Input
                    id="project_name"
                    type="text"
                    placeholder="e.g., My Awesome Project"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    disabled={isUploading}
                    className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                  />
                </div>

                {/* Tabs for different upload sources */}
                <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                  <TabsList className="grid w-full grid-cols-4 bg-slate-950/50">
                    <TabsTrigger value="manual" className="data-[state=active]:bg-emerald-500/20 data-[state=active]:text-emerald-400">
                      <UploadIcon className="w-4 h-4 mr-2" />
                      Files
                    </TabsTrigger>
                    <TabsTrigger value="github" className="data-[state=active]:bg-emerald-500/20 data-[state=active]:text-emerald-400">
                      <Github className="w-4 h-4 mr-2" />
                      GitHub
                    </TabsTrigger>
                    <TabsTrigger value="drive" className="data-[state=active]:bg-emerald-500/20 data-[state=active]:text-emerald-400">
                      <Cloud className="w-4 h-4 mr-2" />
                      Drive
                    </TabsTrigger>
                    <TabsTrigger value="aws" className="data-[state=active]:bg-emerald-500/20 data-[state=active]:text-emerald-400">
                      <Database className="w-4 h-4 mr-2" />
                      AWS
                    </TabsTrigger>
                  </TabsList>

                  {/* Manual File Upload */}
                  <TabsContent value="manual" className="space-y-4 mt-4">
                    <div
                      {...getRootProps()}
                      className={`
                        border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all
                        ${isDragActive
                          ? 'border-emerald-500 bg-emerald-500/5'
                          : 'border-slate-700 hover:border-slate-600 bg-slate-950/30'
                        }
                      `}
                    >
                      <input {...getInputProps()} />
                      <CloudUpload className="w-16 h-16 mx-auto mb-4 text-slate-600" />
                      <p className="text-lg text-white mb-2">
                        {isDragActive ? 'Drop the files here' : 'Drag and drop your files'}
                      </p>
                      <p className="text-sm text-slate-500 mb-4">or</p>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={isUploading}
                        className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
                        onClick={(e) => {
                          e.stopPropagation()
                          document.querySelector('input[type="file"]')?.click()
                        }}
                      >
                        Browse Files
                      </Button>
                      <p className="text-xs text-slate-600 mt-4">
                        Maximum file size: 50MB • Supported: ZIP, TAR, code files
                      </p>
                    </div>

                    {/* Uploaded Files List */}
                    {uploadedFiles.length > 0 && (
                      <div className="space-y-2">
                        <Label className="text-slate-300">Uploaded Files ({uploadedFiles.length})</Label>
                        <div className="space-y-2 max-h-64 overflow-y-auto">
                          {uploadedFiles.map((item, index) => (
                            <Card key={index} className="bg-slate-950/50 border-slate-700">
                              <CardContent className="p-4">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-3 flex-1 min-w-0">
                                    <div className="flex-shrink-0 w-10 h-10 bg-emerald-500/10 rounded-lg flex items-center justify-center">
                                      <FileCode className="w-5 h-5 text-emerald-400" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <p className="text-sm font-medium text-white truncate">{item.file.name}</p>
                                      <p className="text-xs text-slate-500">
                                        {(item.file.size / 1024).toFixed(2)} KB
                                      </p>
                                    </div>
                                  </div>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => handleRemoveFile(index)}
                                    disabled={isUploading}
                                    className="text-slate-400 hover:text-red-400"
                                  >
                                    <X className="w-4 h-4" />
                                  </Button>
                                </div>
                              </CardContent>
                            </Card>
                          ))}
                        </div>
                      </div>
                    )}
                  </TabsContent>

                  {/* GitHub Repository */}
                  <TabsContent value="github" className="space-y-4 mt-4">
                    <div className="space-y-2">
                      <Label htmlFor="github_repo" className="text-slate-300">GitHub Repository URL</Label>
                      <Input
                        id="github_repo"
                        type="text"
                        placeholder="https://github.com/username/repo"
                        value={githubRepo}
                        onChange={(e) => setGithubRepo(e.target.value)}
                        disabled={isUploading}
                        className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="github_branch" className="text-slate-300">Branch</Label>
                      <Input
                        id="github_branch"
                        type="text"
                        placeholder="main"
                        value={githubBranch}
                        onChange={(e) => setGithubBranch(e.target.value)}
                        disabled={isUploading}
                        className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                      />
                    </div>
                  </TabsContent>

                  {/* Google Drive */}
                  <TabsContent value="drive" className="space-y-4 mt-4">
                    <div className="space-y-2">
                      <Label htmlFor="drive_url" className="text-slate-300">Google Drive File/Folder URL</Label>
                      <Input
                        id="drive_url"
                        type="text"
                        placeholder="https://drive.google.com/file/d/..."
                        value={driveUrl}
                        onChange={(e) => setDriveUrl(e.target.value)}
                        disabled={isUploading}
                        className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                      />
                    </div>
                  </TabsContent>

                  {/* AWS S3 */}
                  <TabsContent value="aws" className="space-y-4 mt-4">
                    <div className="space-y-2">
                      <Label htmlFor="aws_bucket" className="text-slate-300">S3 Bucket Name</Label>
                      <Input
                        id="aws_bucket"
                        type="text"
                        placeholder="my-bucket-name"
                        value={awsBucket}
                        onChange={(e) => setAwsBucket(e.target.value)}
                        disabled={isUploading}
                        className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="aws_key" className="text-slate-300">Object Key (Path to file)</Label>
                      <Input
                        id="aws_key"
                        type="text"
                        placeholder="path/to/file.zip"
                        value={awsKey}
                        onChange={(e) => setAwsKey(e.target.value)}
                        disabled={isUploading}
                        className="bg-slate-950/50 border-slate-700 text-white placeholder:text-slate-500"
                      />
                    </div>
                  </TabsContent>
                </Tabs>

                {/* Submit Button */}
                <Button
                  onClick={() => handleUpload(activeTab)}
                  size="lg"
                  className="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white"
                  disabled={isUploading || (activeTab === 'manual' && uploadedFiles.length === 0)}
                >
                  {isUploading ? (
                    <>
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      Analyzing Code...
                    </>
                  ) : (
                    <>
                      <Sparkles className="mr-2 h-5 w-5" />
                      Start Analysis
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}

function Sparkles(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
    </svg>
  )
}
