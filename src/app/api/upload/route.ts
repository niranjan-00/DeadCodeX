import { NextRequest, NextResponse } from 'next/server'
import { getCurrentUser } from '@/lib/auth'
import { db } from '@/lib/db'
import { writeFile } from 'fs/promises'
import path from 'path'
import { createReadStream } from 'fs'
import unzipper from 'unzipper'

export async function POST(request: NextRequest) {
  try {
    const user = await getCurrentUser()
    
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const formData = await request.formData()
    const source = formData.get('source') as string
    const projectName = formData.get('project_name') as string || 'Untitled Project'

    let scanId: string
    let fileContents: { [key: string]: string } = {}

    if (source === 'manual') {
      const fileCount = parseInt(formData.get('file_count') as string || '0')
      
      if (fileCount === 0) {
        return NextResponse.json({ error: 'No files uploaded' }, { status: 400 })
      }

      // Create upload directory if it doesn't exist
      const uploadDir = path.join(process.cwd(), 'upload', 'projects')
      await writeFile(uploadDir, Buffer.from('')) // Ensure directory exists

      // Process uploaded files
      for (let i = 0; i < fileCount; i++) {
        const file = formData.get(`file_${i}`) as File
        
        if (file) {
          const bytes = await file.arrayBuffer()
          const buffer = Buffer.from(bytes)
          const fileName = file.name
          const filePath = path.join(uploadDir, `${Date.now()}_${fileName}`)
          
          await writeFile(filePath, buffer)
          
          // If it's a ZIP file, extract its contents
          if (fileName.endsWith('.zip')) {
            try {
              const directory = await unzipper.Open.file(filePath)
              for await (const entry of directory.files) {
                if (!entry.isDirectory && entry.type === 'File') {
                  const content = await entry.buffer()
                  const textContent = content.toString('utf-8')
                  
                  // Only include code files
                  if (isCodeFile(entry.path)) {
                    fileContents[entry.path] = textContent
                  }
                }
              }
            } catch (error) {
              console.error('Error extracting ZIP:', error)
            }
          } else if (isCodeFile(fileName)) {
            fileContents[fileName] = buffer.toString('utf-8')
          }
        }
      }

      scanId = await createScan(
        user.id,
        projectName,
        source,
        null,
        fileName(fileContents),
        Object.keys(fileContents).length,
        fileContents
      )

    } else if (source === 'github') {
      const repoUrl = formData.get('repo_url') as string
      const branch = formData.get('branch') as string || 'main'

      // TODO: Implement GitHub integration
      // For now, create a placeholder scan
      scanId = await createScan(
        user.id,
        projectName,
        source,
        repoUrl,
        repoUrl.split('/').pop() || 'repo',
        0,
        {}
      )

    } else if (source === 'drive') {
      const driveUrl = formData.get('drive_url') as string

      // TODO: Implement Google Drive integration
      scanId = await createScan(
        user.id,
        projectName,
        source,
        driveUrl,
        'drive_file',
        0,
        {}
      )

    } else if (source === 'aws') {
      const bucket = formData.get('bucket') as string
      const key = formData.get('key') as string

      // TODO: Implement AWS S3 integration
      scanId = await createScan(
        user.id,
        projectName,
        source,
        `${bucket}/${key}`,
        key.split('/').pop() || 'aws_file',
        0,
        {}
      )

    } else {
      return NextResponse.json({ error: 'Invalid source' }, { status: 400 })
    }

    return NextResponse.json({
      message: 'Upload successful',
      scanId,
    })
  } catch (error) {
    console.error('Upload error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

function isCodeFile(fileName: string): boolean {
  const codeExtensions = [
    '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
    '.py', '.java', '.go', '.rs', '.c', '.cpp', '.h',
    '.cs', '.php', '.rb', '.swift', '.kt', '.scala',
    '.json', '.yaml', '.yml', '.xml', '.toml', '.ini',
    '.css', '.scss', '.less', '.sass',
    '.html', '.htm',
    '.sql', '.sh', '.bat', '.ps1'
  ]
  return codeExtensions.some(ext => fileName.endsWith(ext))
}

function fileName(fileContents: { [key: string]: string }): string {
  const keys = Object.keys(fileContents)
  return keys.length > 0 ? keys[0] : null
}

async function createScan(
  userId: string,
  projectName: string,
  source: string,
  sourceUrl: string | null,
  filename: string | null,
  totalFiles: number,
  fileContents: { [key: string]: string }
): Promise<string> {
  const scan = await db.scan.create({
    data: {
      userId,
      projectName,
      source,
      sourceUrl,
      filename,
      totalFiles,
      status: 'Processing',
      fileContents: JSON.stringify(fileContents),
    },
  })

  // Trigger AI analysis in background
  analyzeCode(scan.id, fileContents).catch(error => {
    console.error('Analysis error:', error)
  })

  return scan.id
}

async function analyzeCode(scanId: string, fileContents: { [key: string]: string }) {
  try {
    let totalErrors = 0
    let totalWarnings = 0
    let totalLines = 0
    const analyses: any[] = []

    // Import LLM from SDK for analysis
    // This is a placeholder - in production, you'd use the actual SDK
    for (const [filePath, content] of Object.entries(fileContents)) {
      totalLines += content.split('\n').length
      
      // Basic error detection (will be replaced with AI)
      const errors = detectBasicErrors(content, filePath)
      const warnings = detectWarnings(content, filePath)
      
      totalErrors += errors.length
      totalWarnings += warnings.length

      analyses.push({
        filePath,
        fileName: path.basename(filePath),
        language: detectLanguage(filePath),
        errors,
        warnings,
        suggestions: generateSuggestions(content, filePath),
        originalCode: content,
        errorCount: errors.length,
        warningCount: warnings.length,
        fixedCount: 0,
        isFixed: false,
      })
    }

    // Update scan with results
    await db.scan.update({
      where: { id: scanId },
      data: {
        status: 'Completed',
        totalLines,
        errorCount: totalErrors,
        warningCount: totalWarnings,
        unusedFunctions: totalErrors + totalWarnings,
        cleanupPercentage: totalLines > 0 ? Math.min((totalErrors + totalWarnings) / totalLines * 100, 50) : 0,
        errors: JSON.stringify(analyses.map(a => a.errors)),
        suggestions: JSON.stringify(analyses.map(a => a.suggestions)),
        findings: JSON.stringify(analyses),
      },
    })

    // Create code analysis records
    for (const analysis of analyses) {
      await db.codeAnalysis.create({
        data: {
          scanId,
          userId: (await db.scan.findUnique({ where: { id: scanId } }))!.userId,
          filePath: analysis.filePath,
          fileName: analysis.fileName,
          language: analysis.language,
          errors: JSON.stringify(analysis.errors),
          warnings: JSON.stringify(analysis.warnings),
          suggestions: JSON.stringify(analysis.suggestions),
          originalCode: analysis.originalCode,
          errorCount: analysis.errorCount,
          warningCount: analysis.warningCount,
          fixedCount: 0,
          isFixed: false,
        },
      })
    }
  } catch (error) {
    console.error('Analysis error:', error)
    await db.scan.update({
      where: { id: scanId },
      data: {
        status: 'Failed',
      },
    })
  }
}

function detectBasicErrors(content: string, filePath: string): any[] {
  const errors: any[] = []
  const lines = content.split('\n')

  lines.forEach((line, index) => {
    // Check for console.log in production
    if (line.includes('console.log') && !line.includes('//')) {
      errors.push({
        line: index + 1,
        type: 'warning',
        message: 'console.log statement found',
        severity: 'low',
      })
    }

    // Check for TODO comments
    if (line.toLowerCase().includes('todo:')) {
      errors.push({
        line: index + 1,
        type: 'warning',
        message: 'TODO comment found',
        severity: 'low',
      })
    }

    // Check for empty catch blocks
    if (line.trim() === 'catch' || line.trim() === 'catch {') {
      errors.push({
        line: index + 1,
        type: 'error',
        message: 'Empty catch block detected',
        severity: 'medium',
      })
    }
  })

  return errors
}

function detectWarnings(content: string, filePath: string): any[] {
  const warnings: any[] = []
  const lines = content.split('\n')

  lines.forEach((line, index) => {
    // Check for unused imports (basic detection)
    if (line.includes('import') && line.includes('*')) {
      warnings.push({
        line: index + 1,
        type: 'warning',
        message: 'Wildcard import detected - may cause bundle bloat',
        severity: 'low',
      })
    }
  })

  return warnings
}

function generateSuggestions(content: string, filePath: string): any[] {
  const suggestions: any[] = []
  
  suggestions.push({
    type: 'improvement',
    message: 'Consider adding error handling for better reliability',
    severity: 'low',
  })

  suggestions.push({
    type: 'improvement',
    message: 'Add JSDoc comments for better code documentation',
    severity: 'low',
  })

  return suggestions
}

function detectLanguage(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase()
  const languageMap: { [key: string]: string } = {
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.py': 'python',
    '.java': 'java',
    '.go': 'go',
    '.rs': 'rust',
    '.c': 'c',
    '.cpp': 'cpp',
    '.cs': 'csharp',
    '.php': 'php',
    '.rb': 'ruby',
    '.swift': 'swift',
    '.kt': 'kotlin',
    '.scala': 'scala',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.xml': 'xml',
    '.toml': 'toml',
    '.css': 'css',
    '.scss': 'scss',
    '.html': 'html',
    '.sql': 'sql',
  }
  
  return languageMap[ext] || 'text'
}
